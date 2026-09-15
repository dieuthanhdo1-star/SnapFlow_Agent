"""Small allowlisted sprint release. Never bundles user data or credentials."""
from pathlib import Path
from datetime import datetime
from zipfile import ZipFile,ZIP_DEFLATED
import hashlib,json
ROOT=Path(__file__).resolve().parent
OUT=ROOT.parent/'deliverables/snapflow'
FILES=['server.py','batch.py','feishu.py','providers/__init__.py','providers/vlm_client.py','providers/PROVENANCE.md',
 '.env.example','.gitignore','API_BUDGET_POLICY.json','start-windows.cmd','start-linux.sh','README.md','START_HERE.txt','TWO_DAY_PLAN.md',
 'static/index.html','static/style.css','static/app.js','static/batch.js','static/connections.js','static/guide.html','static/guide.js','static/guide.css',
 'tests/test_app.py','tests/test_batch.py','tests/test_gateway.py','tests/test_feishu.py','tests/sprint-browser.mjs','tests/sprint-replay.mjs',
 'tests/sprint_ui_server.py','tests/sprint_replay_server.py','tests/batch_ui_server.py','tests/capture_sprint_cases.mjs','tests/capture_public_sprint.mjs','package_sprint_release.py']
if __name__=='__main__':
 validation=json.loads((ROOT/'verification/sprint-20260914/RELEASE_VALIDATION.json').read_text())
 assert validation['backend_tests']==56 and validation['browser_groups']==11 and validation['rule_checks_passed']==15
 for p,h in validation['source_files'].items():assert hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==h
 paths={p:ROOT/p for p in FILES}
 for p in (ROOT/'verification/sprint-20260914').rglob('*'):
  if p.is_file():paths[str(p.relative_to(ROOT))]=p
 secrets=[]
 for f in [ROOT/'api_key.json',ROOT.parent/'api_key.json']:
  if f.exists():
   config=json.loads(f.read_text(encoding='utf-8-sig'))
   secrets.extend(v.encode() for k,v in config.items() if isinstance(v,str) and len(v)>12 and ('KEY' in k.upper() or 'TOKEN' in k.upper() or 'SECRET' in k.upper()))
 name='SnapFlow-TwoDay-'+datetime.now().strftime('%Y%m%d-%H%M%S');package=OUT/(name+'.zip')
 manifest={'release':name,'validation':validation,'files':[],'credentials_bundled':False}
 with ZipFile(package,'x',ZIP_DEFLATED) as z:
  for relative,path in sorted(paths.items()):
   raw=path.read_bytes()
   assert not any(secret in raw for secret in secrets),'Credential found; refusing release'
   assert '/data/' not in '/'+relative and 'feishu-private' not in relative
   if relative.endswith(('.cmd','.txt')):raw=raw.replace(b'\r\n',b'\n').replace(b'\n',b'\r\n')
   z.writestr(name+'/'+relative,raw);manifest['files'].append({'path':relative,'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()})
  z.writestr(name+'/MANIFEST.json',json.dumps(manifest,ensure_ascii=False,indent=2))
 with ZipFile(package) as z:
  assert z.testzip() is None
  for row in manifest['files']:assert hashlib.sha256(z.read(name+'/'+row['path'])).hexdigest()==row['sha256']
 receipt={'file':str(package),'bytes':package.stat().st_size,'sha256':hashlib.sha256(package.read_bytes()).hexdigest(),'files':len(paths),'validation':validation}
 package.with_suffix('.sha256').write_text(receipt['sha256']+'  '+package.name+'\n')
 package.with_suffix('.receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2))
 print(json.dumps(receipt,ensure_ascii=False))
