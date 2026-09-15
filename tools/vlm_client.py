#!/usr/bin/env python3
"""Credential-safe, standard-library VLM client for this configured gateway."""
import argparse
import base64
import json
import mimetypes
from pathlib import Path
import time
import urllib.error
import urllib.parse
import urllib.request


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class VLMClient:
    def __init__(self, config, timeout=55):
        cfg = json.loads(Path(config).read_text(encoding='utf-8-sig'))
        self.key = cfg['API_KEY']
        self.base = cfg['BASE_URL'].rstrip('/')
        u = urllib.parse.urlsplit(self.base)
        if not self.key or u.scheme != 'https' or not u.netloc or u.username or u.password or u.query or u.fragment:
            raise ValueError('A nonempty API_KEY and plain HTTPS BASE_URL are required')
        self.api = self.base if u.path.endswith('/v1') else self.base + '/v1'
        self.timeout = timeout

    def safe(self, value):
        return str(value).replace(self.key, '[REDACTED]')

    def request(self, path, payload=None):
        start = time.monotonic()
        req = urllib.request.Request(self.api + path,
            headers={'Authorization': 'Bearer ' + self.key, 'Content-Type': 'application/json'},
            data=json.dumps(payload).encode() if payload is not None else None)
        try:
            with urllib.request.build_opener(NoRedirect).open(req, timeout=self.timeout) as r:
                body = r.read(4_000_001)
                if len(body) > 4_000_000:
                    raise ValueError('Response exceeded safety size limit')
                result = {'http_status': r.status, 'data': json.loads(body)}
        except urllib.error.HTTPError as e:
            result = {'http_status': e.code, 'error': self.safe(e.read(5000).decode('utf-8', 'replace'))}
        except Exception as e:
            result = {'http_status': None, 'error': self.safe(type(e).__name__ + ': ' + str(e))}
        result['seconds'] = round(time.monotonic() - start, 3)
        return result

    def understand(self, model, images, prompt, max_tokens=2048, disable_thinking=False):
        content = [{'type': 'text', 'text': prompt}]
        for filename in images:
            path = Path(filename)
            mime = mimetypes.guess_type(path.name)[0]
            if mime not in ('image/png', 'image/jpeg', 'image/webp'):
                raise ValueError('Use PNG, JPEG or WebP images')
            blob = path.read_bytes()
            if len(blob) > 10_000_000:
                raise ValueError('Resize images larger than 10 MB before sending')
            content.append({'type': 'image_url', 'image_url': {
                'url': 'data:' + mime + ';base64,' + base64.b64encode(blob).decode()}})
        payload = {'model': model, 'messages': [{'role': 'user', 'content': content}], 'stream': False}
        if model.startswith('gpt-'):
            payload.update(max_completion_tokens=max_tokens, reasoning_effort='low')
        else:
            payload['max_tokens'] = max_tokens
        if disable_thinking:
            if not model.startswith('doubao-'):
                raise ValueError('This optional thinking profile is scoped to Doubao routes only')
            payload['thinking'] = {'type': 'disabled'}
        raw = self.request('/chat/completions', payload)
        data = raw.pop('data', {})
        choices = data.get('choices') or []
        choice = choices[0] if choices else {}
        output = (choice.get('message') or {}).get('content') or ''
        if isinstance(output, list):
            output = '\n'.join(x.get('text', '') for x in output if isinstance(x, dict))
        if data.get('error'):
            raw['error'] = self.safe(json.dumps(data['error'], ensure_ascii=False))[:5000]
        raw.update(model=model, returned_model=data.get('model'), response=self.safe(output),
                   usage=data.get('usage'), finish_reason=choice.get('finish_reason'),
                   max_output_tokens=max_tokens, api_response_ok=raw['http_status'] == 200 and bool(output))
        if model.startswith('gpt-'):
            raw['reasoning_effort'] = 'low'
        if disable_thinking:
            raw['thinking'] = {'type': 'disabled'}
        return json.loads(self.safe(json.dumps(raw, ensure_ascii=False)))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config', type=Path, default=Path(__file__).resolve().parents[1] / 'api_key.json')
    p.add_argument('--model', default='gemini-3.5-flash')
    p.add_argument('--image', type=Path, action='append', required=True, help='Repeat for multiple images')
    p.add_argument('--prompt', default='请详细描述图片中的内容、物体、相互关系和可见文字；无法确定的信息请明确说明。')
    p.add_argument('--max-output-tokens', type=int, default=2048)
    p.add_argument('--timeout', type=int, default=55)
    p.add_argument('--disable-thinking', action='store_true', help='Doubao-only explicit low-latency profile')
    args = p.parse_args()
    client = VLMClient(args.config, args.timeout)
    result = client.understand(args.model, args.image, args.prompt, args.max_output_tokens, args.disable_thinking)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result['api_response_ok'] or result.get('finish_reason') == 'length':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
