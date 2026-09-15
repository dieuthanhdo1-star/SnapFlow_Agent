"""Startup regressions without starting real models or opening user browsers."""
import errno
import contextlib
import io
import json
import unittest
from unittest.mock import Mock,patch
from test_app import ARTIFACTS
import launcher

class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.saved=patch('launcher.saved_url',return_value='http://127.0.0.1:8765');self.saved.start();self.addCleanup(self.saved.stop)
        self.remember=patch('launcher.remember_url');self.remember.start();self.addCleanup(self.remember.stop)

    def test_probe_rejects_wrong_version(self):
        with patch('launcher.fetch',return_value=b'{"app_version":"old"}'):
            self.assertEqual(launcher.probe()[0],'other')
    def test_probe_handles_invalid_response(self):
        with patch('launcher.fetch',return_value=b'<html>proxy page</html>'):
            self.assertEqual(launcher.probe()[0],'unavailable')
    def test_probe_bypasses_proxy(self):
        response=Mock();response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=False);response.read.return_value=b'{}'
        opener=Mock();opener.open.return_value=response
        with patch('launcher.urllib.request.ProxyHandler') as handler,patch('launcher.urllib.request.build_opener',return_value=opener):
            self.assertEqual(launcher.fetch('/api/config'),b'{}');handler.assert_called_once_with({})
    def test_missing_assets_fail_before_browser(self):
        with patch('launcher.fetch',side_effect=[b'SnapFlow',b'function init(',b'body{}']):
            self.assertFalse(launcher.check_page()[0])
    def test_existing_server_browser_failure_is_visible(self):
        output=io.StringIO()
        with contextlib.redirect_stdout(output),patch('launcher.probe',return_value=('ready','')),patch('launcher.check_page',return_value=(True,'')),patch('launcher.webbrowser.open',return_value=False),patch('launcher.subprocess.Popen') as process:
            self.assertEqual(launcher.main(),0);process.assert_not_called()
        self.assertIn('http://127.0.0.1:8765',output.getvalue());self.assertIn('未自动打开',output.getvalue())
    def test_all_ports_denied_reports_error_without_child(self):
        with contextlib.redirect_stdout(io.StringIO()),patch('launcher.probe',return_value=('other','')),patch('launcher.choose_port',side_effect=OSError('denied')),patch('launcher.subprocess.Popen') as process:
            self.assertEqual(launcher.main(),1);process.assert_not_called()
    def test_child_error_preserves_log_and_reports_path(self):
        root=ARTIFACTS/'launcher-package';root.mkdir(parents=True);(root/'static').mkdir();(root/'server.py').write_text('');(root/'static/index.html').write_text('')
        child=Mock();child.poll.return_value=1;child.returncode=1;output=io.StringIO()
        with contextlib.redirect_stdout(output),patch('launcher.ROOT',root),patch('launcher.probe',return_value=('unavailable','')),patch('launcher.choose_port',return_value=18765),patch('launcher.subprocess.Popen',return_value=child) as start:
            self.assertEqual(launcher.main(),1)
        args=start.call_args;self.assertIn('-u',args.args[0]);self.assertEqual(args.kwargs['env']['PORT'],'18765')
        self.assertIn('诊断日志',output.getvalue());self.assertEqual(len(list((root.parent/'tmp/snapflow-runtime').glob('startup-*.log'))),1)
    def test_page_check_prevents_opening_broken_page(self):
        with contextlib.redirect_stdout(io.StringIO()),patch('launcher.probe',return_value=('ready','')),patch('launcher.check_page',return_value=(False,'broken')),patch('launcher.webbrowser.open') as browser:
            self.assertEqual(launcher.main(),1);browser.assert_not_called()

class PortTests(unittest.TestCase):
    def test_windows_10013_preflight_moves_to_next_port(self):
        denied=OSError('denied');denied.winerror=10013
        first,second=Mock(),Mock()
        first.bind.side_effect=denied;second.getsockname.return_value=('127.0.0.1',18765)
        for sock in [first,second]:sock.__enter__=Mock(return_value=sock);sock.__exit__=Mock(return_value=False)
        with contextlib.redirect_stdout(io.StringIO()),patch('launcher.socket.socket',side_effect=[first,second]):
            self.assertEqual(launcher.choose_port(),18765)
        first.bind.assert_called_once_with(('127.0.0.1',8765));second.bind.assert_called_once_with(('127.0.0.1',18765))
    def test_real_server_bind_falls_back_after_10013(self):
        import server
        denied=OSError('denied');denied.winerror=10013
        bound=Mock();bound.server_port=18765
        with contextlib.redirect_stdout(io.StringIO()),patch('server.ThreadingHTTPServer',side_effect=[denied,bound]) as factory:
            self.assertIs(server.bind_http_server(8765),bound)
        self.assertEqual(factory.call_args_list[1].args[0],('127.0.0.1',18765))
    def test_unrelated_bind_errors_are_not_hidden(self):
        import server
        with patch('server.ThreadingHTTPServer',side_effect=OSError(errno.EMFILE,'files exhausted')) as factory:
            with self.assertRaises(OSError):server.bind_http_server(8765)
            self.assertEqual(factory.call_count,1)
    def test_every_denied_port_is_bounded(self):
        import server
        with contextlib.redirect_stdout(io.StringIO()),patch('server.ThreadingHTTPServer',side_effect=OSError(errno.EACCES,'denied')) as factory:
            with self.assertRaises(OSError):server.bind_http_server(8765)
            self.assertEqual(factory.call_count,5)
    def test_saved_port_is_validated_and_reused(self):
        root=ARTIFACTS/'port-record';root.mkdir(parents=True,exist_ok=True)
        with patch('launcher.ROOT',root),patch('launcher.URL','http://127.0.0.1:18765'):
            launcher.remember_url();self.assertEqual(launcher.saved_url(),'http://127.0.0.1:18765')
            launcher.address_path().write_text('{"port":"18765/evil"}')
            self.assertEqual(launcher.saved_url(),'http://127.0.0.1:8765')
