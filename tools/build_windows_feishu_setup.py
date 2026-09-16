"""Build a personalized local configuration helper without embedding App Secret."""
import argparse
import ast
import base64
import hashlib
import json
from pathlib import Path
import re
import zlib

ROOT=Path(__file__).resolve().parents[1]

def build(app_id, private_config=None):
    if not re.fullmatch(r'cli_[A-Za-z0-9]+',app_id):raise ValueError('Invalid App ID')
    source=(ROOT/'tools/windows_feishu_setup.py').read_text()
    source=source.replace("APP_ID = ''  # Filled only in the user's delivery; not a secret or login token.", 'APP_ID = '+repr(app_id))
    if private_config:
        raw=Path(private_config).read_bytes()
        value=json.loads(raw)
        if value.get('app_id')!=app_id or not isinstance(value.get('app_secret'),str) or not value['app_secret'].strip():
            raise ValueError('Private configuration does not match this app')
        source=source.replace("PRIVATE_CONFIG_SHA256 = ''  # Optional binding to a separately delivered private file.",
                              'PRIVATE_CONFIG_SHA256 = '+repr(hashlib.sha256(raw).hexdigest()))
    ast.parse(source)
    bootstrap="import pathlib,base64,zlib,sys;p=pathlib.Path(sys.argv[1]).read_bytes().split(b'\\r\\n::SNAPFLOW_PAYLOAD\\r\\n',1)[1];exec(zlib.decompress(base64.b64decode(p)))"
    lines=['@echo off','chcp 65001 >nul','set PYTHONIOENCODING=utf-8','set PYTHONDONTWRITEBYTECODE=1',
           'title SnapFlow - Feishu Setup','echo Opening local Feishu setup. Please wait.',
           'set "SNAPFLOW_PY=%LOCALAPPDATA%\\Programs\\Python\\Python312\\python.exe"',
           'if exist "%SNAPFLOW_PY%" (',f' "%SNAPFLOW_PY%" -u -c "{bootstrap}" "%~f0"',
           ') else (',' where py >nul 2>&1',' if errorlevel 1 (',f'  python -u -c "{bootstrap}" "%~f0"',
           ' ) else (',f'  py -3 -u -c "{bootstrap}" "%~f0"',' )',')',
           'if errorlevel 1 pause','exit /b','::SNAPFLOW_PAYLOAD']
    raw=('\r\n'.join(lines)+'\r\n').encode()+base64.b64encode(zlib.compress(source.encode(),9))+b'\r\n'
    assert zlib.decompress(base64.b64decode(raw.split(b'\r\n::SNAPFLOW_PAYLOAD\r\n',1)[1]))==source.encode()
    path=ROOT/'deliverables/snapflow/SnapFlow-Connect-Feishu.cmd'
    path.write_bytes(raw)
    # Personalized delivery stays out of Git; reusable source is tracked.
    receipt=ROOT/'tmp/feishu-connect-20260916/delivery.sha256'
    receipt.parent.mkdir(parents=True,exist_ok=True)
    receipt.write_text(hashlib.sha256(raw).hexdigest()+'  '+path.name+'\n')
    print(path.name+': '+str(len(raw))+' bytes; App Secret is not bundled.')

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--app-id',required=True)
    parser.add_argument('--private-config',type=Path)
    args=parser.parse_args()
    build(args.app_id,args.private_config)
