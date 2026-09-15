"""Isolated end-to-end fixture server. Never contacts models or Feishu."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from batch_ui_server import FixtureApp
from server import Handler, ThreadingHTTPServer
import server

class SprintApp(FixtureApp):
    def call_vision(self, image, body):
        result, metadata = super().call_vision(image, body)
        return result, metadata

def fake_remote(url, payload, token=None, **kwargs):
    if '/events?' in url:
        if '模拟失败' in payload.get('summary', ''):
            raise server.Problem('测试：网络中断，请核对飞书。', 502)
        return {'code': 0, 'data': {'event': {'event_id': 'fixture-' + url.split('idempotency_key=')[-1]}}}
    raise AssertionError('Unexpected external call in offline test')

if __name__ == '__main__':
    app = SprintApp(Path(sys.argv[1]), config={'VISION_BASE_URL': 'https://offline.invalid', 'VISION_API_KEY': 'offline-only', 'VISION_MODEL': 'offline-fixture'})
    app.feishu.configure({'app_id': 'cli_offline', 'app_secret': 'offline-secret'})
    app.feishu.accept_token({'access_token': 'offline-access', 'refresh_token': 'offline-refresh'})
    app.feishu.value.update(calendar_id='offline-calendar', calendar_name='测试日历（模拟）')
    server.remote_json = fake_remote
    http = ThreadingHTTPServer(('127.0.0.1', 8768), Handler); http.app = app
    print('Offline sprint server: 8768; no external requests', flush=True)
    try: http.serve_forever()
    finally: http.server_close(); app.batch_pool.shutdown(wait=True)
