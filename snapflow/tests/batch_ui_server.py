"""Isolated browser-test server. No real keys or external model calls."""
import base64
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server import App, CST, Handler, Problem, ThreadingHTTPServer


class FixtureApp(App):
    def call_vision(self, image, body):
        assert body.get('context') == ''
        raw = (self.uploads / image).read_bytes()
        marker = raw.rsplit(b'CASE:', 1)[-1].decode('ascii', errors='replace')
        time.sleep(.25)
        if marker == 'chat':
            return {'actions': [
                {'kind': 'task', 'title': '办理设备借用', 'time_text': '11月3日14:00开放；年份未注明', 'notes': '适用于本科生。离线虚构示例。', 'questions': ['若需设置提醒，请核对年份。']},
                {'kind': 'task', 'title': '提交奖学金申请', 'time_text': '11月5日10:00开放；年份未注明', 'notes': '适用于符合条件的同学。离线虚构示例。', 'questions': ['若需设置提醒，请核对年份。']}
            ]}, {'requested_model': 'offline-test-fixture', 'upstream_verified': False}
        if marker == 'failure':
            raise Problem('离线测试：模拟一张图片识别失败。', 502)
        date = (datetime.now(CST) + timedelta(days=2)).replace(hour=18, minute=0, second=0, microsecond=0)
        kinds = {'event': 'event', 'task': 'task', 'bookmark': 'bookmark', 'missing': 'event'}
        kind = kinds.get(marker, 'bookmark')
        titles = {'event': '校园摄影分享会', 'task': '提交交互设计作业', 'bookmark': '设计灵感阅读清单', 'missing': '缺少结束时间的讲座'}
        return {'kind': kind, 'title': titles.get(marker, '测试资料'), 'questions': [],
                'start_at': date.isoformat() if kind == 'event' else '',
                'end_at': (date + timedelta(hours=1)).isoformat() if marker == 'event' else '',
                'due_at': date.isoformat() if kind == 'task' else '',
                'location': '图书馆报告厅' if kind == 'event' else '', 'notes': '预设离线测试数据，并非本轮模型识别结果。'}, {'requested_model': 'offline-test-fixture', 'upstream_verified': False}


if __name__ == '__main__':
    app = FixtureApp(Path(sys.argv[1]), config={'VISION_BASE_URL': 'https://offline.invalid', 'VISION_API_KEY': 'offline-only', 'VISION_MODEL': 'offline-test-fixture'})
    app.recover_batches()
    server = ThreadingHTTPServer(('127.0.0.1', 8767), Handler)
    server.app = app
    print('Offline batch UI test server on 8767; no external calls.', flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally:
        server.server_close()
        app.batch_pool.shutdown(wait=True)
