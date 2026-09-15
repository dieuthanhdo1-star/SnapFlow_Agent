"""Offline tests: no credentials or network access required."""
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from vlm_client import VLMClient, NoRedirect
from benchmark_vlm_advanced import equal, score


class ClientTests(unittest.TestCase):
    def client(self, base='https://gateway.example'):
        with patch.object(Path, 'read_text', return_value=json.dumps({'BASE_URL':base,'API_KEY':'dummy-secret'})):
            return VLMClient('unused')

    def test_base_url(self):
        self.assertEqual(self.client().api, 'https://gateway.example/v1')
        self.assertEqual(self.client('https://gateway.example/v1/').api, 'https://gateway.example/v1')
        for base in ['http://gateway.example','https://user:pass@gateway.example','https://gateway.example?k=a']:
            with self.assertRaises(ValueError): self.client(base)

    def test_redaction(self):
        self.assertEqual(self.client().safe('Error dummy-secret'), 'Error [REDACTED]')

    def test_no_redirect(self):
        self.assertIsNone(NoRedirect().redirect_request(None,None,302,None,None,'https://elsewhere.example'))

    def test_payload(self):
        c=self.client()
        captured=[]
        def request(path,payload):
            captured.append(payload)
            return {'http_status':200,'seconds':1,'data':{'model':payload['model'],
                    'choices':[{'message':{'content':'ok'},'finish_reason':'stop'}]}}
        c.request=request
        with patch.object(Path,'read_bytes',return_value=b'image-fixture'):
            self.assertTrue(c.understand('gemini-3.5-flash',['test.png'],'describe')['api_response_ok'])
            c.understand('gpt-5.5',['test.png'],'describe')
        self.assertEqual(captured[0]['max_tokens'],2048)
        self.assertNotIn('max_tokens',captured[1])
        self.assertEqual(captured[1]['max_completion_tokens'],2048)
        self.assertEqual(captured[0]['messages'][0]['content'][1]['type'],'image_url')

    def test_grading(self):
        self.assertFalse(equal(True,1))
        self.assertFalse(equal('false',False))
        self.assertTrue(equal(' singapore ','Singapore'))
        self.assertTrue(equal(3.42000000001,3.42))
        self.assertEqual(score('```json\n{"n":2}\n```',{'n':2})['correct'],1)
        self.assertEqual(score('not json',{'n':2})['correct'],0)

    def test_doubao_profile(self):
        c=self.client(); captured=[]
        def request(path,payload):
            captured.append(payload)
            return {'http_status':200,'seconds':1,'data':{'choices':[{'message':{'content':'ok'},'finish_reason':'stop'}]}}
        c.request=request
        c.understand('doubao-seed-2-1-pro',[],'test',disable_thinking=True)
        self.assertEqual(captured[0]['thinking'],{'type':'disabled'})
        with self.assertRaises(ValueError):
            c.understand('gemini-3.5-flash',[],'test',disable_thinking=True)


if __name__=='__main__': unittest.main()
