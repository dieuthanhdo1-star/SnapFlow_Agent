"""Directory browsing is metadata only; image access still requires explicit consent."""
import json
import http.client
import threading
from pathlib import Path
import unittest
from unittest.mock import patch
from test_app import ARTIFACTS
from server import App, Handler, Problem, ThreadingHTTPServer
from native_album import browse_folders


class FolderBrowserTests(unittest.TestCase):
    def setUp(self):
        self.root=ARTIFACTS/self._testMethodName;self.root.mkdir(parents=True)
        self.roots=patch('native_album.folder_roots',return_value=[self.root]);self.roots.start();self.addCleanup(self.roots.stop)

    def test_roots_directories_parent_and_no_file_contents(self):
        folder=self.root/'截图';folder.mkdir();(folder/'子文件夹').mkdir()
        (folder/'secret.json').write_text('not for browsing')
        (folder/'photo.png').write_bytes(b'not read')
        self.assertEqual(browse_folders({})['folders'][0]['path'],str(self.root))
        with patch.object(Path,'read_bytes',side_effect=AssertionError('no content reads')),patch.object(Path,'read_text',side_effect=AssertionError('no content reads')):
            result=browse_folders({'path':str(folder)})
        self.assertEqual([f['name'] for f in result['folders']],['子文件夹'])
        self.assertEqual(result['parent'],str(self.root))
        self.assertIsNone(browse_folders({'path':str(self.root)})['parent'])

    def test_invalid_missing_file_and_outside_root_rejected(self):
        (self.root/'file.txt').touch()
        for path in ['relative',str(self.root/'missing'),str(self.root/'file.txt'),str(self.root.parent),4,'\x00']:
            with self.assertRaises(Problem):browse_folders({'path':path})

    def test_linked_directories_are_not_listed(self):
        actual=self.root/'actual';actual.mkdir()
        (self.root/'linked').symlink_to(actual,target_is_directory=True)
        self.assertEqual([f['name'] for f in browse_folders({'path':str(self.root)})['folders']],['actual'])

    def test_large_directory_is_bounded(self):
        for i in range(502):(self.root/str(i)).mkdir()
        result=browse_folders({'path':str(self.root)})
        self.assertEqual(len(result['folders']),500);self.assertTrue(result['truncated'])

    def test_http_requires_csrf_and_browsing_does_not_authorize(self):
        app=App(self.root/'data',config={});server=ThreadingHTTPServer(('127.0.0.1',0),Handler);server.app=app
        worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
        try:
            for token,status in [('',403),(app.csrf,200)]:
                c=http.client.HTTPConnection('127.0.0.1',server.server_port)
                c.request('POST','/api/agent/folders',json.dumps({'path':str(self.root)}),{'Content-Type':'application/json','X-Snapflow-Token':token})
                result=c.getresponse();self.assertEqual(result.status,status);result.read();c.close()
            self.assertEqual(app.agent.status()['sources'],[])
            with app.db() as db:self.assertEqual(db.execute('SELECT count(*) FROM agent_jobs').fetchone()[0],0)
        finally:server.shutdown();server.server_close();worker.join();app.batch_pool.shutdown(wait=True)
