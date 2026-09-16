"""Offline routing, TLS invariants, failure status and non-retry checks."""
import io
import json
import ssl
import urllib.error
import urllib.request
import unittest
from unittest.mock import MagicMock, patch
from test_app import ARTIFACTS, CONFIG, PNG
from server import App, Problem
from vision_network import VisionNetwork, NetworkUnavailable, TunnelHTTPSConnection, NoRedirect, error_code


class NetworkTests(unittest.TestCase):
    def test_direct_fallback_and_only_one_post_even_on_timeout(self):
        net = VisionNetwork('https://example.invalid/v1')
        default, direct = MagicMock(), MagicMock()
        default.open.side_effect = urllib.error.URLError(ssl.SSLEOFError())
        denied = urllib.error.HTTPError(net.base+'/models',401,'Unauthorized',{},io.BytesIO())
        direct.open.side_effect = [denied, urllib.error.URLError(TimeoutError())]
        with patch('vision_network.urllib.request.build_opener', side_effect=[default,direct]):
            with self.assertRaises(urllib.error.URLError):
                net.open(urllib.request.Request(net.base+'/chat/completions',b'{"image":"fixture"}'))
        self.assertEqual(net.route,'direct')
        self.assertEqual(direct.open.call_count,2)
        self.assertEqual(default.open.call_count,1)
        self.assertIsNone(net.opener)
        self.assertEqual(net.attempts,[{'route':'default','result':'tls'},{'route':'direct','result':'http_401'}])

    def test_bridge_only_for_exact_gateway_and_explicit_enable(self):
        self.assertFalse(VisionNetwork('https://example.invalid/v1',True).allow_bridge)
        self.assertFalse(VisionNetwork('https://llm-gateway.galbot.com:444/v1',True).allow_bridge)
        self.assertFalse(VisionNetwork('https://llm-gateway.galbot.com/v1').allow_bridge)
        net=VisionNetwork('https://llm-gateway.galbot.com/v1',True)
        bridge=MagicMock()
        with patch.object(net,'_probe',side_effect=[False,False,True]),patch.object(net,'_start_bridge',return_value=bridge):
            net.ensure()
        self.assertEqual(net.route,'bridge')
        self.assertIs(net.opener,bridge)

    def test_failed_preflight_sends_no_image_and_cools_down(self):
        net=VisionNetwork('https://example.invalid/v1')
        with patch.object(net,'_probe',return_value=False) as probe,patch.object(net,'_start_bridge') as bridge:
            for _ in range(2):
                with self.assertRaises(NetworkUnavailable):
                    net.open(urllib.request.Request(net.base+'/chat/completions',b'private-image'))
            self.assertEqual(probe.call_count,2)
            bridge.assert_not_called()

    def test_bound_origin_and_https_no_redirects(self):
        net=VisionNetwork('https://example.invalid/v1')
        with patch.object(net,'ensure') as ensure:
            for url in ['http://example.invalid/v1','https://other.invalid/v1','https://example.invalid:444/v1']:
                with self.assertRaises(NetworkUnavailable):net.open(url)
            ensure.assert_not_called()
        self.assertIsNone(NoRedirect().redirect_request(None,None,302,'',{},'https://other.invalid'))
        for url in ['http://example.invalid','https://key@example.invalid','https://example.invalid/?key=x']:
            with self.assertRaises(ValueError):VisionNetwork(url)

    def test_tunnel_preserves_original_tls_identity_and_verification(self):
        conn=TunnelHTTPSConnection('example.invalid',tunnel_port=23456,expected_host='example.invalid',timeout=4)
        self.assertTrue(conn._context.check_hostname)
        self.assertEqual(conn._context.verify_mode,ssl.CERT_REQUIRED)
        raw=MagicMock();context=MagicMock();conn._context=context
        with patch('vision_network.socket.create_connection',return_value=raw) as connect:
            conn.connect()
        connect.assert_called_once_with(('127.0.0.1',23456),4)
        context.wrap_socket.assert_called_once_with(raw,server_hostname='example.invalid')
        with self.assertRaises(NetworkUnavailable):
            TunnelHTTPSConnection('other.invalid',tunnel_port=23456,expected_host='example.invalid')
        context.wrap_socket.side_effect=ssl.SSLCertVerificationError()
        with patch('vision_network.socket.create_connection',return_value=raw):
            with self.assertRaises(ssl.SSLCertVerificationError):conn.connect()
        raw.close.assert_called_once()

    def test_error_classification_contains_no_credentials(self):
        for exc,code in [(ssl.SSLEOFError('secret'),'tls'),(ssl.SSLCertVerificationError('secret'),'certificate'),(TimeoutError('secret'),'timeout')]:
            self.assertEqual(error_code(urllib.error.URLError(exc)),code)

    def test_http_401_is_not_a_reason_to_reroute(self):
        net=VisionNetwork('https://example.invalid/v1');opener=MagicMock()
        opener.open.side_effect=urllib.error.HTTPError(net.base+'/models',401,'',{},io.BytesIO())
        with patch('vision_network.urllib.request.build_opener',return_value=opener) as build:
            net.ensure()
        self.assertEqual(net.route,'default');build.assert_called_once()


class ConnectionStatusTests(unittest.TestCase):
    def setUp(self):
        self.app=App(ARTIFACTS/self._testMethodName,config=CONFIG)
    def tearDown(self):
        self.app.batch_pool.shutdown(wait=True)
        if self.app.vision_network:self.app.vision_network.close()
    def test_configuration_is_not_success(self):
        self.assertEqual(self.app.public_config()['vision_state'],'configured')
        self.assertNotIn(CONFIG['VISION_API_KEY'],json.dumps(self.app.public_config()))
    def test_connection_probe_does_not_claim_inference_success(self):
        with patch('vision_network.VisionNetwork.ensure'),patch('server.remote_json',return_value={'data':[]}) as request:
            result=self.app.check_vision()
        self.assertEqual(result['vision_state'],'reachable')
        self.assertEqual(request.call_args.args[1],None)
        self.assertTrue(request.call_args.args[0].endswith('/models'))
        self.assertEqual(self.app.budget_status()['calls'],0)
    def test_failed_detection_records_safe_status(self):
        with patch('vision_network.VisionNetwork.ensure',side_effect=NetworkUnavailable('连接未完成')):
            result=self.app.check_vision()
        self.assertEqual(result['vision_state'],'failed')
        self.assertEqual(result['vision_message'],'连接未完成')
    def test_successful_image_and_later_failure_are_distinct(self):
        good={'choices':[{'message':{'content':json.dumps({'kind':'bookmark','title':'测试资料','questions':[]})},'finish_reason':'stop'}]}
        with patch('server.remote_json',return_value=good):self.app.analyze({'image':PNG,'mode':'ai'})
        self.assertEqual(self.app.public_config()['vision_state'],'verified')
        with patch('server.remote_json',side_effect=Problem('连接超时',502)):
            with self.assertRaises(Problem):self.app.analyze({'image':PNG,'mode':'ai'})
        self.assertEqual(self.app.public_config()['vision_state'],'failed')
