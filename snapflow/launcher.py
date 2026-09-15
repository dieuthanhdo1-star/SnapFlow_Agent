"""Visible Windows startup diagnostics. Probes bypass proxies; errors persist in logs."""
import errno
import hashlib
import socket
import json
import os
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT=Path(__file__).resolve().parent
URL='http://127.0.0.1:8765'
VERSION='windows-folderwatch-20260914'

def address_path():
    tag=hashlib.sha256(str(ROOT).encode()).hexdigest()[:16]
    return ROOT.parent/'tmp'/'snapflow-runtime'/('address-'+tag+'.json')

def saved_url():
    try:
        port=json.loads(address_path().read_text(encoding='utf-8')).get('port')
        if type(port) is int and 1<=port<=65535:return f'http://127.0.0.1:{port}'
    except (OSError,ValueError,AttributeError):pass
    return 'http://127.0.0.1:8765'

def remember_url():
    path=address_path();path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix(f'.{os.getpid()}.new')
    temporary.write_text(json.dumps({'port':int(URL.rsplit(':',1)[1])}),encoding='utf-8')
    os.replace(temporary,path)

def choose_port():
    for port in [8765,18765,18766,18767,0]:
        try:
            with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as listener:
                if os.name=='nt':listener.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1)
                listener.bind(('127.0.0.1',port))
                return listener.getsockname()[1]
        except OSError as exc:
            if exc.errno not in {errno.EACCES,errno.EADDRINUSE,10013,10048} and getattr(exc,'winerror',None) not in {10013,10048}:raise
            print(f'端口 {port or "自动分配"} 不可用，正在换用其他本机端口…',flush=True)
    raise OSError('Windows 未允许本机端口监听，请保留日志以便进一步检查。')

def fetch(path,timeout=2):
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(URL+path,timeout=timeout) as response:
        return response.read(2*1024*1024)

def probe():
    try:
        result=json.loads(fetch('/api/config'))
        if not isinstance(result,dict) or result.get('app_version')!=VERSION:
            return 'other','此地址上运行的不是本版 SnapFlow。'
        return 'ready',''
    except (OSError,ValueError) as exc:
        return 'unavailable',type(exc).__name__

def check_page():
    try:
        html=fetch('/').decode('utf-8')
        script=fetch('/app.js').decode('utf-8')
        css=fetch('/style.css').decode('utf-8')
        if 'SnapFlow' not in html or 'id="cards"' not in html or 'function init(' not in script or len(css)<100:
            return False,'首页文件不完整，请将整个压缩包全部解压后再启动。'
        return True,''
    except (OSError,ValueError):
        return False,'服务已响应，但首页文件读取失败，请检查解压目录是否完整。'

def show_error(message,log=None):
    print('\n启动未完成：'+message,flush=True)
    if log:print('诊断日志：'+str(log),flush=True)
    print('请把本窗口中的文字发给开发者。不要发送 api_key.json 或其他密钥文件。',flush=True)
    return 1

def main():
    global URL
    URL=saved_url()
    print('SnapFlow 正在启动，请保留此窗口…',flush=True)
    print('正在检查本机服务及可用端口…',flush=True)
    if sys.version_info<(3,10):return show_error('需要 Python 3.10 或更高版本。')
    if not (ROOT/'server.py').is_file() or not (ROOT/'static/index.html').is_file():
        return show_error('文件未完整解压。请右键 ZIP → 全部解压缩，然后运行 start-windows.cmd。')
    state,_=probe()
    if state!='ready':
        try:port=choose_port()
        except OSError:return show_error('无法找到可监听的本机端口。请保留错误信息以便检查 Windows 端口限制。')
        URL=f'http://127.0.0.1:{port}'
        print('本次页面地址：'+URL,flush=True)
        log_dir=ROOT.parent/'tmp'/'snapflow-runtime';log_dir.mkdir(parents=True,exist_ok=True)
        log=log_dir/('startup-'+time.strftime('%Y%m%d-%H%M%S')+f'-{os.getpid()}.log')
        print('后台日志：'+str(log),flush=True)
        status_path=log.with_suffix('.ready.json')
        env=dict(os.environ,SNAPFLOW_STARTUP_PORT_FILE=str(status_path),PORT=str(port),PYTHONUNBUFFERED='1',PYTHONIOENCODING='utf-8')
        kwargs={}
        if os.name=='nt':
            info=subprocess.STARTUPINFO();info.dwFlags=subprocess.STARTF_USESHOWWINDOW;info.wShowWindow=6
            kwargs={'creationflags':subprocess.CREATE_NEW_CONSOLE,'startupinfo':info}
        try:
            with log.open('ab') as out:
                child=subprocess.Popen([sys.executable,'-u',str(ROOT/'server.py')],cwd=ROOT,env=env,stdout=out,stderr=subprocess.STDOUT,**kwargs)
        except OSError as exc:return show_error('无法启动 Python 后台服务：'+type(exc).__name__,log)
        deadline=time.monotonic()+30
        while time.monotonic()<deadline:
            if child.poll() is not None:
                print('后台服务已退出，退出码：'+str(child.returncode),flush=True)
                # Full traceback remains in the local log, not automatically shared.
                return show_error('请打开上述日志查看启动错误。若提示地址占用，请关闭旧版后台。',log)
            announced=False
            try:
                status=json.loads(status_path.read_text(encoding='utf-8'))
                actual_port=status.get('port')
                if status.get('pid')==child.pid and type(actual_port) is int and 1<=actual_port<=65535:
                    URL=f'http://127.0.0.1:{actual_port}'
                    announced=True
            except (OSError,ValueError,AttributeError):pass
            if not announced:
                time.sleep(.25)
                continue
            state,_=probe()
            if state=='ready':break
            if state=='other':return show_error('所选端口刚被其他服务占用，请再次启动以重新选择端口。',log)
            time.sleep(.5)
        else:return show_error('等待服务响应超时。请打开上述日志查看详情。',log)
    valid,message=check_page()
    if not valid:return show_error(message)
    remember_url()
    print('\n服务和首页文件检查通过。',flush=True)
    print('如果浏览器显示空白，请复制以下地址到 Edge 或 Chrome 的地址栏：\n'+URL,flush=True)
    try:
        if not webbrowser.open(URL):print('默认浏览器未自动打开，请手动打开上面的地址。',flush=True)
    except Exception:print('浏览器启动失败，请手动打开上面的地址。',flush=True)
    print('关闭此启动窗口不会停止后台服务。',flush=True)
    return 0

if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception as exc:
        raise SystemExit(show_error('启动器遇到错误：'+type(exc).__name__))
