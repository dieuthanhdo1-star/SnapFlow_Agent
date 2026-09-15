"""Persistent screenshot intake queue; model calls use two workers, never auto-retry."""
import json
import re
import secrets
import threading
from concurrent.futures import ThreadPoolExecutor


class BatchMixin:
    def init_batches(self):
        self.batch_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="snapflow-image")
        self.batch_lock = threading.RLock()
        with self.db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS image_jobs (
                    id TEXT PRIMARY KEY, batch_id TEXT NOT NULL, image TEXT NOT NULL,
                    filename TEXT NOT NULL, mode TEXT NOT NULL, status TEXT NOT NULL,
                    draft_id TEXT NOT NULL DEFAULT '', error TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    saved_item_id TEXT NOT NULL DEFAULT '',
                    UNIQUE(batch_id,image));
                CREATE TABLE IF NOT EXISTS image_job_actions (
                    id TEXT PRIMARY KEY, job_id TEXT NOT NULL, draft_id TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL DEFAULT 'ready', saved_item_id TEXT NOT NULL DEFAULT '');
                CREATE INDEX IF NOT EXISTS job_actions_parent ON image_job_actions(job_id);
            """)
            # Upgrade existing single-result batches without replacing their IDs or user data.
            db.execute("""INSERT OR IGNORE INTO image_job_actions(id,job_id,draft_id,status,saved_item_id)
                SELECT id,id,draft_id,status,saved_item_id FROM image_jobs
                WHERE draft_id!='' AND status IN ('ready','saved','cancelled')""")

    def recover_batches(self):
        # Only the real server calls this at startup, never each test App instance.
        with self.db() as db:
            db.execute("""UPDATE image_jobs SET status='interrupted',error='上次识别中断，结果未核实；可单独重试。'
                WHERE status IN ('queued','running')""")

    def batch_jobs(self, batch_id):
        with self.db() as db:
            rows = db.execute("""SELECT j.*, d.payload FROM image_jobs j
                LEFT JOIN drafts d ON d.id=j.draft_id WHERE j.batch_id=? ORDER BY j.rowid""", (batch_id,)).fetchall()
        result = []
        for row in rows:
            job = dict(row)
            payload = job.pop("payload")
            job["draft"] = json.loads(payload) if payload else None
            with self.db() as db:
                actions = db.execute("""SELECT a.*, d.payload FROM image_job_actions a
                    JOIN drafts d ON d.id=a.draft_id WHERE a.job_id=? ORDER BY a.rowid""", (job['id'],)).fetchall()
            if actions:
                for index, action in enumerate(actions):
                    result.append(dict(job, id=action['id'], image_job_id=job['id'],
                        action_index=index + 1, action_count=len(actions), draft_id=action['draft_id'],
                        status=action['status'], saved_item_id=action['saved_item_id'],
                        draft=json.loads(action['payload'])))
            else:
                result.append(dict(job, image_job_id=job['id'], action_index=1, action_count=1))
        return {"batch_id": batch_id, "jobs": result}

    def current_batch(self):
        with self.db() as db:
            row = db.execute("""SELECT batch_id FROM image_jobs
                WHERE status NOT IN ('saved','cancelled') ORDER BY rowid DESC LIMIT 1""").fetchone()
        return self.batch_jobs(row["batch_id"]) if row else {"batch_id": "", "jobs": []}

    def enqueue_image(self, body):
        from server import Problem, now_iso, text_field
        batch_id, job_id = body.get("batch_id", ""), body.get("request_id", "")
        if not all(isinstance(v, str) and re.fullmatch(r"[a-f0-9]{32}", v) for v in [batch_id, job_id]):
            raise Problem("上传标识无效，请刷新页面后重试。")
        mode = "ai" if self.public_config()["vision"] else "manual"
        image = self.save_image(body.get("image", ""))
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT id,batch_id,image FROM image_jobs WHERE id=? OR (batch_id=? AND image=?)",
                             (job_id, batch_id, image)).fetchone()
            if old:
                if old["batch_id"] != batch_id or old["image"] != image:
                    raise Problem("上传标识冲突，请重新选择文件。", 409)
                return {"job_id": old["id"], "duplicate": True, "batch_id": batch_id}
            count = db.execute("SELECT count(*) FROM image_jobs WHERE batch_id=? AND status!='cancelled'", (batch_id,)).fetchone()[0]
            pending = db.execute("SELECT count(*) FROM image_jobs WHERE status IN ('queued','running')").fetchone()[0]
            if count >= 30:
                raise Problem("每批最多 30 张，请先处理当前清单。")
            if pending >= 60:
                raise Problem("正在整理的截图较多，请稍后再上传。", 429)
            db.execute("""INSERT INTO image_jobs(id,batch_id,image,filename,mode,status,created_at,updated_at)
                VALUES(?,?,?,?,?,'queued',?,?)""", (job_id, batch_id, image, text_field(body.get("filename"), 160) or "截图", mode, now_iso(), now_iso()))
        self.batch_pool.submit(self.process_image, job_id)
        return {"job_id": job_id, "duplicate": False, "batch_id": batch_id}

    def process_image(self, job_id):
        import base64
        from server import Problem, now_iso
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM image_jobs WHERE id=?", (job_id,)).fetchone()
            if not row or row["status"] != "queued":
                return
            db.execute("UPDATE image_jobs SET status='running',updated_at=? WHERE id=?", (now_iso(), job_id))
        try:
            if hasattr(self, 'agent') and not self.agent.allowed(job_id):
                with self.db() as db:
                    db.execute("UPDATE image_jobs SET status='interrupted',error='自动处理授权已暂停或撤销；可手动重试。' WHERE id=?", (job_id,))
                return
            raw = (self.uploads / row["image"]).read_bytes()
            image = "data:image/" + row["image"].split(".")[-1] + ";base64," + base64.b64encode(raw).decode()
            # Empty context is intentional: classification must come from the screenshot.
            draft = self.analyze({"image": image, "mode": row["mode"], "context": "", "multiple": True})
            drafts = draft.get('actions', [draft])
            with self.db() as db:
                changed = db.execute("UPDATE image_jobs SET status='ready',draft_id=?,error='',updated_at=? WHERE id=? AND status='running'",
                                     (draft["id"], now_iso(), job_id)).rowcount
                if changed:
                    for index, part in enumerate(drafts):
                        db.execute("INSERT INTO image_job_actions(id,job_id,draft_id) VALUES(?,?,?)",
                            (job_id if index == 0 else secrets.token_hex(16), job_id, part['id']))
            if changed and hasattr(self, 'agent'):
                self.agent.finish_job(job_id)
            if not changed:
                for part in drafts:
                    self.cancel(part["id"])
        except Exception as exc:
            message = str(exc) if isinstance(exc, Problem) else "这张截图暂时未能识别，可单独重试或手动填写。"
            with self.db() as db:
                db.execute("UPDATE image_jobs SET status='failed',error=?,updated_at=? WHERE id=? AND status='running'", (message, now_iso(), job_id))

    def update_image_job(self, job_id, body):
        with self.batch_lock:
            return self._update_image_job(job_id, body)

    def _update_image_job(self, job_id, body):
        from server import Problem, now_iso
        action = body.get("action")
        submit = False
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            part = db.execute('SELECT * FROM image_job_actions WHERE id=?', (job_id,)).fetchone()
            if part:
                if action != 'cancel' or part['status'] == 'saved':
                    raise Problem("已识别的事项可编辑或移出；已保存的事项请在行动列表查看。", 409)
                db.execute("UPDATE image_job_actions SET status='cancelled' WHERE id=?", (job_id,))
                db.execute('UPDATE drafts SET cancelled=1 WHERE id=?', (part['draft_id'],))
                self.sync_image_status(db, part['job_id'])
                batch_id = db.execute('SELECT batch_id FROM image_jobs WHERE id=?', (part['job_id'],)).fetchone()[0]
                db.commit()
                return self.batch_jobs(batch_id)
            job = db.execute("SELECT * FROM image_jobs WHERE id=?", (job_id,)).fetchone()
            if not job:
                raise Problem("未找到这张截图。", 404)
            if action == "cancel":
                if job["status"] == "saved":
                    raise Problem("这条行动已保存，请在行动列表中查看。", 409)
                db.execute("UPDATE image_jobs SET status='cancelled',updated_at=? WHERE id=?", (now_iso(), job_id))
                if job["draft_id"]:
                    db.execute("UPDATE drafts SET cancelled=1 WHERE id=?", (job["draft_id"],))
            elif action in {"retry", "manual"}:
                if job["status"] not in {"failed", "interrupted"}:
                    raise Problem("只有失败或中断的截图可以重试。", 409)
                mode = "manual" if action == "manual" else "ai"
                if mode == "ai" and not self.public_config()["vision"]:
                    raise Problem("模型尚未连接，可先手动填写。")
                if db.execute("SELECT count(*) FROM image_jobs WHERE status IN ('queued','running')").fetchone()[0] >= 60:
                    raise Problem("正在整理的截图较多，请稍后重试。", 429)
                db.execute("UPDATE image_jobs SET status='queued',mode=?,error='',updated_at=? WHERE id=?", (mode, now_iso(), job_id))
                submit = True
            else:
                raise Problem("未知操作。")
        if submit:
            if hasattr(self, 'agent'):
                with self.db() as db:
                    db.execute("UPDATE agent_jobs SET source_id='',generation=0 WHERE job_id=?", (job_id,))
            self.batch_pool.submit(self.process_image, job_id)
        return self.batch_jobs(job["batch_id"])

    def sync_image_status(self, db, job_id):
        from server import now_iso
        parts = db.execute('SELECT status,saved_item_id FROM image_job_actions WHERE job_id=?', (job_id,)).fetchall()
        status = 'ready' if any(p['status'] == 'ready' for p in parts) else ('saved' if any(p['status'] == 'saved' for p in parts) else 'cancelled')
        saved = next((p['saved_item_id'] for p in parts if p['saved_item_id']), '')
        db.execute('UPDATE image_jobs SET status=?,saved_item_id=?,updated_at=? WHERE id=?', (status, saved, now_iso(), job_id))

    def confirm_batch(self, body):
        from server import Problem, now_iso
        if body.get("confirmed") is not True:
            raise Problem("请确认选中的行动后再保存。")
        entries = body.get("entries")
        if not isinstance(entries, list) or not 1 <= len(entries) <= 300:
            raise Problem("请选择 1～300 条行动。")
        # Serialize confirmation and job cancellation; per-item failures are isolated.
        results = []
        with self.batch_lock:
            for entry in entries:
                job_id = entry.get("job_id", "") if isinstance(entry, dict) else ""
                try:
                    with self.db() as db:
                        job = db.execute("""SELECT a.* FROM image_job_actions a JOIN image_jobs j ON j.id=a.job_id
                            WHERE a.id=? AND j.batch_id=?""", (job_id, body.get("batch_id", ""))).fetchone()
                    if not job or job["status"] not in {"ready", "saved"}:
                        raise Problem("这张截图尚未准备好，或已移出清单。")
                    fields = entry.get("fields", {})
                    if not isinstance(fields, dict):
                        raise Problem("行动字段无效。")
                    item = self.confirm(dict(fields, draft_id=job["draft_id"], confirmed=True))
                    with self.db() as db:
                        db.execute("UPDATE image_job_actions SET status='saved',saved_item_id=? WHERE id=?", (item["id"], job_id))
                        self.sync_image_status(db, job['job_id'])
                    results.append({"job_id": job_id, "saved": True, "item_id": item["id"]})
                except Problem as exc:
                    results.append({"job_id": job_id, "saved": False, "error": str(exc)})
        return {"results": results}
