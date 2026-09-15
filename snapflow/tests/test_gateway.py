"""Gateway integration checks with fake credentials and mocked inference only."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server import App, Problem
from test_app import ARTIFACTS, PNG


class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.root = ARTIFACTS / self._testMethodName
        self.root.mkdir(parents=True)
        self.credentials = self.root / 'gateway-fixture.json'
        self.credentials.write_text(json.dumps({'BASE_URL': 'https://fixture.invalid', 'API_KEY': 'never-expose-this-fixture-key'}))
        self.app = App(self.root / 'data', config={'VISION_GATEWAY_CONFIG': str(self.credentials)})

    def outcome(self, **updates):
        outcome = {'api_response_ok': True, 'http_status': 200, 'model': 'gemini-3.8-flash',
                   'returned_model': 'gateway-returned-alias', 'response': json.dumps({'kind': 'bookmark', 'title': '中文资料', 'questions': []}),
                   'usage': {'prompt_tokens': 123, 'completion_tokens': 42, 'total_tokens': 165}, 'seconds': 2.1, 'finish_reason': 'stop'}
        outcome.update(updates)
        return outcome

    def test_detect_gateway_without_exposing_credentials(self):
        config = self.app.public_config()
        self.assertTrue(config['vision'])
        self.assertEqual(config['vision_model'], 'gemini-3.8-flash')
        self.assertEqual(config['vision_provider'], 'gateway')
        self.assertNotIn('never-expose', json.dumps(config))
        self.assertNotIn('gateway-fixture', json.dumps(config))

    def test_model_configuration_remains_explicitly_overridable(self):
        self.app.config['VISION_GATEWAY_MODEL'] = 'claude-opus-5'
        self.assertEqual(self.app.public_config()['vision_model'], 'claude-opus-5')
        self.app.config['VISION_DISABLED'] = '1'
        with patch('server.VLMClient.understand') as call:
            with self.assertRaises(Problem): self.app.analyze({'image': PNG, 'mode': 'ai'})
            call.assert_not_called()

    def test_gateway_success_is_a_draft_then_preserves_audit_when_confirmed(self):
        with patch('server.VLMClient.understand', return_value=self.outcome()) as call:
            draft = self.app.analyze({'image': PNG, 'mode': 'ai'})
        call.assert_called_once()
        self.assertEqual(call.call_args.kwargs['model'], 'gemini-3.8-flash')
        self.assertTrue(Path(call.call_args.kwargs['images'][0]).is_file())
        self.assertEqual(self.app.items(), [])
        self.assertFalse(draft['vision_metadata']['upstream_verified'])
        self.assertEqual(draft['vision_metadata']['returned_model'], 'gateway-returned-alias')
        saved = self.app.confirm({'draft_id': draft['id'], 'confirmed': True, 'kind': 'bookmark', 'title': draft['title']})
        metadata = json.loads(saved['vision_metadata'])
        self.assertEqual(metadata['requested_model'], 'gemini-3.8-flash')
        with self.app.db() as db:
            record = dict(db.execute('SELECT * FROM vision_calls').fetchone())
        self.assertEqual(record['status'], 'success')
        self.assertIsNone(record['cost_rmb'])
        self.assertEqual(json.loads(record['usage'])['total_tokens'], 165)

    def test_timeout_default_override_and_bounds_reach_gateway(self):
        for configured, expected in [(None,120), ('180',180), ('invalid',120), ('2',10), ('900',300)]:
            if configured is None: self.app.config.pop('VISION_TIMEOUT_SECONDS', None)
            else: self.app.config['VISION_TIMEOUT_SECONDS'] = configured
            with patch('server.VLMClient') as client:
                client.return_value.understand.return_value = self.outcome()
                self.app.analyze({'image':PNG, 'mode':'ai'})
                self.assertEqual(client.call_args.kwargs['timeout'], expected)
                client.return_value.understand.assert_called_once()
            self.assertEqual(self.app.public_config()['vision_timeout_seconds'], expected)

    def test_direct_vision_uses_the_same_timeout(self):
        self.app.config.update(VISION_BASE_URL='https://offline.invalid', VISION_API_KEY='fake', VISION_MODEL='fixture', VISION_TIMEOUT_SECONDS='120')
        response = {'choices':[{'finish_reason':'stop','message':{'content':json.dumps({'kind':'task','title':'测试'})}}]}
        with patch('server.remote_json', return_value=response) as call:
            self.app.analyze({'image':PNG,'mode':'ai'})
            self.assertEqual(call.call_args.kwargs['timeout'],120)
            call.assert_called_once()

    def test_timeout_does_not_retry_or_leak_provider_error(self):
        with patch('server.VLMClient.understand', return_value=self.outcome(api_response_ok=False, http_status=None, error='never-expose-this-fixture-key')) as call:
            with self.assertRaises(Problem) as problem:
                self.app.analyze({'image': PNG, 'mode': 'ai'})
            call.assert_called_once()
        self.assertNotIn('never-expose', str(problem.exception))
        self.assertEqual(self.app.items(), [])
        with self.app.db() as db:
            record = dict(db.execute('SELECT * FROM vision_calls').fetchone())
        self.assertEqual(record['status'], 'failed')
        self.assertIsNone(record['cost_rmb'])

    def test_truncated_valid_json_is_not_accepted(self):
        with patch('server.VLMClient.understand', return_value=self.outcome(finish_reason='length')):
            with self.assertRaisesRegex(Problem, '截断'):
                self.app.analyze({'image': PNG, 'mode': 'ai'})
        self.assertEqual(self.app.items(), [])

    def test_empty_and_invalid_response_still_audited(self):
        for response in ['', '[]', 'unparseable']:
            with patch('server.VLMClient.understand', return_value=self.outcome(response=response)):
                with self.assertRaises(Problem): self.app.analyze({'image': PNG, 'mode': 'ai'})
        self.assertEqual(self.app.budget_status()['calls'], 3)
        self.assertEqual(self.app.budget_status()['unpriced_calls'], 3)
        self.assertIsNone(self.app.budget_status()['verified_spend_rmb'])
        self.assertFalse(self.app.budget_status()['automatic_expansion_active'])

    def test_bad_gateway_config_disables_ai_safely(self):
        self.credentials.write_text('{bad-json')
        app = App(self.root / 'other', config={'VISION_GATEWAY_CONFIG': str(self.credentials)})
        self.assertFalse(app.public_config()['vision'])
        self.assertIn('无法读取', app.public_config()['vision_config_error'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
