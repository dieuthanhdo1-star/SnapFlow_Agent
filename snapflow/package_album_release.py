"""Allowlisted Windows album release. User data and credentials are excluded."""
from pathlib import Path
from datetime import datetime
from zipfile import ZipFile,ZIP_DEFLATED
import hashlib,json,os,shutil,time
ROOT=Path(__file__).resolve().parent
OUT=ROOT.parent/'deliverables/snapflow'
FILES=['server.py','vision_network.py','vision_settings.py','batch.py','feishu.py','skills_engine.py','agent_engine.py','native_album.py','select-folder.ps1','launcher.py',
 'providers/__init__.py','providers/vlm_client.py','providers/PROVENANCE.md','.env.example','API_BUDGET_POLICY.json',
 'start-windows.cmd','README.md','START_HERE.txt','static/index.html','static/style.css','static/app.js','static/favicon.svg',
 'tests/test_app.py','tests/test_vision_network.py','tests/test_batch.py','tests/test_gateway.py','tests/test_vision_settings.py','tests/test_folder_browser.py','tests/test_feishu.py','tests/test_album_agent.py',
 'tests/folder-browser.mjs','tests/test_ports_integration.py','tests/port-browser.mjs','tests/test_launcher.py','tests/launcher-browser.mjs','tests/album-browser.mjs','tests/album_ui_server.py','tests/batch_ui_server.py','package_album_release.py']

def secret_strings(value, sensitive=False):
    found=[]
    if isinstance(value,dict):
        for k,v in value.items():found+=secret_strings(v,any(x in k.lower() for x in ['key','token','secret','password']))
    elif isinstance(value,list):
        for v in value:found+=secret_strings(v,sensitive)
    elif sensitive and isinstance(value,str) and len(value)>12:found.append(value.encode())
    return found

if __name__=='__main__':
    verification=ROOT/'verification/network-repair-20260916'
    validation=json.loads((verification/'RELEASE_VALIDATION.json').read_text())
    assert validation['backend_tests']==116 and validation['browser_groups']==12 and validation['new_model_calls']==0
    for name,digest in validation['source_files'].items():assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==digest,name
    paths={name:ROOT/name for name in FILES}
    paths.update({str(p.relative_to(ROOT)):p for p in verification.iterdir() if p.is_file()})
    history=ROOT/'verification/album-agent-20260914'
    paths.update({str(p.relative_to(ROOT)):p for p in history.iterdir() if p.is_file()})
    secrets=[]
    for path in [ROOT/'api_key.json',ROOT.parent/'api_key.json']:
        if path.exists():secrets+=secret_strings(json.loads(path.read_text(encoding='utf-8-sig')))
    name='SnapFlow-Windows-ConfigFix-20260914-165159'
    OUT.mkdir(parents=True,exist_ok=True)
    work=ROOT.parent/'tmp/network-repair-20260916';work.mkdir(parents=True,exist_ok=True)
    package=work/(name+'-'+str(time.time_ns())+'.zip')
    manifest={'release':name,'credentials_bundled':False,'files':[]}
    with ZipFile(package,'x',ZIP_DEFLATED) as z:
        for relative,path in sorted(paths.items()):
            raw=path.read_bytes()
            assert not any(s in raw for s in secrets),'Credential detected'
            assert '/data/' not in '/'+relative and 'private.json' not in relative
            if relative.endswith(('.cmd','.txt','.ps1')):raw=raw.replace(b'\r\n',b'\n').replace(b'\n',b'\r\n')
            z.writestr(name+'/'+relative,raw)
            manifest['files'].append({'path':relative,'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()})
        z.writestr(name+'/MANIFEST.json',json.dumps(manifest,ensure_ascii=False,indent=2))
    with ZipFile(package) as z:
        assert z.testzip() is None
        for row in manifest['files']:assert hashlib.sha256(z.read(name+'/'+row['path'])).hexdigest()==row['sha256']
        assert z.read(name+'/select-folder.ps1').startswith(b'\xef\xbb\xbf')
    destination=OUT/(name+'.zip')
    protected=[ROOT.parent/'archive',ROOT/'data',ROOT.parent/'.snapflow-config']
    backup=ROOT.parent/'archive'/('release-network-repair-'+datetime.now().strftime('%Y%m%d-%H%M%S'))
    backup.mkdir(parents=True,exist_ok=False)
    entries=[]
    for old in [destination,destination.with_suffix('.sha256'),OUT/'LATEST.json']:
        if old.exists():
            target=backup/old.name;shutil.copy2(old,target)
            raw=old.read_bytes();digest=hashlib.sha256(raw).hexdigest()
            assert len(raw)==target.stat().st_size and digest==hashlib.sha256(target.read_bytes()).hexdigest()
            entries.append({'path':old.name,'bytes':len(raw),'sha256':digest})
    (backup/'RECEIPT.json').write_text(json.dumps({'status':'verified_before_update','files':len(entries),'bytes':sum(e['bytes'] for e in entries),'entries':entries,'protected':[str(p) for p in protected]},indent=2))
    os.replace(package,destination);package=destination
    receipt={'file':str(package),'bytes':package.stat().st_size,'sha256':hashlib.sha256(package.read_bytes()).hexdigest(),'files':len(paths),'validation':validation}
    package.with_suffix('.sha256').write_text(receipt['sha256']+'  '+package.name+'\n')
    package.with_suffix('.receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2))
    (OUT/'LATEST.json').write_text(json.dumps({'file':package.name,'bytes':receipt['bytes'],'sha256':receipt['sha256'],'report':str(verification.relative_to(ROOT.parent)/'REPORT.md'),'windows_target':'desktop-725gbmn','windows_native_verified':False,'revision':'windows-networkfix-20260916','repair_entry':'SnapFlow-Repair.cmd'},ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'file':str(package),'bytes':receipt['bytes'],'sha256':receipt['sha256'],'files':len(paths)},ensure_ascii=False))
