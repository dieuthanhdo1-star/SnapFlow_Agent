"""Allowlisted Windows album release. User data and credentials are excluded."""
from pathlib import Path
from datetime import datetime
from zipfile import ZipFile,ZIP_DEFLATED
import hashlib,json
ROOT=Path(__file__).resolve().parent
OUT=ROOT.parent/'deliverables/snapflow'
FILES=['server.py','vision_settings.py','batch.py','feishu.py','skills_engine.py','agent_engine.py','native_album.py','select-folder.ps1','launcher.py',
 'providers/__init__.py','providers/vlm_client.py','providers/PROVENANCE.md','.env.example','API_BUDGET_POLICY.json',
 'start-windows.cmd','README.md','START_HERE.txt','static/index.html','static/style.css','static/app.js','static/favicon.svg',
 'tests/test_app.py','tests/test_batch.py','tests/test_gateway.py','tests/test_vision_settings.py','tests/test_folder_browser.py','tests/test_feishu.py','tests/test_album_agent.py',
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
    verification=ROOT/'verification/album-agent-20260914'
    validation=json.loads((verification/'RELEASE_VALIDATION.json').read_text())
    assert validation['backend_tests']==102 and validation['browser_groups']==12 and validation['model']['rule_checks_passed']==15
    for name,digest in validation['source_files'].items():assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==digest,name
    paths={name:ROOT/name for name in FILES}
    paths.update({str(p.relative_to(ROOT)):p for p in verification.iterdir() if p.is_file()})
    secrets=[]
    for path in [ROOT/'api_key.json',ROOT.parent/'api_key.json']:
        if path.exists():secrets+=secret_strings(json.loads(path.read_text(encoding='utf-8-sig')))
    name='SnapFlow-Windows-ConfigFix-'+datetime.now().strftime('%Y%m%d-%H%M%S')
    OUT.mkdir(parents=True,exist_ok=True);package=OUT/(name+'.zip')
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
    receipt={'file':str(package),'bytes':package.stat().st_size,'sha256':hashlib.sha256(package.read_bytes()).hexdigest(),'files':len(paths),'validation':validation}
    package.with_suffix('.sha256').write_text(receipt['sha256']+'  '+package.name+'\n')
    package.with_suffix('.receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2))
    print(json.dumps({'file':str(package),'bytes':receipt['bytes'],'sha256':receipt['sha256'],'files':len(paths)},ensure_ascii=False))
