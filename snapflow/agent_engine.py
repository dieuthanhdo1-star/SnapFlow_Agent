"""Persistent, consent-bound Windows screenshot automation."""
import base64
import hashlib
import json
import os
import secrets
import threading
import time
from pathlib import Path
from skills_engine import SKILLS, normalize, review_reasons

SCAN_INTERVAL = 3


class AlbumAgent:
    def __init__(self, app):
        self.app = app
        self.lock = threading.RLock()
        self.pending = {}
        self.observed = {}
        self.last_scan = ''
        self.error = ''
        with app.db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS album_sources (
                    id TEXT PRIMARY KEY, path TEXT UNIQUE NOT NULL, enabled INTEGER NOT NULL,
                    generation INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS album_files (
                    source_id TEXT NOT NULL, name TEXT NOT NULL, signature TEXT NOT NULL,
                    state TEXT NOT NULL, error TEXT NOT NULL DEFAULT '', PRIMARY KEY(source_id,name));
                CREATE TABLE IF NOT EXISTS agent_jobs (
                    job_id TEXT PRIMARY KEY, digest TEXT UNIQUE NOT NULL, source_id TEXT NOT NULL,
                    generation INTEGER NOT NULL, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS agent_settings (id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL);
            ''')
            db.execute('INSERT OR IGNORE INTO agent_settings VALUES(1,?)', (json.dumps({'skills': list(SKILLS), 'daily_limit': 100, 'sync_events': False, 'sync_tasks': False, 'calendar_target': '', 'task_target': ''}),))

    def settings(self):
        with self.app.db() as db:
            return json.loads(db.execute('SELECT payload FROM agent_settings WHERE id=1').fetchone()[0])

    def configure(self, body):
        from server import Problem
        with self.lock:
            value = self.settings()
            skills = body.get('skills', value['skills'])
            if not isinstance(skills, list) or not all(isinstance(s, str) and s in SKILLS for s in skills):
                raise Problem('处理能力选择无效。')
            limit = body.get('daily_limit', value['daily_limit'])
            if type(limit) is not int or not 1 <= limit <= 1000: raise Problem('每天识别上限为 1～1000 张。')
            value.update(skills=list(dict.fromkeys(skills)), daily_limit=limit)
            for key, target_key, target in [('sync_events', 'calendar_target', self.app.feishu.target()),
                                            ('sync_tasks', 'task_target', self.app.feishu.task_target())]:
                if key in body:
                    enabled = body[key] is True
                    if enabled and (not target or body.get(target_key) != target):
                        raise Problem('请先连接飞书并确认当前同步目标。', 409)
                    value[key] = enabled
                    value[target_key] = target if enabled else ''
            with self.app.db() as db:
                db.execute('UPDATE agent_settings SET payload=? WHERE id=1', (json.dumps(value),))
        return value

    def pick(self):
        from native_album import choose_folder
        path = choose_folder()
        if path is None: return {'cancelled': True}
        return self.prepare_path({'path':str(path)})

    def prepare_path(self, body):
        from server import Problem
        raw=body.get('path')
        if not isinstance(raw,str) or not raw.strip() or len(raw)>4096 or '\x00' in raw:
            raise Problem('请填写截图文件夹的完整路径。')
        raw=raw.strip().strip('"')
        path=Path(raw)
        if not path.is_absolute(): raise Problem('请填写完整路径，例如 D:\\CodeProgram\\AgentM\\截图。')
        try:
            path=path.resolve(strict=True)
            if not path.is_dir():raise Problem('这不是文件夹，请选择存放截图的文件夹。')
        except (OSError,RuntimeError):raise Problem('找不到这个文件夹，请检查路径是否正确、文件夹是否已创建。')
        nonce = secrets.token_urlsafe(32)
        with self.lock:
            self.pending = {k: v for k, v in self.pending.items() if v[1] > time.time()}
            self.pending[nonce] = (path, time.time()+600)
        return {'token': nonce, 'path': str(path), 'name': path.name or str(path)}

    def authorize(self, body):
        from server import Problem, now_iso
        if body.get('confirmed') is not True: raise Problem('请授权读取所选文件夹并使用模型处理截图。')
        with self.lock:
            selected = self.pending.pop(body.get('token', ''), None)
            if not selected or selected[1] <= time.time(): raise Problem('文件夹选择已过期，请重新选择。')
            path = selected[0]
            if not path.is_dir(): raise Problem('文件夹不可用，请重新选择。')
            source_id = secrets.token_hex(16)
            with self.app.db() as db:
                # A single active folder keeps the scope obvious in the UI.
                db.execute('UPDATE album_sources SET enabled=0,generation=generation+1')
                old = db.execute('SELECT id FROM album_sources WHERE path=?', (str(path),)).fetchone()
                if old:
                    source_id = old['id']
                    db.execute('UPDATE album_sources SET enabled=1 WHERE id=?', (source_id,))
                else:
                    db.execute('INSERT INTO album_sources(id,path,enabled,created_at) VALUES(?,?,1,?)', (source_id,str(path),now_iso()))
                if body.get('include_existing') is not True:
                    for p in path.iterdir():
                        if self.safe_file(path,p):
                            stat = p.stat()
                            db.execute("INSERT OR REPLACE INTO album_files VALUES(?,?,?,'skipped','')", (source_id,p.name,self.signature(stat)))
        return self.status()

    def source_action(self, body):
        from server import Problem
        action = body.get('action')
        if action not in {'pause','resume','revoke'}: raise Problem('操作无效。')
        with self.lock, self.app.db() as db:
            row = db.execute('SELECT * FROM album_sources WHERE id=?', (body.get('id',''),)).fetchone()
            if not row: raise Problem('未找到已授权文件夹。',404)
            if action == 'resume':
                if not Path(row['path']).is_dir(): raise Problem('文件夹不可用。')
                db.execute('UPDATE album_sources SET enabled=0 WHERE id!=?',(row['id'],))
                db.execute('UPDATE album_sources SET enabled=1 WHERE id=?',(row['id'],))
            else:
                db.execute('UPDATE album_sources SET enabled=0,generation=generation+1 WHERE id=?',(row['id'],))
                if action == 'revoke':
                    # Retain dedup history, but forget the authorized filesystem location.
                    db.execute('DELETE FROM album_sources WHERE id=?',(row['id'],))
        return self.status()

    @staticmethod
    def signature(stat): return f'{stat.st_size}:{stat.st_mtime_ns}'

    @staticmethod
    def safe_file(root, path):
        try:
            # Exclude symlinks, junctions/reparse points, subfolders and unsupported formats.
            return (not path.is_symlink() and not (getattr(path.lstat(),'st_file_attributes',0) & 0x400)
                    and path.is_file() and path.suffix.lower() in {'.png','.jpg','.jpeg','.webp'}
                    and path.resolve().parent == root.resolve())
        except OSError: return False

    def allowed(self, job_id):
        with self.app.db() as db:
            job = db.execute('SELECT * FROM agent_jobs WHERE job_id=?',(job_id,)).fetchone()
            if not job: return True  # Legacy explicitly submitted batches.
            if not job['source_id']: return True  # Explicit file upload consent.
            source = db.execute('SELECT * FROM album_sources WHERE id=?',(job['source_id'],)).fetchone()
            return bool(source and source['enabled'] and source['generation']==job['generation'])

    def ingest(self, body, source=None):
        from server import Problem, now_iso
        with self.lock:
            if body.get('confirmed') is not True: raise Problem('请授权识别并自动整理所选截图。')
            if not self.app.public_config()['vision']: raise Problem('识别服务尚未连接，请先完成设置。')
            image = self.app.save_image(body.get('image',''))
            digest = image.split('.')[0]
            with self.app.db() as db:
                existing = db.execute('SELECT job_id FROM agent_jobs WHERE digest=?',(digest,)).fetchone()
                if existing: return {'duplicate':True,'job_id':existing['job_id']}
                legacy = db.execute("SELECT id FROM image_jobs WHERE image=? AND status!='cancelled' ORDER BY rowid DESC LIMIT 1",(image,)).fetchone()
                if legacy: return {'duplicate':True,'job_id':legacy['id']}
                count = db.execute('SELECT count(*) FROM agent_jobs WHERE substr(created_at,1,10)=?',(now_iso()[:10],)).fetchone()[0]
                if count >= self.settings()['daily_limit']: raise Problem('已达到今日识别上限，可在设置中调整。',429)
                job_id = secrets.token_hex(16)
                db.execute('INSERT INTO agent_jobs VALUES(?,?,?,?,?)',(job_id,digest,source['id'] if source else '',source['generation'] if source else 0,now_iso()))
            try:
                return self.app.enqueue_image(dict(body, request_id=job_id,batch_id=secrets.token_hex(16)))
            except Exception:
                with self.app.db() as db: db.execute('DELETE FROM agent_jobs WHERE job_id=?',(job_id,))
                raise

    def scan_once(self):
        from server import Problem, now_iso
        self.last_scan = now_iso()
        self.error = ''
        if not self.app.public_config()['vision']:
            self.error='请连接识别服务，已授权的截图文件夹会保留。'
            return
        with self.app.db() as db: sources = [dict(r) for r in db.execute('SELECT * FROM album_sources WHERE enabled=1')]
        for source in sources:
            root = Path(source['path'])
            try:
                if root.is_symlink() or root.resolve() != root or (getattr(root.lstat(),'st_file_attributes',0) & 0x400):
                    self.error='截图文件夹位置已变化，请重新选择并授权。'
                    continue
                paths = sorted(root.iterdir(), key=lambda p:p.name)
                with self.app.db() as db:
                    previous = {r['name']: r['signature'] for r in db.execute(
                        'SELECT name,signature FROM album_files WHERE source_id=?', (source['id'],))}
                for path in paths:
                    if not self.safe_file(root,path): continue
                    stat = path.stat()
                    signature = self.signature(stat)
                    key = (source['id'],path.name)
                    if previous.get(path.name)==signature: continue
                    if self.observed.get(key) != signature:
                        self.observed[key] = signature
                        continue
                    if time.time()-stat.st_mtime < 2: continue
                    with self.lock:
                        with self.app.db() as db:
                            current = db.execute('SELECT * FROM album_sources WHERE id=?',(source['id'],)).fetchone()
                        if not current or not current['enabled'] or current['generation']!=source['generation']: break
                        if not self.safe_file(root,path): continue
                        state,error = 'queued',''
                        try:
                            if not 0 < stat.st_size <= 8*1024*1024: raise Problem('图片超过 8 MB 或为空，请缩小后再试。')
                            with path.open('rb') as stream: raw=stream.read(8*1024*1024+1)
                            if self.signature(path.stat())!=signature: continue
                            kind='jpeg' if path.suffix.lower() in {'.jpg','.jpeg'} else path.suffix[1:].lower()
                            self.ingest({'confirmed':True,'filename':path.name,'image':f'data:image/{kind};base64,'+base64.b64encode(raw).decode()},source)
                        except Problem as exc:
                            if exc.status==429:
                                self.error=str(exc)
                                break
                            state,error='failed',str(exc)
                        with self.app.db() as db:
                            db.execute('INSERT OR REPLACE INTO album_files VALUES(?,?,?,?,?)',(*key,signature,state,error))
            except OSError:
                self.error='截图文件夹暂时无法读取，请检查路径或权限。'

    def finish_job(self, job_id):
        with self.app.db() as db:
            tracked = db.execute('SELECT job_id FROM agent_jobs WHERE job_id=?',(job_id,)).fetchone()
            parts = db.execute("SELECT a.id,a.draft_id,d.payload FROM image_job_actions a JOIN drafts d ON d.id=a.draft_id WHERE a.job_id=? AND a.status='ready'",(job_id,)).fetchall()
        if not tracked: return
        for part in parts:
            draft=json.loads(part['payload'])
            with self.lock:
                if not self.allowed(job_id): return
                if normalize(draft)['skill'] not in self.settings()['skills'] or review_reasons(draft): continue
                try: self.save_part(dict(part),draft)
                except Exception: continue  # Draft stays visible for review; never repeats model call.

    def save_part(self, part, fields):
        item=self.app.confirm(dict(fields,draft_id=part['draft_id'],confirmed=True))
        with self.app.db() as db:
            db.execute("UPDATE image_job_actions SET status='saved',saved_item_id=? WHERE id=?",(item['id'],part['id']))
            parent=db.execute('SELECT job_id FROM image_job_actions WHERE id=?',(part['id'],)).fetchone()
            self.app.sync_image_status(db,parent['job_id'])
        self.sync_if_authorized(item)
        return item

    def sync_if_authorized(self,item):
        value=self.settings()
        task=item['kind']=='task'
        if item['kind'] not in {'task','event'} or not value['sync_tasks' if task else 'sync_events']: return
        target=value['task_target' if task else 'calendar_target']
        current=self.app.feishu.task_target() if task else self.app.feishu.target()
        if not target or target!=current: return
        try: self.app.sync_feishu(item['id'],{'confirmed':True,'expected_target':target})
        except Exception: pass  # Stored sync_error remains visible; never automatic retry.

    def review(self,body):
        from server import Problem
        with self.lock:
            with self.app.db() as db:
                part=db.execute("SELECT a.* FROM image_job_actions a WHERE a.id=? AND a.status IN ('ready','saved')",(body.get('id',''),)).fetchone()
                if not part: raise Problem('未找到待核对事项。',404)
                original=json.loads(db.execute('SELECT payload FROM drafts WHERE id=?',(part['draft_id'],)).fetchone()[0])
            fields=body.get('fields',{})
            if not isinstance(fields,dict): raise Problem('事项内容无效。')
            return self.save_part(dict(part),dict(original,**fields))

    def status(self):
        with self.app.db() as db:
            sources=[dict(r) for r in db.execute('SELECT * FROM album_sources ORDER BY created_at DESC')]
            pending=[dict(r) for r in db.execute("SELECT id,filename,image,status,error FROM image_jobs WHERE status IN ('queued','running','failed','interrupted') ORDER BY rowid DESC LIMIT 100")]
            reviews=[]
            for r in db.execute("SELECT a.id,a.job_id,d.payload,j.filename FROM image_job_actions a JOIN drafts d ON d.id=a.draft_id JOIN image_jobs j ON j.id=a.job_id WHERE a.status='ready' ORDER BY j.rowid DESC LIMIT 300"):
                draft=json.loads(r['payload'])
                reviews.append({'id':r['id'],'job_id':r['job_id'],'filename':r['filename'],'draft':draft,'reasons':review_reasons(draft) or ['请核对后保存（此能力已暂停或自动处理授权已变化）。']})
            errors=[dict(r) for r in db.execute("SELECT name,error FROM album_files WHERE state='failed' LIMIT 30")]
        return {'native':os.name=='nt','sources':sources,'settings':self.settings(),'skills':SKILLS,'pending':pending,'reviews':reviews,
                'items':self.app.items(),'last_scan':self.last_scan,'scan_interval_seconds':SCAN_INTERVAL,'error':self.error,'file_errors':errors}

    def run(self,stop):
        while not stop.is_set():
            try: self.scan_once()
            except Exception: self.error='自动整理暂时遇到问题；已有记录保留，请重新启动应用。'
            stop.wait(SCAN_INTERVAL)
