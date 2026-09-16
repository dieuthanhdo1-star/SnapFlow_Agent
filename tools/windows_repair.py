"""One-click repair of the known Windows install; build embeds allowlisted source only."""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import urllib.request

NAME = 'SnapFlow-Windows-ConfigFix-20260914-165159'
PROJECT = Path(r'D:\CodeProgram\AgentM')
PAYLOAD = {}  # Filled by build_windows_repair.py; contains no credentials.
ALLOWED = {'server.py','vision_network.py','vision_settings.py','providers/vlm_client.py',
           'providers/__init__.py','launcher.py','batch.py','feishu.py','skills_engine.py',
           'agent_engine.py','native_album.py','select-folder.ps1','start-windows.cmd',
           'API_BUDGET_POLICY.json','static/app.js','static/index.html','static/style.css',
           'static/favicon.svg','README.md','START_HERE.txt'}


def find_root(project):
    preferred=project/NAME/NAME
    if (preferred/'server.py').is_file(): return preferred
    candidates=[p for p in [project/NAME,project/'snapflow'] if (p/'server.py').is_file()]
    if len(candidates)==1:return candidates[0]
    raise RuntimeError('未找到你正在使用的程序目录，请保留本窗口。')


def stop_target(root):
    pattern=r'(?i)(?:^|[\s"\x27])'+re.escape(str(root/'server.py'))+r'(?=$|[\s"\x27])'
    script="$ErrorActionPreference='Stop'; $pattern='"+pattern.replace("'","''")+"'; Get-CimInstance Win32_Process -Filter \"Name='python.exe' OR Name='pythonw.exe'\" | Where-Object { $_.CommandLine -and $_.CommandLine -match $pattern } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop }"
    result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-EncodedCommand',base64.b64encode(script.encode('utf-16le')).decode()],capture_output=True,timeout=25)
    if result.returncode:raise RuntimeError('无法重启当前程序，请保留本窗口。')


def install(root, payload, stop=stop_target):
    if set(payload)!=ALLOWED:raise ValueError('修复包文件清单不匹配。')
    if root.is_symlink() or not (root/'vision_settings.py').is_file():raise ValueError('安装目录不完整。')
    updates={name:base64.b64decode(value['data'],validate=True) for name,value in payload.items()}
    for name,raw in updates.items():
        if hashlib.sha256(raw).hexdigest()!=payload[name]['sha256']:raise ValueError('修复包校验失败。')
    project=root.parent
    while project.name.startswith('SnapFlow-'):project=project.parent
    protected=[project/'archive',root/'data',project/'.snapflow-config',project/'api_key.json']
    backup=project/'archive'/('network-repair-'+time.strftime('%Y%m%d-%H%M%S')+'-'+str(os.getpid()))
    backup.mkdir(parents=True,exist_ok=False)
    setting=root/'data/network-settings.json'
    settings=json.loads(setting.read_text(encoding='utf-8')) if setting.exists() else {}
    settings['allow_existing_ssh_bridge']=True
    updates['data/network-settings.json']=json.dumps(settings).encode()
    entries=[]
    for name in updates:
        p=root/name
        if p.is_symlink() or any(parent.is_symlink() for parent in p.parents if parent!=root.parent):
            raise ValueError('安装文件路径包含链接，已停止更新。')
        row={'path':name,'existed':p.exists()}
        if p.exists():
            q=backup/name;q.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,q)
            raw=p.read_bytes();digest=hashlib.sha256(raw).hexdigest()
            if len(raw)!=q.stat().st_size or digest!=hashlib.sha256(q.read_bytes()).hexdigest():raise ValueError('备份校验失败。')
            row.update(bytes=len(raw),sha256=digest)
        entries.append(row)
    receipt={'status':'verified_before_update','files':len(entries),
             'bytes':sum(e.get('bytes',0) for e in entries),'entries':entries,'protected':[str(p) for p in protected]}
    record=backup/'RECEIPT.json';record.write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
    stop(root)
    changed=[]
    try:
        for name,raw in updates.items():
            p=root/name;p.parent.mkdir(parents=True,exist_ok=True)
            temporary=p.with_name(p.name+'.'+str(os.getpid())+'.new')
            with temporary.open('xb') as out:out.write(raw)
            os.replace(temporary,p);changed.append(name)
            if p.read_bytes()!=raw:raise ValueError('写入校验失败。')
        receipt['status']='complete'
    except Exception:
        for row in entries:
            if row['path'] not in changed:continue
            target=root/row['path']
            if row['existed']:shutil.copy2(backup/row['path'],target)
            else:target.unlink()  # Only files just created by this failed source-code update.
        receipt['status']='rolled_back'
        raise
    finally:record.write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
    return backup


def find_tailscale():
    found=shutil.which('tailscale.exe')
    if found:return found
    for var in ['ProgramFiles','ProgramFiles(x86)','LOCALAPPDATA']:
        candidate=Path(os.environ.get(var,''))/'Tailscale/tailscale.exe'
        if candidate.is_file():return str(candidate)
    script="Get-Process *tailscale* -ErrorAction SilentlyContinue | ForEach-Object { if ($_.Path) { Join-Path (Split-Path $_.Path) 'tailscale.exe' } } | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1"
    result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',script],capture_output=True,timeout=8)
    candidate=result.stdout.decode('utf-8','replace').strip()
    return candidate if candidate and Path(candidate).is_file() else None


def diagnose(root):
    # Use the launcher's verified local address, never a proxy for localhost.
    sys.path.insert(0,str(root))
    import launcher
    url=launcher.saved_url()
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    def api(path,body=None,token=None,timeout=12):
        headers={'Content-Type':'application/json'}
        if token:headers['X-Snapflow-Token']=token
        req=urllib.request.Request(url+path,data=json.dumps(body).encode() if body is not None else None,headers=headers)
        with opener.open(req,timeout=timeout) as res:return json.loads(res.read(2*1024*1024))
    config=api('/api/config')
    if config.get('app_version')!='windows-networkfix-20260916':raise RuntimeError('新版后台尚未启动，请保留本窗口。')
    print('正在自动检测连接，必要时复用已有 SSH 连接，请稍等…',flush=True)
    config=api('/api/vision/check',{},config['csrf'],timeout=75)
    report={'version':config['app_version'],'state':config['vision_state'],
            'message':config['vision_message'],'network':config['vision_network'],
            'image_retry':'not_attempted','credentials_included':False,'images_included':False}
    print(config['vision_message'],flush=True)
    if config['vision_state']=='reachable':
        state=api('/api/agent/status')
        failed=next((j for j in state['pending'] if j['status'] in ('failed','interrupted')),None)
        if failed:
            print('连接已通，正在用之前失败的一张截图验证一次，不会批量重试。',flush=True)
            batch=api('/api/image-jobs/'+failed['id'],{'action':'retry'},config['csrf'])
            report['image_retry']='submitted'
            deadline=time.monotonic()+150
            while time.monotonic()<deadline:
                state=api('/api/agent/status')
                pending=next((j for j in state['pending'] if j['id']==failed['id']),None)
                if pending is None or pending['status'] not in ('queued','running'):
                    report['image_retry']='completed' if pending is None else pending['status']
                    break
                time.sleep(2)
            else:report['image_retry']='still_running'
            config=api('/api/config')
            report.update(state=config['vision_state'],message=config['vision_message'])
    return report


def main():
    if os.name!='nt':raise RuntimeError('请在 Windows 电脑双击这个修复文件。')
    root=find_root(PROJECT)
    print('正在修复现有 SnapFlow，原有配置和截图记录会保留。',flush=True)
    backup=install(root,PAYLOAD)
    print('程序已更新，原文件已校验备份。正在打开 SnapFlow…',flush=True)
    result=subprocess.run([sys.executable,'-u',str(root/'launcher.py')],cwd=root)
    if result.returncode:raise RuntimeError('启动未完成，请保留本窗口。')
    report=diagnose(root)
    output=PROJECT/'tmp/network-repair'/('SnapFlow-Connection-Result-'+time.strftime('%Y%m%d-%H%M%S')+'.json')
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('\n'+report['message'],flush=True)
    print('诊断文件：'+str(output),flush=True)
    try:
        ts=find_tailscale()
        if ts:
            result=subprocess.run([ts,'file','cp',str(output),'100.97.47.4:'],capture_output=True,timeout=20)
            if result.returncode==0:print('已将不含密钥和图片的诊断结果传回开发机。',flush=True)
    except (OSError,subprocess.SubprocessError):pass
    if report['state']=='verified':print('识别已验证成功，请在已打开的页面查看结果。',flush=True)
    elif report['state']=='reachable':print('连接检测通过，请在页面放入一张截图继续验证。',flush=True)
    else:print('还没有跑通。诊断已保存，不用再输入命令；请告诉开发者已双击完成。',flush=True)


if __name__=='__main__':
    try:main()
    except Exception as exc:
        print(str(exc) if isinstance(exc,(ValueError,RuntimeError)) else '修复未完成：'+type(exc).__name__+'。请保留本窗口。',flush=True)
        raise SystemExit(1)
