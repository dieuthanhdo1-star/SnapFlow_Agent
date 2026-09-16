"""Build one self-contained CMD from reviewed source; never include credentials."""
import base64
import hashlib
import importlib.util
import json
from pathlib import Path
import zlib

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('windows_repair',ROOT/'tools/windows_repair.py')
repair=importlib.util.module_from_spec(spec);spec.loader.exec_module(repair)

def build():
    payload={}
    for name in sorted(repair.ALLOWED):
        raw=(ROOT/'snapflow'/name).read_bytes()
        payload[name]={'data':base64.b64encode(raw).decode(),'sha256':hashlib.sha256(raw).hexdigest()}
    template=(ROOT/'tools/windows_repair.py').read_text()
    source=template.replace('PAYLOAD = {}  # Filled by build_windows_repair.py; contains no credentials.', 'PAYLOAD = '+repr(payload))
    compile(source,'windows_repair.py','exec')
    # Check both decoded runtime source and original update files against known secrets.
    secrets=[]
    def collect(value):
        if isinstance(value,dict):
            for key,val in value.items():
                if any(word in key.lower() for word in ('key','token','secret','password')) and isinstance(val,str) and len(val)>12:secrets.append(val.encode())
                else:collect(val)
        elif isinstance(value,list):
            for val in value:collect(val)
    for path in [ROOT/'api_key.json',ROOT/'snapflow/api_key.json']:
        if path.is_file():collect(json.loads(path.read_text(encoding='utf-8-sig')))
    raw_sources=[source.encode()]+[(ROOT/'snapflow'/name).read_bytes() for name in payload]
    if any(secret in raw for secret in secrets for raw in raw_sources):raise ValueError('Credential detected in repair payload')
    bootstrap="import pathlib,base64,zlib,sys;p=pathlib.Path(sys.argv[1]).read_bytes().split(b'\\r\\n::SNAPFLOW_PAYLOAD\\r\\n',1)[1];exec(zlib.decompress(base64.b64decode(p)))"
    lines=['@echo off','chcp 65001 >nul','set PYTHONIOENCODING=utf-8','set PYTHONDONTWRITEBYTECODE=1',
           'title SnapFlow - Repair','echo SnapFlow is repairing your current installation. Please wait.',
           'set "SNAPFLOW_PY=%LOCALAPPDATA%\\Programs\\Python\\Python312\\python.exe"',
           'if exist "%SNAPFLOW_PY%" (',f' "%SNAPFLOW_PY%" -u -c "{bootstrap}" "%~f0"',
           ') else (',' where py >nul 2>&1',' if errorlevel 1 (',f'  python -u -c "{bootstrap}" "%~f0"',
           ' ) else (',f'  py -3 -u -c "{bootstrap}" "%~f0"',' )',')','echo.','pause','exit /b','::SNAPFLOW_PAYLOAD']
    encoded=base64.b64encode(zlib.compress(source.encode(),9))
    body=('\r\n'.join(lines)+'\r\n').encode()+encoded+b'\r\n'
    assert zlib.decompress(base64.b64decode(body.split(b'\r\n::SNAPFLOW_PAYLOAD\r\n',1)[1]))==source.encode()
    output=ROOT/'deliverables/snapflow/SnapFlow-Repair.cmd'
    output.write_bytes(body)
    digest=hashlib.sha256(body).hexdigest()
    output.with_suffix('.sha256').write_text(digest+'  '+output.name+'\n')
    print(json.dumps({'file':str(output),'bytes':len(body),'sha256':digest,'files':len(payload),'credentials_bundled':False}))

if __name__=='__main__':build()
