"""Offline checks against the actual loopback API; no Feishu account or model is called."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import threading
import time
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'snapflow'))
from server import App,Handler,ThreadingHTTPServer
from windows_feishu_setup import SetupClient,SetupError,import_private_config,SCOPES

OUTPUT=ROOT/'tmp/feishu-connect-20260916/tests'/str(time.time_ns())

class SetupTests(unittest.TestCase):
    def setUp(self):
        self.root=OUTPUT/self._testMethodName/'snapflow'
        self.app=App(self.root/'data',config={'VISION_BASE_URL':'https://vision.invalid/v1','VISION_API_KEY':'fake-vision','VISION_MODEL':'fake-model'})
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler);self.server.app=self.app
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.client=SetupClient(self.root,'http://127.0.0.1:'+str(self.server.server_port))
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join()
        self.app.batch_pool.shutdown(wait=True)
    def test_local_save_uses_csrf_and_preserves_vision_configuration(self):
        self.assertFalse(self.client.connect()['configured'])
        result=self.client.save('cli_fixture','local-only-secret')
        self.assertTrue(result['configured'])
        self.assertEqual(self.app.feishu.credentials(),('cli_fixture','local-only-secret'))
        self.assertEqual(self.app.config['VISION_API_KEY'],'fake-vision')
        self.assertEqual(self.client.callback,self.client.url+'/api/feishu/callback')
        self.assertNotIn('local-only-secret',json.dumps(result))
    def test_existing_private_configuration_is_verified_before_switch(self):
        self.client.connect();self.client.save('cli_old','old-fixture-secret')
        original=(self.root/'data/feishu-private.json').read_bytes()
        self.client.save('cli_new','new-fixture-secret')
        backups=list((self.root.parent/'archive').glob('feishu-connect-*'))
        self.assertEqual(len(backups),1)
        self.assertEqual((backups[0]/'feishu-private.json').read_bytes(),original)
        receipt=json.loads((backups[0]/'RECEIPT.json').read_text())
        self.assertEqual(receipt['entries'][0]['sha256'],hashlib.sha256(original).hexdigest())
    def test_external_and_malformed_urls_are_rejected(self):
        for url in ['https://example.com','http://127.0.0.1:8765@evil.invalid','http://127.0.0.1:8765/extra','http://localhost:8765','http://127.0.0.1:8765?x=1']:
            with self.assertRaises(SetupError):SetupClient(self.root,url)
    def test_failed_post_never_echoes_secret_or_auto_retries(self):
        self.client.connect()
        with patch.object(self.client.opener,'open',side_effect=OSError('private-fixture-secret')) as request:
            with self.assertRaises(SetupError) as result:self.client.save('cli_fixture','private-fixture-secret')
        self.assertNotIn('private-fixture-secret',str(result.exception));request.assert_called_once()
    def test_missing_csrf_cannot_modify_settings(self):
        with self.assertRaises(SetupError):self.client.save('cli_fixture','private-fixture-secret')
        self.assertFalse(self.app.feishu.status()['configured'])
    def test_settings_open_in_browser_without_server_side_oauth(self):
        with patch('windows_feishu_setup.webbrowser.open',return_value=True) as browser,patch.object(self.client,'request') as request:
            self.assertTrue(self.client.open_settings());request.assert_not_called()
        self.assertTrue(browser.call_args.args[0].startswith(self.client.url+'/?feishu=setup&'))
        self.assertNotIn('app_secret',browser.call_args.args[0])
    def test_paired_config_handles_renamed_copy_and_preserves_existing_login(self):
        self.client.connect();self.client.save('cli_fixture','fixture-secret')
        self.app.feishu.value.update(access_token='fake-token',refresh_token='fake-refresh',calendar_id='fake-calendar')
        self.app.feishu.save()
        folder=self.root/'incoming';folder.mkdir()
        raw=json.dumps({'app_id':'cli_fixture','app_secret':'fixture-secret'}).encode()
        (folder/'SnapFlow-feishu-private-config.json').write_text('{"app_id":"cli_old"}')
        (folder/'SnapFlow-feishu-private-config (1).json').write_bytes(raw)
        status=import_private_config(self.client,folder,hashlib.sha256(raw).hexdigest(),'cli_fixture')
        self.assertTrue(status['authorized']);self.assertEqual(status['calendar_id'],'fake-calendar')
        self.assertEqual(self.app.feishu.value['access_token'],'fake-token')
    def test_missing_or_changed_private_file_does_not_write(self):
        self.client.connect()
        folder=self.root/'incoming';folder.mkdir()
        (folder/'SnapFlow-feishu-private-config.json').write_text('{"app_secret":"private-fixture"}')
        with self.assertRaises(SetupError) as result:
            import_private_config(self.client,folder,'0'*64,'cli_fixture')
        self.assertNotIn('private-fixture',str(result.exception))
        self.assertFalse(self.app.feishu.status()['configured'])
    def test_invalid_private_credentials_are_rejected_even_with_matching_digest(self):
        self.client.connect()
        folder=self.root/'incoming';folder.mkdir()
        for value in [{'app_id':'cli_wrong','app_secret':'fake'}, {'app_id':'cli_fixture','app_secret':7}]:
            raw=json.dumps(value).encode();(folder/'SnapFlow-feishu-private-config.json').write_bytes(raw)
            with self.assertRaises(SetupError):
                import_private_config(self.client,folder,hashlib.sha256(raw).hexdigest(),'cli_fixture')
        self.assertFalse(self.app.feishu.status()['configured'])
    def test_helper_scopes_match_application_oauth(self):
        import urllib.parse
        self.client.connect();self.client.save('cli_fixture','fixture-secret')
        response,_=self.app.feishu.begin(self.client.callback)
        actual=urllib.parse.parse_qs(urllib.parse.urlsplit(response['url']).query)['scope'][0].split()
        self.assertEqual(set(actual),set(SCOPES))

if __name__=='__main__':unittest.main(verbosity=2)
