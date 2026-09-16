"""Local Windows setup helper. Private credentials stay out of code and logs."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import webbrowser

APP_ID = ''  # Filled only in the user's delivery; not a secret or login token.
PRIVATE_CONFIG_SHA256 = ''  # Optional binding to a separately delivered private file.
SCOPES = ['offline_access','calendar:calendar:read','calendar:calendar.event:create','task:task:write']
INSTALL_NAME = 'SnapFlow-Windows-ConfigFix-20260914-165159'
PROJECT = Path(r'D:\CodeProgram\AgentM')


class SetupError(Exception):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class SetupClient:
    def __init__(self, root, url):
        parsed=urllib.parse.urlsplit(url)
        if (parsed.scheme!='http' or parsed.hostname!='127.0.0.1' or parsed.path or
                parsed.username or parsed.password or parsed.query or parsed.fragment or not parsed.port):
            raise SetupError('本机 SnapFlow 地址无效。')
        self.root=Path(root)
        self.url=url
        self.opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
        self.csrf=''

    def request(self, path, body=None):
        if path not in {'/api/config','/api/feishu/status','/api/feishu/configure'}:
            raise SetupError('不支持的配置操作。')
        headers={'Content-Type':'application/json'}
        if body is not None:headers['X-Snapflow-Token']=self.csrf
        req=urllib.request.Request(self.url+path,data=json.dumps(body).encode() if body is not None else None,headers=headers)
        try:
            with self.opener.open(req,timeout=12) as response:
                raw=response.read(65537)
                if len(raw)>65536:raise ValueError()
                result=json.loads(raw)
                if not isinstance(result,dict):raise ValueError()
                return result
        except Exception:
            # Provider responses, tokens and user-entered secrets are never echoed.
            raise SetupError('本机配置操作未确认成功。请查看 SnapFlow 设置，暂时不要反复点击保存。') from None

    def connect(self):
        cfg=self.request('/api/config')
        if cfg.get('app_version')!='windows-networkfix-20260916' or not cfg.get('csrf'):
            raise SetupError('没有找到正在使用的 SnapFlow 版本，请先正常打开它。')
        self.csrf=cfg['csrf']
        return self.request('/api/feishu/status')

    @property
    def callback(self):
        return self.url+'/api/feishu/callback'

    def save(self, app_id, secret):
        if not app_id.startswith('cli_') or not secret.strip():
            raise SetupError('请从飞书的“凭证与基础信息”复制 App Secret。')
        old=self.root/'data/feishu-private.json'
        if old.exists():
            project=self.root.parent
            while project.name.startswith('SnapFlow-'):project=project.parent
            protected=[project/'archive',self.root/'data',project/'.snapflow-config']
            backup=project/'archive'/('feishu-connect-'+str(time.time_ns()))
            backup.mkdir(parents=True,exist_ok=False)
            target=backup/old.name
            shutil.copy2(old,target)
            raw=old.read_bytes();digest=hashlib.sha256(raw).hexdigest()
            if len(raw)!=target.stat().st_size or digest!=hashlib.sha256(target.read_bytes()).hexdigest():
                raise SetupError('旧配置备份校验失败，已停止保存。')
            receipt={'status':'verified_before_update','files':1,'bytes':len(raw),
                     'entries':[{'path':old.name,'bytes':len(raw),'sha256':digest}],
                     'protected':[str(p) for p in protected]}
            (backup/'RECEIPT.json').write_text(json.dumps(receipt,ensure_ascii=False),encoding='utf-8')
        status=self.request('/api/feishu/configure',{'app_id':app_id,'app_secret':secret.strip()})
        if not status.get('configured') or status.get('app_id')!=app_id:
            raise SetupError('应用配置尚未确认保存，请查看 SnapFlow 设置。')
        return status

    def open_settings(self):
        # Let the real page perform OAuth so its browser-binding cookie is present.
        query=urllib.parse.urlencode({'feishu':'setup','message':'应用配置已保存。请先完成飞书权限、回调和发布，再点击登录飞书并授权。'})
        return webbrowser.open(self.url+'/?'+query)


def find_root(project):
    candidates=[project/INSTALL_NAME/INSTALL_NAME,project/INSTALL_NAME,project/'snapflow']
    for root in candidates:
        if (root/'launcher.py').is_file() and (root/'feishu.py').is_file():return root
    raise SetupError('未找到当前 SnapFlow，请保留此窗口。')


def import_private_config(client, folder, expected_digest, app_id):
    """Import only the exact paired file, including Taildrop's renamed copies."""
    if not expected_digest:return None
    for path in sorted(Path(folder).glob('SnapFlow-feishu-private-config*.json')):
        try:
            with path.open('rb') as stream:raw=stream.read(8193)
            if len(raw)>8192 or hashlib.sha256(raw).hexdigest()!=expected_digest:continue
            value=json.loads(raw)
            if (not isinstance(value,dict) or value.get('app_id')!=app_id or
                    not isinstance(value.get('app_secret'),str) or not value['app_secret'].strip()):
                raise ValueError()
        except (OSError,ValueError):
            continue
        # configure() preserves existing OAuth tokens if the credentials match.
        return client.save(app_id,value['app_secret'])
    raise SetupError('未找到配套的飞书私有配置。请将收到的 JSON 文件与此 CMD 放在同一文件夹，再双击 CMD。')


def show_window(client, status):
    try:
        import tkinter as tk
        from tkinter import ttk
    except ImportError:
        raise SetupError('当前 Python 缺少窗口组件。请在 SnapFlow 的“应用提供者配置”中填入凭据。') from None
    window=tk.Tk();window.title('连接我的飞书 · SnapFlow');window.geometry('680x640');window.minsize(650,620)
    window.option_add('*Font',('Microsoft YaHei UI',10))
    frame=ttk.Frame(window,padding=24);frame.pack(fill='both',expand=True)
    ttk.Label(frame,text='连接你的飞书任务和日历',font=('Microsoft YaHei UI',15,'bold')).pack(anchor='w')
    ttk.Label(frame,text='应用凭据保存在本机，接下来连接你自己的账号。').pack(anchor='w',pady=(8,12))
    ttk.Label(frame,text='App ID：'+APP_ID).pack(anchor='w')
    credentials=ttk.Frame(frame)
    ttk.Label(credentials,text='从飞书后台“凭证与基础信息”复制 App Secret：').pack(anchor='w',pady=(14,4))
    secret=tk.StringVar();entry=ttk.Entry(credentials,textvariable=secret,show='*');entry.pack(fill='x')
    message=tk.StringVar(value='保存配置后，还需要完成飞书授权。')
    ttk.Label(frame,textvariable=message,wraplength=590).pack(anchor='w',pady=(10,10))
    later=ttk.Frame(frame)
    def show_next():
        later.pack(fill='x',pady=(15,0))
        message.set('应用配置已保存，尚未验证飞书登录或同步。')
    def save():
        value=secret.get()
        button.configure(state='disabled');message.set('正在保存到当前 SnapFlow…');window.update_idletasks()
        try:
            client.save(APP_ID,value)
            secret.set('');entry.configure(state='disabled');show_next()
        except SetupError as exc:
            secret.set('');message.set(str(exc));button.configure(state='normal')
        finally:value=''
    button=ttk.Button(credentials,text='保存到当前 SnapFlow',command=save);button.pack(anchor='w',pady=8)
    def copy_permissions():
        window.clipboard_clear()
        window.clipboard_append(json.dumps({'scopes':{'tenant':[],'user':SCOPES}},indent=2))
        window.update();message.set('权限已复制。请在飞书后台“权限管理 → 批量导入/导出权限”中粘贴导入。')
    ttk.Label(later,text='1. 权限管理：批量导入下面的四项权限；已经配置的可跳过。',wraplength=610).pack(anchor='w')
    row=ttk.Frame(later);row.pack(fill='x',pady=8)
    ttk.Button(row,text='复制所需权限',command=copy_permissions).pack(side='left',padx=(0,8))
    ttk.Button(row,text='打开飞书后台',command=lambda:webbrowser.open('https://open.feishu.cn/app/'+APP_ID)).pack(side='left')
    ttk.Label(later,text='2. 安全设置：添加下面的重定向 URL。',wraplength=610).pack(anchor='w',pady=(12,0))
    callback=tk.StringVar(value=client.callback)
    ttk.Entry(later,textvariable=callback,state='readonly').pack(fill='x',pady=8)
    def copy_callback():
        window.clipboard_clear();window.clipboard_append(client.callback);window.update()
        message.set('回调地址已复制。请粘贴到飞书后台“安全设置 → 重定向 URL”，保存并发布。')
    row=ttk.Frame(later);row.pack(fill='x')
    ttk.Button(row,text='复制回调地址',command=copy_callback).pack(side='left',padx=(0,8))
    ttk.Label(later,text='3. 版本管理与发布：创建版本，把自己加入可用范围并发布。随后在 SnapFlow 点击“登录飞书并授权”。',wraplength=610).pack(anchor='w',pady=(16,8))
    ttk.Button(later,text='打开 SnapFlow 设置',command=client.open_settings).pack(anchor='w')
    if status.get('configured') and status.get('app_id')==APP_ID:
        button.configure(state='disabled');entry.configure(state='disabled');show_next()
        message.set('应用凭据已保存，无需再填密钥。本人授权'+('已记录，请在设置中检查任务和日历目标。' if status.get('authorized') else '尚未完成；请完成下面三步。'))
    else:
        credentials.pack(fill='x')
        if status.get('configured'):message.set('当前已配置另一个飞书应用；保存将先备份原配置。')
        entry.focus_set()
    window.mainloop()


def main():
    if os.name!='nt' or not APP_ID.startswith('cli_'):
        raise SetupError('请在 Windows 电脑双击收到的飞书配置文件。')
    root=find_root(PROJECT)
    sys.path.insert(0,str(root))
    import launcher
    client=SetupClient(root,launcher.saved_url())
    try:status=client.connect()
    except SetupError:
        result=subprocess.run([sys.executable,'-u',str(root/'launcher.py')],cwd=root)
        if result.returncode:raise SetupError('请先正常打开 SnapFlow，再双击此配置文件。')
        client=SetupClient(root,launcher.saved_url());status=client.connect()
    if PRIVATE_CONFIG_SHA256:
        status=import_private_config(client,Path(sys.argv[1]).resolve().parent,PRIVATE_CONFIG_SHA256,APP_ID)
    show_window(client,status)


if __name__=='__main__':
    try:main()
    except Exception as exc:
        print(str(exc) if isinstance(exc,SetupError) else '配置未完成，请保留窗口。错误类型：'+type(exc).__name__,flush=True)
        raise SystemExit(1)
