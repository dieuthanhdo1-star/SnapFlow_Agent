"""Package verified runtime plus handoff docs; archive and verify previous delivery."""
import ast
import hashlib
import json
import os
from pathlib import Path
import shutil
import time
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / 'snapflow'
OUT = ROOT / 'deliverables/snapflow'
NAME = 'SnapFlow-Windows-ConfigFix-20260914-165159'
RUNTIME = ['server.py','vision_network.py','vision_settings.py','batch.py','feishu.py',
           'skills_engine.py','agent_engine.py','native_album.py','select-folder.ps1','launcher.py',
           'providers/__init__.py','providers/vlm_client.py','providers/PROVENANCE.md',
           '.env.example','API_BUDGET_POLICY.json','start-windows.cmd',
           'static/index.html','static/style.css','static/app.js','static/favicon.svg']

def digest(raw):
    return hashlib.sha256(raw).hexdigest()

def private_values(value):
    if isinstance(value, dict):
        for key, child in value.items():
            if any(word in key.lower() for word in ('key','token','secret','password')) and isinstance(child,str) and len(child)>12:
                yield child.encode()
            else:yield from private_values(child)
    elif isinstance(value,list):
        for child in value:yield from private_values(child)

def main():
    validation=json.loads((APP/'verification/network-repair-20260916/RELEASE_VALIDATION.json').read_text())
    files={}
    for name in RUNTIME:
        raw=(APP/name).read_bytes()
        if digest(raw)!=validation['source_files'][name]:raise ValueError('Runtime changed: '+name)
        if name.endswith('.py'):ast.parse(raw, filename=name)
        files[name]=raw
    files.update({
        'README.md':(ROOT/'docs/WINDOWS_HANDOFF.md').read_bytes(),
        '先看这里.html':(ROOT/'docs/WINDOWS_HANDOFF.html').read_bytes(),
        'FEISHU_SETUP.md':(ROOT/'docs/FEISHU_SETUP.md').read_bytes(),
        'Feishu-Permissions.json':(OUT/'Feishu-Permissions.json').read_bytes(),
        'START_HERE.txt':('SnapFlow Windows 试用版\n\n'
            '1. 右键 ZIP → 全部解压缩。先打开“先看这里.html”阅读交付说明。\n'
            '2. 新电脑需要 Python 3.10+ 及可访问的识别服务，再双击 start-windows.cmd。\n'
            '3. 已经跑通的电脑继续使用原安装目录，本交付包用于分享和留存。\n'
            '4. 截图自动整理；核对后手动点击“同步飞书”。保持两个自动同步选项关闭。\n'
            '5. 不包含真实密钥、用户截图和飞书登录状态。\n').encode('utf-8-sig')})
    known=[]
    for path in [ROOT/'api_key.json',APP/'api_key.json',APP/'data/feishu-private.json',
                 ROOT/'tmp/feishu-connect-20260916/private/SnapFlow-feishu-private-config.json']:
        if path.is_file():known.extend(private_values(json.loads(path.read_text(encoding='utf-8-sig'))))
    for name,raw in files.items():
        if any(value in raw for value in known):raise ValueError('Private credential in delivery')
        if name.endswith(('.cmd','.txt','.ps1')):files[name]=raw.replace(b'\r\n',b'\n').replace(b'\n',b'\r\n')
    assert files['select-folder.ps1'].startswith(b'\xef\xbb\xbf')
    manifest={'release':NAME,'revision':'windows-networkfix-20260916','stage':'windows-trial',
              'sync_workflow':'manual_confirmation','runtime_matches_verified_source':True,
              'credentials_bundled':False,'user_data_bundled':False,
              'user_confirmed':['new_screenshot_processed','first_manual_feishu_sync'],
              'pending':['both_task_and_event_acceptance','classification_accuracy','batch_stability','windows_restart'],
              'files':[{'path':name,'bytes':len(raw),'sha256':digest(raw)} for name,raw in sorted(files.items())]}
    work=ROOT/'tmp/windows-handoff-20260916';work.mkdir(parents=True,exist_ok=True)
    candidate=work/(NAME+'-'+str(time.time_ns())+'.zip')
    with ZipFile(candidate,'x',ZIP_DEFLATED) as archive:
        for name,raw in sorted(files.items()):archive.writestr(NAME+'/'+name,raw)
        archive.writestr(NAME+'/MANIFEST.json',json.dumps(manifest,ensure_ascii=False,indent=2))
    with ZipFile(candidate) as archive:
        assert archive.testzip() is None
        assert len(archive.namelist())==len(files)+1
        for row in manifest['files']:
            raw=archive.read(NAME+'/'+row['path'])
            assert len(raw)==row['bytes'] and digest(raw)==row['sha256']
    destination=OUT/(NAME+'.zip')
    backup=ROOT/'archive'/('windows-handoff-'+str(time.time_ns()));backup.mkdir(parents=True)
    rows=[]
    for path in [destination,destination.with_suffix('.sha256'),OUT/'LATEST.json']:
        if path.exists():
            copy=backup/path.name;shutil.copy2(path,copy);raw=path.read_bytes()
            assert copy.stat().st_size==len(raw) and digest(copy.read_bytes())==digest(raw)
            rows.append({'path':path.name,'bytes':len(raw),'sha256':digest(raw)})
    (backup/'RECEIPT.json').write_text(json.dumps({'status':'verified_before_update','files':len(rows),
        'bytes':sum(r['bytes'] for r in rows),'entries':rows,'protected':[str(ROOT/'archive')]},indent=2))
    os.replace(candidate,destination)
    sha=digest(destination.read_bytes())
    destination.with_suffix('.sha256').write_text(sha+'  '+destination.name+'\n')
    latest={'file':destination.name,'bytes':destination.stat().st_size,'sha256':sha,
            'report':'docs/WINDOWS_HANDOFF.md','windows_target':'desktop-725gbmn',
            'windows_native_verified':False,'user_confirmed':manifest['user_confirmed'],
            'revision':manifest['revision'],'stage':'windows-trial','sync_workflow':'manual_confirmation',
            'repair_entry':'SnapFlow-Repair.cmd','handoff_guide':'docs/WINDOWS_HANDOFF.html'}
    (OUT/'LATEST.json').write_text(json.dumps(latest,ensure_ascii=False,indent=2)+'\n')
    report=dict(latest,files=len(files)+1,crc_verified=True,all_file_hashes_verified=True,
                runtime_matches_verified_source=True,known_credentials_scan_passed=True)
    (work/'package-check.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps(report,ensure_ascii=False))

if __name__=='__main__':main()
