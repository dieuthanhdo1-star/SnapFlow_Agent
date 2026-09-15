"""Local Feishu OAuth connection. Credentials stay in the application's data folder."""
import base64
import hashlib
import json
import os
import secrets
import threading
import time
import urllib.parse


class FeishuConnection:
    def __init__(self, app):
        self.app = app
        self.path = app.data / 'feishu-private.json'
        self.lock = threading.RLock()
        self.pending = {}
        self.value = json.loads(self.path.read_text()) if self.path.exists() else {}

    def save(self):
        temporary = self.path.with_suffix('.new')
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w') as out:
            json.dump(self.value, out)
        os.replace(temporary, self.path)

    def credentials(self):
        return (self.value.get('app_id') or self.app.config.get('FEISHU_APP_ID', ''),
                self.value.get('app_secret') or self.app.config.get('FEISHU_APP_SECRET', ''))

    def status(self):
        app_id, secret = self.credentials()
        target = self.target()
        with self.app.db() as db:
            success = db.execute("""SELECT count(*) FROM items i JOIN feishu_targets t ON t.item_id=i.id
                WHERE i.sync_state='synced' AND t.target=?""", (target,)).fetchone()[0]
        return {'configured': bool(app_id and secret), 'app_id': app_id,
                'authorized': bool(self.value.get('refresh_token') or self.value.get('access_token')),
                'calendar_id': self.value.get('calendar_id', ''),
                'calendar_name': self.value.get('calendar_name', ''),
                'connected': bool(self.value.get('access_token') and self.value.get('calendar_id')),
                'sync_target': target, 'successful_events': success, 'task_target': self.task_target(),
                'task_connected': bool(self.task_target()), 'task_user_name': self.value.get('task_user_name','')}

    def target(self):
        if self.value.get('access_token') and self.value.get('calendar_id'):
            return 'user:' + self.credentials()[0] + ':' + self.value['calendar_id']
        if self.app.configured('FEISHU_APP_ID', 'FEISHU_APP_SECRET', 'FEISHU_CALENDAR_ID'):
            return 'tenant:' + self.app.config['FEISHU_APP_ID'] + ':' + self.app.config['FEISHU_CALENDAR_ID']
        return ''

    def configure(self, body):
        from server import Problem, text_field
        app_id = text_field(body.get('app_id'), 200).strip()
        secret = text_field(body.get('app_secret'), 500).strip()
        with self.lock:
            old_id, old_secret = self.credentials()
            if not app_id or not (secret or (app_id == old_id and old_secret)):
                raise Problem('请填写飞书应用 App ID 和 App Secret。')
            if app_id != old_id or (secret and secret != old_secret):
                self.value = {}
                self.pending.clear()
            self.value.update(app_id=app_id, app_secret=secret or old_secret)
            self.save()
        return self.status()

    def begin(self, redirect_uri):
        from server import Problem
        app_id, secret = self.credentials()
        if not (app_id and secret):
            raise Problem('请先保存飞书应用配置。')
        nonce, binding, verifier = (secrets.token_urlsafe(32) for _ in range(3))
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
        with self.lock:
            self.pending = {k: v for k, v in self.pending.items() if v['expires'] > time.time()}
            self.pending[nonce] = dict(binding=binding, verifier=verifier, redirect_uri=redirect_uri, expires=time.time()+600)
        query = urllib.parse.urlencode(dict(client_id=app_id, response_type='code', redirect_uri=redirect_uri,
            scope='offline_access calendar:calendar:read calendar:calendar.event:create task:task:write',
            state=nonce, code_challenge=challenge, code_challenge_method='S256'))
        return {'url': 'https://accounts.feishu.cn/open-apis/authen/v1/authorize?' + query}, binding

    def exchange(self, fields, binding):
        from server import Problem, remote_json
        nonce = fields.get('state', [''])[0]
        with self.lock:
            entry = self.pending.get(nonce)
            if not entry or entry['expires'] < time.time() or not secrets.compare_digest(entry['binding'], binding):
                raise Problem('飞书授权会话无效或过期，请重新连接。', 403)
            del self.pending[nonce]
            code = fields.get('code', [''])[0]
            if not code or fields.get('error'):
                raise Problem('你已取消授权，尚未连接飞书。')
            app_id, secret = self.credentials()
            data = remote_json('https://open.feishu.cn/open-apis/authen/v2/oauth/token', dict(
                grant_type='authorization_code', client_id=app_id, client_secret=secret,
                code=code, redirect_uri=entry['redirect_uri'], code_verifier=entry['verifier']))
            for key in ('calendar_id','calendar_name','task_user_id','task_user_name','refresh_token'):
                self.value.pop(key, None)
            self.accept_token(data)

    def accept_token(self, data):
        from server import Problem
        if data.get('code', 0) != 0 or not data.get('access_token'):
            raise Problem('飞书授权失败，请检查应用权限与回调地址后重新授权。', 502)
        self.value.update(access_token=data['access_token'], expires_at=time.time()+int(data.get('expires_in', 3600)),
            refresh_token=data.get('refresh_token', self.value.get('refresh_token', '')))
        self.save()

    def token(self):
        from server import Problem, remote_json
        with self.lock:
            if self.value.get('access_token') and self.value.get('expires_at', 0) > time.time()+90:
                return self.value['access_token']
            if not self.value.get('refresh_token'):
                raise Problem('请先登录飞书并授权日历。')
            app_id, secret = self.credentials()
            data = remote_json('https://open.feishu.cn/open-apis/authen/v2/oauth/token', dict(
                grant_type='refresh_token', client_id=app_id, client_secret=secret,
                refresh_token=self.value['refresh_token']))
            self.accept_token(data)
            return self.value['access_token']

    def calendars(self):
        from server import Problem, remote_json
        token = self.token()
        result, page, seen = [], '', set()
        for _ in range(20):
            url = 'https://open.feishu.cn/open-apis/calendar/v4/calendars?' + urllib.parse.urlencode(dict(page_size=100, page_token=page))
            response = remote_json(url, None, token)
            if response.get('code', 0) != 0:
                raise Problem('无法读取飞书日历，请检查 calendar:calendar:read 权限。', 502)
            data = response.get('data') or {}
            for item in data.get('calendar_list', []):
                if item.get('role') in ('owner', 'writer') and not item.get('is_deleted'):
                    result.append({'id': item['calendar_id'], 'name': item.get('summary', '我的日历')})
            page = data.get('page_token', '')
            if not data.get('has_more') or not page: break
            if page in seen: raise Problem('飞书日历分页异常，请重试。', 502)
            seen.add(page)
        return result

    def select(self, calendar_id):
        from server import Problem
        with self.lock:
            selected = next((c for c in self.calendars() if c['id'] == calendar_id), None)
            if not selected: raise Problem('请选择拥有写入权限的日历。')
            self.value.update(calendar_id=selected['id'], calendar_name=selected['name'])
            self.save()
            return self.status()

    def disconnect(self):
        with self.lock:
            self.value = {}
            self.pending.clear()
            self.save()
        return self.status()

    def task_target(self):
        if self.value.get('access_token') and self.value.get('task_user_id'):
            return 'task:' + self.credentials()[0] + ':' + self.value['task_user_id']
        return ''

    def connect_tasks(self):
        from server import Problem, remote_json
        with self.lock:
            response = remote_json('https://open.feishu.cn/open-apis/authen/v1/user_info', None, self.token())
            user = response.get('data') or {}
            if response.get('code', 0) != 0 or not user.get('open_id'):
                raise Problem('无法确认飞书任务所属账号，请重新授权。',502)
            self.value.update(task_user_id=user['open_id'], task_user_name=user.get('name','我的飞书'))
            self.save()
        return self.status()

    def sync_task(self, item_id, body):
        from server import Problem, remote_json, parse_date, text_field
        if body.get('confirmed') is not True: raise Problem('请确认同步到飞书任务。')
        with self.lock:
            target = self.task_target()
            if not target or body.get('expected_target',target) != target:
                raise Problem('飞书任务账号已变化或未连接，请重新确认。',409)
            item = self.app.get_item(item_id)
            if item['kind'] != 'task' or item['status'] != 'active': raise Problem('只能同步未完成的任务。')
            if item['sync_state'] == 'synced': return item
            with self.app.db() as db:
                db.execute('BEGIN IMMEDIATE')
                old=db.execute('SELECT target FROM feishu_targets WHERE item_id=?',(item_id,)).fetchone()
                if old and old['target'] != target: raise Problem('此任务已尝试同步到另一账号，请恢复原账号并核对。',409)
                if not db.execute("UPDATE items SET sync_state='syncing',sync_error='' WHERE id=? AND sync_state IN ('local','error','uncertain')",(item_id,)).rowcount:
                    raise Problem('任务正在同步，请稍后刷新。',409)
                db.execute('INSERT OR IGNORE INTO feishu_targets VALUES(?,?)',(item_id,target))
            try:
                payload={'summary':item['title'],'description':item['notes'],'client_token':item_id,
                         'members':[{'id':self.value['task_user_id'],'type':'user','role':'assignee'}]}
                if item['due_at']: payload['due']={'timestamp':int(parse_date(item['due_at']).timestamp()*1000),'is_all_day':False}
                response=remote_json('https://open.feishu.cn/open-apis/task/v2/tasks?user_id_type=open_id',payload,self.token())
                task=(response.get('data') or {}).get('task') or {}
                if response.get('code',0)!=0 or not task.get('guid'):
                    raise Problem('飞书未确认任务创建成功，请检查 task:task:write 权限并核对飞书。',502)
                with self.app.db() as db:
                    db.execute("UPDATE items SET sync_state='synced',external_id=?,external_url=?,sync_error='' WHERE id=?",(task['guid'],text_field(task.get('url'),2000),item_id))
            except Exception as exc:
                message=str(exc) if isinstance(exc,Problem) else '任务同步中断，请先在飞书核对。'
                with self.app.db() as db: db.execute("UPDATE items SET sync_state='uncertain',sync_error=? WHERE id=?",(message,item_id))
                raise Problem(message,502)
        return self.app.get_item(item_id)
