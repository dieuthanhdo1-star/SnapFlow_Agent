"""Application tests only: provider calls are stubbed; no model inference occurs."""
import base64
import http.client
import json
import os
import sys
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server import App, CST, Handler, Problem, ThreadingHTTPServer, calendar_file, parse_date

ARTIFACTS = Path(os.environ.get('SNAPFLOW_TEST_OUTPUT', Path(__file__).resolve().parents[2] / 'tmp' / 'screenshot-feishu-20260913' / 'unit')) / f'unit-{time.time_ns()}'
PNG = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aXioAAAAASUVORK5CYII='
CONFIG = {'VISION_BASE_URL': 'https://vision.invalid/v1', 'VISION_API_KEY': 'secret-test-key', 'VISION_MODEL': 'vision-fixture',
          'FEISHU_APP_ID': 'app-test', 'FEISHU_APP_SECRET': 'secret-test-app', 'FEISHU_CALENDAR_ID': 'calendar-test'}


class AppTests(unittest.TestCase):
    def setUp(self):
        self.app = App(ARTIFACTS / self._testMethodName, config={})

    def body(self, kind='event', **updates):
        draft = self.app.demo(kind)
        body = dict(draft, draft_id=draft['id'], confirmed=True)
        body.update(updates)
        return body

    def test_no_action_before_explicit_confirmation(self):
        body = self.body()
        self.assertEqual(self.app.items(), [])
        body['confirmed'] = False
        with self.assertRaises(Problem):
            self.app.confirm(body)
        self.assertEqual(self.app.items(), [])

    def test_cancelled_draft_cannot_execute(self):
        body = self.body()
        self.app.cancel(body['draft_id'])
        with self.assertRaises(Problem):
            self.app.confirm(body)
        self.assertEqual(self.app.items(), [])

    def test_concurrent_confirmation_creates_one_record(self):
        body = self.body()
        with ThreadPoolExecutor(max_workers=6) as pool:
            records = list(pool.map(lambda _: self.app.confirm(body), range(12)))
        self.assertEqual(len({r['id'] for r in records}), 1)
        self.assertEqual(len(self.app.items()), 1)

    def test_incomplete_or_reversed_event_is_rejected(self):
        for changes in [{'start_at': ''}, {'end_at': ''}, {'start_at': '2027-01-01'},
                        {'start_at': '2027-01-02T12:00:00+08:00', 'end_at': '2027-01-01T12:00:00+08:00'}]:
            with self.subTest(changes=changes), self.assertRaises(Problem):
                self.app.confirm(self.body(**changes))
        self.assertEqual(self.app.items(), [])

    def test_task_and_bookmark_do_not_invent_dates(self):
        task = self.app.confirm(self.body('task', due_at=''))
        bookmark = self.app.confirm(self.body('bookmark', start_at='2027-01-01T12:00', due_at='2027-01-01T12:00'))
        self.assertEqual(task['due_at'], '')
        self.assertEqual(bookmark['start_at'], '')
        self.assertEqual(bookmark['due_at'], '')

    def test_image_and_records_survive_restart(self):
        draft = self.app.analyze({'image': PNG, 'mode': 'manual'})
        saved = self.app.confirm(dict(draft_id=draft['id'], confirmed=True, kind='bookmark', title='我的参考'))
        restart = App(self.app.data, config={})
        self.assertEqual(restart.get_item(saved['id'])['title'], '我的参考')
        self.assertTrue((restart.uploads / saved['image']).exists())

    def test_file_type_validation_and_duplicate_upload_storage(self):
        first = self.app.save_image(PNG)
        self.assertEqual(first, self.app.save_image(PNG))
        self.assertEqual(len(list(self.app.uploads.iterdir())), 1)
        for invalid in ['data:image/svg+xml;base64,PHN2Zz4=', 'data:image/png;base64,SGVsbG8=', 'data:image/png;base64,====', PNG.replace('png', 'jpeg')]:
            with self.subTest(invalid=invalid[:30]), self.assertRaises(Problem):
                self.app.save_image(invalid)

    def test_missing_model_does_not_return_fake_recognition(self):
        with self.assertRaisesRegex(Problem, '尚未配置'):
            self.app.analyze({'image': PNG, 'mode': 'ai'})
        manual = self.app.analyze({'image': PNG, 'mode': 'manual'})
        self.assertEqual(manual['source'], 'manual')
        self.assertEqual(manual['title'], '')
        self.assertEqual(manual['kind'], 'unknown')

    def test_provider_response_becomes_draft_only(self):
        self.app.config = CONFIG
        response = {'choices': [{'message': {'content': json.dumps({'kind': 'event', 'title': '测试海报', 'start_at': '周五', 'questions': ['哪一年？']})}}]}
        with patch('server.remote_json', return_value=response) as mocked:
            draft = self.app.analyze({'image': PNG, 'mode': 'ai', 'context': '记下活动'})
        self.assertEqual(draft['source'], 'ai')
        self.assertEqual(draft['start_at'], '')
        self.assertIn('哪一年？', draft['questions'])
        self.assertEqual(self.app.items(), [])
        self.assertEqual(mocked.call_count, 1)

    def test_invalid_model_response_reports_failure(self):
        self.app.config = CONFIG
        for content in ['not JSON', '[]', 'null']:
            with self.subTest(content=content), patch('server.remote_json', return_value={'choices': [{'message': {'content': content}}]}):
                with self.assertRaises(Problem):
                    self.app.analyze({'image': PNG, 'mode': 'ai'})
        self.assertEqual(self.app.items(), [])

    def test_reminder_requires_valid_future_time(self):
        with self.assertRaises(Problem):
            self.app.confirm(self.body(reminder_at='2020-01-01T10:00'))
        with self.assertRaises(Problem):
            self.app.confirm(self.body(reminder_at=(datetime.now(CST) + timedelta(days=5)).isoformat()))

    def test_reminders_persist_deduplicate_snooze_and_stop_on_completion(self):
        reminder = datetime.now(CST) + timedelta(minutes=1)
        saved = self.app.confirm(self.body('task', reminder_at=reminder.isoformat()))
        self.app.tick(reminder + timedelta(seconds=2))
        self.app.tick(reminder + timedelta(seconds=3))
        restart = App(self.app.data, config={})
        self.assertEqual(len(restart.notifications()), 1)
        restart.update_item(saved['id'], {'action': 'snooze'})
        self.assertEqual(restart.notifications(), [])
        next_reminder = parse_date(restart.get_item(saved['id'])['reminder_at'])
        restart.tick(next_reminder + timedelta(seconds=1))
        self.assertEqual(len(restart.notifications()), 1)
        restart.update_item(saved['id'], {'action': 'complete'})
        restart.tick(next_reminder + timedelta(days=1))
        self.assertEqual(restart.notifications(), [])
        self.assertEqual(restart.get_item(saved['id'])['reminder_at'], '')
        with self.assertRaises(Problem):
            restart.update_item(saved['id'], {'action': 'snooze'})

    def test_ics_is_utc_escaped_folded_and_preserves_reminder(self):
        saved = self.app.confirm(self.body(title='摄影分享会' * 20 + '\nBEGIN:EVIL', notes='A,B;C\\D', reminder_at=(datetime.now(CST) + timedelta(minutes=2)).isoformat()))
        content = calendar_file(saved)
        self.assertIn(b'BEGIN:VALARM\r\n', content)
        self.assertIn(b'TRIGGER;VALUE=DATE-TIME:', content)
        unfolded = content.decode().replace('\r\n ', '')
        self.assertIn('\\nBEGIN:EVIL', unfolded)
        self.assertNotIn('\r\nBEGIN:EVIL', unfolded)
        self.assertIn('DESCRIPTION:A\\,B\\;C\\\\D', unfolded)
        self.assertTrue(all(len(line) <= 75 for line in content.split(b'\r\n')))
        self.assertIn('DTSTART:' + parse_date(saved['start_at']).astimezone(__import__('datetime').timezone.utc).strftime('%Y%m%dT%H%M%SZ'), unfolded)

    def test_credentials_never_in_public_configuration(self):
        self.app.config = CONFIG
        public = json.dumps(self.app.public_config())
        self.assertNotIn('secret-test', public)
        self.assertNotIn('calendar-test', public)

    def test_feishu_requires_confirmation_and_retries_with_same_key(self):
        self.app.config = CONFIG
        saved = self.app.confirm(self.body())
        with patch('server.remote_json') as mocked:
            with self.assertRaises(Problem):
                self.app.sync_feishu(saved['id'], {})
            mocked.assert_not_called()
        with patch('server.remote_json', side_effect=[{'tenant_access_token': 'token'}, Problem('timeout', 502)]) as mocked:
            with self.assertRaises(Problem):
                self.app.sync_feishu(saved['id'], {'confirmed': True})
            first_url = mocked.call_args_list[1].args[0]
        self.assertEqual(self.app.get_item(saved['id'])['sync_state'], 'uncertain')
        with patch('server.remote_json', side_effect=[{'tenant_access_token': 'token'}, {'code': 0, 'data': {'event': {'event_id': 'event-123'}}}]) as mocked:
            result = self.app.sync_feishu(saved['id'], {'confirmed': True})
            self.assertEqual(first_url, mocked.call_args_list[1].args[0])
        self.assertEqual(result['external_id'], 'event-123')
        with patch('server.remote_json') as mocked:
            self.app.sync_feishu(saved['id'], {'confirmed': True})
            mocked.assert_not_called()

    def test_interrupted_sync_can_be_recovered(self):
        item = self.app.confirm(self.body())
        with self.app.db() as db:
            db.execute("UPDATE items SET sync_state='syncing' WHERE id=?", (item['id'],))
        self.app.recover_syncs()
        self.assertEqual(self.app.get_item(item['id'])['sync_state'], 'uncertain')


class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = App(ARTIFACTS / 'http', config={})
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        cls.server.app = cls.app
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def request(self, path, payload=None, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        hdrs = {'Content-Type': 'application/json', 'X-Snapflow-Token': self.app.csrf}
        hdrs.update(headers or {})
        connection.request('GET' if payload is None else 'POST', path, body=None if payload is None else json.dumps(payload), headers=hdrs)
        response = connection.getresponse()
        data = response.read()
        status = response.status
        connection.close()
        return status, data

    def test_home_and_config(self):
        status, html = self.request('/')
        self.assertEqual(status, 200)
        self.assertIn('让截图'.encode(), html)
        status, config = self.request('/api/config')
        self.assertEqual(json.loads(config)['vision'], False)

    def test_album_assets_and_removed_guide(self):
        for path in ['/', '/app.js', '/style.css', '/favicon.svg']:
            self.assertEqual(self.request(path)[0], 200)
        self.assertEqual(self.request('/guide.html')[0], 404)
        self.assertNotIn(b'<style>', self.request('/')[1])

    def test_write_requires_csrf_and_same_origin(self):
        self.assertEqual(self.request('/api/demo', {}, {'X-Snapflow-Token': ''})[0], 403)
        self.assertEqual(self.request('/api/demo', {}, {'Origin': 'https://evil.invalid'})[0], 403)

    def test_host_and_private_files_are_protected(self):
        self.assertEqual(self.request('/api/config', headers={'Host': 'evil.invalid'})[0], 403)
        for path in ['/.env', '/data/snapflow.sqlite3', '/../server.py', '/uploads/../../server.py']:
            self.assertEqual(self.request(path)[0], 404)

    def test_complete_http_flow(self):
        status, raw = self.request('/api/demo', {'kind': 'task'})
        self.assertEqual(status, 200)
        draft = json.loads(raw)
        payload = dict(draft, draft_id=draft['id'], confirmed=True)
        status, raw = self.request('/api/confirm', payload)
        self.assertEqual(status, 200)
        saved = json.loads(raw)
        self.assertEqual(self.request(f"/api/items/{saved['id']}/update", {'action': 'complete'})[0], 200)


if __name__ == '__main__':
    unittest.main(verbosity=2)
