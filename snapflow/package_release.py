"""Allowlisted release: source, public samples, and reviewed verification only."""
import hashlib
import json
from datetime import datetime
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile
ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT.parent / 'deliverables' / 'snapflow'
SOURCES = [
    'feishu.py', 'static/connections.js', 'tests/test_feishu.py',
    'tests/connections-browser.mjs', 'tests/web30-browser.mjs', 'tests/web30_replay_server.py',
    'server.py', 'static/index.html', 'static/style.css', 'static/app.js',
    '.env.example', '.gitignore', 'start-windows.cmd', 'start-linux.sh',
    'README.md', 'ACCEPTANCE.md', 'tests/test_app.py', 'tests/browser.mjs',
    'package_release.py', 'providers/__init__.py', 'providers/vlm_client.py',
    'providers/PROVENANCE.md', 'API_BUDGET_POLICY.json', 'tests/test_gateway.py',
    'batch.py', 'static/batch.js', 'tests/test_batch.py',
    'tests/batch-browser.mjs', 'tests/batch_ui_server.py', 'tests/chat-browser.mjs',
]

def main():
    summary = json.loads((ROOT/'verification/SUMMARY.json').read_text())
    assert summary['final_valid_responses'] == 30
    assert '\nOK\n' in (ROOT/'verification/unit-tests.log').read_text()
    for file in ['browser-test-report.json','batch-browser-report.json','chat-browser-report.json','connections-report.json','web30-report.json']:
        report = json.loads((ROOT/'verification'/file).read_text())
        assert report['passed'] and not report['errors']
    name = 'SnapFlow-Photo-Feishu-' + datetime.now().strftime('%Y%m%d-%H%M%S')
    package = OUTPUT/(name+'.zip')
    entries = {p: ROOT/p for p in SOURCES}
    for folder in ['verification','samples']:
        for path in sorted((ROOT/folder).rglob('*')):
            if path.is_file(): entries[str(path.relative_to(ROOT))] = path
    keys = []
    for config in [ROOT/'api_key.json', ROOT.parent/'api_key.json']:
        if config.exists(): keys.append(json.loads(config.read_text(encoding='utf-8-sig'))['API_KEY'].encode())
    receipt = {'package': package.name,'created_at':datetime.now().isoformat(),'validation':summary,'files':[],
               'credentials_bundled':False,'windows_delivery':'pending transport receipt'}
    with ZipFile(package,'x',compression=ZIP_DEFLATED) as archive:
        for relative,path in entries.items():
            raw = path.read_bytes()
            assert not any(key and key in raw for key in keys), 'Credential detected; abort release'
            assert '/data/' not in '/'+relative and not relative.endswith('feishu-private.json')
            if relative.endswith('.cmd'): raw=raw.replace(b'\r\n',b'\n').replace(b'\n',b'\r\n')
            archive.writestr(name+'/'+relative,raw)
            receipt['files'].append({'path':relative,'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()})
        archive.writestr(name+'/MANIFEST.json',json.dumps(receipt,ensure_ascii=False,indent=2))
    with ZipFile(package) as archive:
        assert archive.testzip() is None
        for entry in receipt['files']:
            raw=archive.read(name+'/'+entry['path'])
            assert len(raw)==entry['bytes'] and hashlib.sha256(raw).hexdigest()==entry['sha256']
    receipt.update(package_bytes=package.stat().st_size,package_sha256=hashlib.sha256(package.read_bytes()).hexdigest())
    package.with_suffix('.sha256').write_text(receipt['package_sha256']+'  '+package.name+'\n')
    package.with_suffix('.receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2))
    print(json.dumps({'path':str(package),'bytes':receipt['package_bytes'],'sha256':receipt['package_sha256'],'files':len(entries)},ensure_ascii=False))

if __name__ == '__main__': main()
