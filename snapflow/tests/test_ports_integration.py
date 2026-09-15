"""Real loopback bind collision and launcher handoff, isolated data, models disabled."""
import contextlib
import io
import os
import shutil
import socket
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch
from test_app import ARTIFACTS
import launcher

class PortIntegrationTests(unittest.TestCase):
    def test_occupied_preflight_port_falls_back_and_browser_uses_actual_port(self):
        package=ARTIFACTS/'port-integration/package';package.mkdir(parents=True)
        source=Path(__file__).resolve().parents[1]
        for name in ['server.py','vision_settings.py','batch.py','agent_engine.py','skills_engine.py','native_album.py','feishu.py','static/index.html','static/app.js','static/style.css','providers/__init__.py','providers/vlm_client.py']:
            dst=package/name;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source/name,dst)
        children=[];real_popen=subprocess.Popen;real_probe=launcher.probe;count=0
        def spawn(*args,**kwargs):
            child=real_popen(*args,**kwargs);children.append(child);return child
        def probe():
            nonlocal count
            count+=1
            return ('unavailable','') if count==1 else real_probe()
        with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as occupied:
            occupied.bind(('127.0.0.1',0));occupied.listen();port=occupied.getsockname()[1]
            try:
                with contextlib.redirect_stdout(io.StringIO()),patch('launcher.ROOT',package),patch('launcher.saved_url',return_value='http://127.0.0.1:8765'),patch('launcher.choose_port',return_value=port),patch('launcher.probe',side_effect=probe),patch('launcher.subprocess.Popen',side_effect=spawn),patch('launcher.webbrowser.open',return_value=True) as browser,patch.dict(os.environ,{'VISION_DISABLED':'1','VISION_GATEWAY_CONFIG':'','SNAPFLOW_DATA_DIR':str(package/'data')}):
                    self.assertEqual(launcher.main(),0)
                    url=browser.call_args.args[0];self.assertNotEqual(url,f'http://127.0.0.1:{port}')
                    self.assertEqual(launcher.saved_url(), 'http://127.0.0.1:8765') # Patched bootstrap only.
                    self.assertIn('port',launcher.address_path().read_text())
                    self.assertEqual(launcher.probe()[0],'ready')
            finally:
                for child in children:
                    child.terminate()
                    try:child.wait(timeout=5)
                    except subprocess.TimeoutExpired:child.kill();child.wait(timeout=5)
