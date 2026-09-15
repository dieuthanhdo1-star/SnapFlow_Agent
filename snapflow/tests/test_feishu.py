"""Feishu contract checks with fake responses; no account is accessed."""
import json
import time
import unittest
import urllib.parse
from unittest.mock import patch
from test_app import App, ARTIFACTS, Problem

class FeishuTests(unittest.TestCase):
    def setUp(self):
        self.app = App(ARTIFACTS / self._testMethodName, config={})
        self.f = self.app.feishu
        self.f.configure({'app_id': 'cli_test', 'app_secret': 'private-secret'})

    def tearDown(self):
        self.app.batch_pool.shutdown(wait=True)

    def authorized(self):
        self.f.accept_token({'access_token': 'fake-access', 'refresh_token': 'fake-refresh', 'expires_in': 3600})

    def test_secrets_not_in_status_and_persist(self):
        self.authorized()
        self.assertNotIn('private-secret', json.dumps(self.f.status()))
        self.assertNotIn('fake-access', json.dumps(self.app.public_config()))
        self.assertEqual(self.f.path.stat().st_mode & 0o777, 0o600)
        restored = App(self.app.data, config={})
        self.assertTrue(restored.feishu.status()['authorized'])
        restored.batch_pool.shutdown(wait=True)

    def test_oauth_state_browser_binding_pkce_and_replay(self):
        result, cookie = self.f.begin('http://127.0.0.1:8765/api/feishu/callback')
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(result['url']).query)
        self.assertEqual(query['code_challenge_method'], ['S256'])
        fields = {'state': query['state'], 'code': ['sample-code']}
        with self.assertRaises(Problem): self.f.exchange(fields, 'wrong-browser')
        with patch('server.remote_json', return_value={'access_token': 'fake-access', 'refresh_token': 'fake-refresh'}) as remote:
            self.f.exchange(fields, cookie)
            self.assertTrue(remote.call_args.args[1]['code_verifier'])
        with self.assertRaises(Problem): self.f.exchange(fields, cookie)

    def test_expired_cancelled_and_changed_app_authorization(self):
        result, cookie = self.f.begin('http://localhost:8765/api/feishu/callback')
        state = urllib.parse.parse_qs(urllib.parse.urlsplit(result['url']).query)['state']
        self.f.pending[state[0]]['expires'] = 0
        with self.assertRaises(Problem): self.f.exchange({'state': state, 'code': ['x']}, cookie)
        self.authorized()
        self.f.configure({'app_id': 'new-app', 'app_secret': 'new-secret'})
        self.assertFalse(self.f.status()['authorized'])
        self.assertFalse(self.f.pending)

    def test_refresh_rotation(self):
        self.authorized(); self.f.value['expires_at'] = 0
        with patch('server.remote_json', return_value={'access_token': 'rotated', 'refresh_token': 'rotated-refresh'}) as remote:
            self.assertEqual(self.f.token(), 'rotated')
            self.assertEqual(remote.call_args.args[1]['grant_type'], 'refresh_token')
        self.assertEqual(self.f.value['refresh_token'], 'rotated-refresh')

    def test_bulk_preview_target_guard_and_verified_count(self):
        self.authorized()
        self.f.value.update(calendar_id='calendar-one', calendar_name='个人日历')
        item = self.app.demo('event')
        item = self.app.confirm(dict(item, draft_id=item['id'], confirmed=True))
        target = self.f.status()['sync_target']
        self.assertEqual(self.f.status()['successful_events'], 0)
        with patch('server.remote_json') as remote:
            with self.assertRaises(Problem):
                self.app.sync_feishu(item['id'], {'confirmed': True, 'expected_target': 'user:old:calendar'})
            remote.assert_not_called()
        with patch('server.remote_json', return_value={'code': 0, 'data': {'event': {'event_id': 'live-contract-id'}}}) as remote:
            first = self.app.sync_feishu(item['id'], {'confirmed': True, 'expected_target': target})
            second = self.app.sync_feishu(item['id'], {'confirmed': True, 'expected_target': target})
            self.assertEqual(first['external_id'], second['external_id'])
            self.assertEqual(remote.call_count, 1)
        self.assertEqual(self.f.status()['successful_events'], 1)
        self.f.value['calendar_id'] = 'calendar-two'
        self.assertEqual(self.f.status()['successful_events'], 0)

    def test_calendar_pagination_permissions_selection(self):
        self.authorized()
        pages = [{'code': 0, 'data': {'calendar_list': [{'calendar_id': 'read', 'role': 'reader'}, {'calendar_id': 'write', 'role': 'writer', 'summary': '<我的日历>'}], 'has_more': True, 'page_token': 'next'}},
                 {'code': 0, 'data': {'calendar_list': [{'calendar_id': 'own', 'role': 'owner', 'summary': '我'}]}}]
        with patch('server.remote_json', side_effect=pages) as remote:
            rows = self.f.calendars()
            self.assertEqual([c['id'] for c in rows], ['write', 'own'])
            self.assertIsNone(remote.call_args.args[1])
        with patch.object(self.f, 'calendars', return_value=rows):
            with self.assertRaises(Problem): self.f.select('read')
            self.assertTrue(self.f.select('write')['connected'])

    def test_user_sync_explicit_idempotency_and_target_binding(self):
        self.authorized(); self.f.value.update(calendar_id='calendar1', calendar_name='我的日历')
        draft = self.app.demo('event')
        item = self.app.confirm(dict(draft, draft_id=draft['id'], confirmed=True))
        with patch('server.remote_json', return_value={'code': 0, 'data': {'event': {'event_id': 'e1'}}}) as remote:
            with self.assertRaises(Problem): self.app.sync_feishu(item['id'], {})
            synced = self.app.sync_feishu(item['id'], {'confirmed': True})
            self.assertEqual(synced['external_id'], 'e1')
            self.assertEqual(remote.call_args.args[2], 'fake-access')
            self.app.sync_feishu(item['id'], {'confirmed': True})
            self.assertEqual(remote.call_count, 1)
        with self.app.db() as db: db.execute("UPDATE items SET sync_state='uncertain' WHERE id=?", (item['id'],))
        self.f.value['calendar_id'] = 'calendar2'
        with patch('server.remote_json') as remote:
            with self.assertRaises(Problem): self.app.sync_feishu(item['id'], {'confirmed': True})
            remote.assert_not_called()

    def test_disconnect_clears_tokens(self):
        self.authorized(); self.f.disconnect()
        self.assertEqual(json.loads(self.f.path.read_text()), {})
        self.assertFalse(self.f.status()['connected'])
        with self.assertRaises(Problem): self.f.token()

class FeishuHTTPTests(unittest.TestCase):
    def test_browser_cookie_callback_and_csrf(self):
        import http.client
        import threading
        from server import Handler, ThreadingHTTPServer
        app = App(ARTIFACTS/'oauth-http', config={})
        app.feishu.configure({'app_id':'cli_test','app_secret':'http-secret'})
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler); server.app=app
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        def request(method,path,body=None,headers=None):
            connection=http.client.HTTPConnection('127.0.0.1',server.server_port)
            connection.request(method,path,json.dumps(body) if body is not None else None,headers or {})
            response=connection.getresponse(); data=response.read(); result=(response.status,dict(response.getheaders()),data)
            connection.close();return result
        try:
            status,_,_=request('POST','/api/feishu/connect',{}, {'Content-Type':'application/json'})
            self.assertEqual(status,403)
            status,headers,data=request('POST','/api/feishu/connect',{}, {'Content-Type':'application/json','X-Snapflow-Token':app.csrf})
            self.assertEqual(status,200);self.assertIn('HttpOnly',headers['Set-Cookie'])
            query=urllib.parse.parse_qs(urllib.parse.urlsplit(json.loads(data)['url']).query)
            callback='/api/feishu/callback?'+urllib.parse.urlencode({'state':query['state'][0],'code':'private-code'})
            status,headers2,_=request('GET',callback)
            self.assertEqual(status,302);self.assertIn('feishu=error',headers2['Location'])
            with patch('server.remote_json',return_value={'access_token':'a','refresh_token':'r'}):
                status,headers2,_=request('GET',callback,headers={'Cookie':headers['Set-Cookie'].split(';')[0]})
            self.assertEqual(headers2['Location'],'/?feishu=connected')
            self.assertTrue(app.feishu.status()['authorized'])
        finally:
            server.shutdown();server.server_close();thread.join();app.batch_pool.shutdown(wait=True)
