"""Browser fixture: never uses a model, account, or Windows user data."""
import sys
import time
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from server import App,Handler,ThreadingHTTPServer
from batch_ui_server import FixtureApp
if __name__=='__main__':
    root=Path(sys.argv[1]);root.mkdir(parents=True,exist_ok=True)
    app=FixtureApp(root/'data',config={'VISION_BASE_URL':'https://offline.invalid','VISION_API_KEY':'offline','VISION_MODEL':'offline-fixture'})
    folder=root/'Screenshots';folder.mkdir(exist_ok=True)
    # Only the picker is mocked; consent and source APIs are real.
    import native_album
    native_album.choose_folder=lambda:folder
    native_album.folder_roots=lambda:[folder]
    (folder/'子目录').mkdir(exist_ok=True)
    app.feishu.value.update(app_id='offline-app',app_secret='offline-secret',access_token='offline-token',expires_at=time.time()+9999,calendar_id='test-calendar',calendar_name='测试日历',task_user_id='test-user',task_user_name='测试用户')
    server=ThreadingHTTPServer(('127.0.0.1',8774),Handler);server.app=app
    print('Album UI offline server :8774',flush=True)
    server.serve_forever()
