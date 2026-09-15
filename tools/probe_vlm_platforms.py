#!/usr/bin/env python3
"""Small authenticated vision smoke tests; never print/store credentials."""
import argparse
import base64
import concurrent.futures
import datetime as dt
import json
from pathlib import Path
import re
import struct
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib

ROOT = Path('/home/lidanshi/lizekai/AgentM')
CHOICES = {
    'OpenAI': ['gpt-5.4-mini', 'gpt-5.4'],
    'Anthropic': ['claude-haiku-4-5', 'claude-sonnet-4-6'],
    'Google': ['gemini-2.5-flash', 'gemini-3.1-pro-preview'],
    'Qwen': ['qwen3.6-flash', 'qwen3.7-plus'],
    'Doubao': ['doubao-seed-2-0-pro', 'doubao-seed-2-1-turbo'],
    'Kimi': ['kimi-k2.6', 'kimi-k3'],
    'GLM': ['glm-5.3', 'glm-5.1'],
    'MiniMax': ['minimax-m3', 'MiniMax/MiniMax-M2.7'],
    'DeepSeek': ['deepseek-v4-flash', 'deepseek-v3.2'],
}
EXPECTED = {'code': '5837', 'blue_triangles': 3,
            'top_left_color': 'red', 'top_left_shape': 'circle'}
PROMPT = ('Inspect the attached image. Read the four digits in its bottom-right '
          'quadrant, count the blue triangles in its bottom-left quadrant, and '
          'identify the color and shape in its top-left quadrant. Return only '
          'JSON with keys code (string), blue_triangles (integer), '
          'top_left_color (lowercase English), top_left_shape (lowercase English).')


def fixture():
    """Generate a deterministic 400x300 PNG without external image libraries."""
    w, h = 400, 300
    rows = [bytearray([255] * (w * 3)) for _ in range(h)]
    def pixel(x, y, color):
        if 0 <= x < w and 0 <= y < h:
            rows[y][x * 3:x * 3 + 3] = bytes(color)
    def rect(x1, y1, x2, y2, color):
        for y in range(y1, y2):
            for x in range(x1, x2): pixel(x, y, color)
    for y in range(25, 125):
        for x in range(40, 140):
            if (x - 90) ** 2 + (y - 75) ** 2 <= 45 ** 2:
                pixel(x, y, (230, 20, 20))
    rect(250, 40, 360, 110, (0, 155, 40))
    for center in (40, 100, 160):
        for y in range(190, 245):
            half = int((y - 190) * 0.42)
            for x in range(center - half, center + half + 1):
                pixel(x, y, (15, 70, 235))
    glyphs = {
        '5': ['11111', '10000', '10000', '11110', '00001', '00001', '11110'],
        '8': ['01110', '10001', '10001', '01110', '10001', '10001', '01110'],
        '3': ['11110', '00001', '00001', '01110', '00001', '00001', '11110'],
        '7': ['11111', '00001', '00010', '00100', '01000', '01000', '01000'],
    }
    for i, digit in enumerate(EXPECTED['code']):
        for gy, line in enumerate(glyphs[digit]):
            for gx, bit in enumerate(line):
                if bit == '1':
                    x, y = 222 + i * 40 + gx * 6, 195 + gy * 6
                    rect(x, y, x + 6, y + 6, (0, 0, 0))
    def chunk(kind, data):
        return (struct.pack('!I', len(data)) + kind + data +
                struct.pack('!I', zlib.crc32(kind + data) & 0xffffffff))
    raw = b''.join(b'\x00' + bytes(row) for row in rows)
    return (b'\x89PNG\r\n\x1a\n' +
            chunk(b'IHDR', struct.pack('!2I5B', w, h, 8, 2, 0, 0, 0)) +
            chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b''))


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # Never forward credentials to a redirected destination.


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=Path, default=ROOT / 'api_key.json')
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--timeout', type=int, default=45)
    parser.add_argument('--workers', type=int, default=3)
    parser.add_argument('--platforms', nargs='+', choices=list(CHOICES), default=list(CHOICES))
    parser.add_argument('--disable-deepseek-thinking', action='store_true')
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    key = config['API_KEY']
    base = config['BASE_URL'].rstrip('/')
    parsed = urllib.parse.urlsplit(base)
    if parsed.scheme != 'https' or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('Expected a plain HTTPS API base URL without credentials or query parameters')
    api = base if parsed.path.rstrip('/').endswith('/v1') else base + '/v1'
    args.output_dir.mkdir(parents=True, exist_ok=False)
    def safe(value):
        return str(value).replace(key, '[REDACTED]')
    def save(name, value):
        (args.output_dir / name).write_text(safe(json.dumps(value, ensure_ascii=False, indent=2)) + '\n')
    def request(path, payload=None):
        start = time.monotonic()
        headers = {'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'}
        req = urllib.request.Request(api + path, headers=headers,
            data=json.dumps(payload).encode() if payload is not None else None)
        result = {}
        try:
            with urllib.request.build_opener(NoRedirect).open(req, timeout=args.timeout) as response:
                body = response.read(2_000_000)
                result = {'http_status': response.status, 'data': json.loads(body)}
        except urllib.error.HTTPError as exc:
            result = {'http_status': exc.code, 'error': safe(exc.read(1800).decode('utf-8', 'replace'))}
        except Exception as exc:
            result = {'http_status': None, 'error': safe(type(exc).__name__ + ': ' + str(exc))}
        result['seconds'] = round(time.monotonic() - start, 3)
        return result
    inventory = request('/models')
    if inventory.get('http_status') != 200:
        save('inventory_error.json', inventory)
        raise SystemExit('Model inventory failed; see sanitized inventory_error.json')
    model_ids = [x['id'] for x in inventory['data'].get('data', [])]
    save('models.json', {'base_url': base, 'models': model_ids})
    png = fixture()
    (args.output_dir / 'vision-test.png').write_bytes(png)
    image_url = 'data:image/png;base64,' + base64.b64encode(png).decode()
    def probe(model, vision):
        content = [{'type': 'text', 'text': PROMPT},
                   {'type': 'image_url', 'image_url': {'url': image_url}}] if vision else 'Reply exactly: API_OK'
        payload = {'model': model, 'messages': [{'role': 'user', 'content': content}], 'stream': False}
        if model.startswith('gpt-'):
            payload.update(max_completion_tokens=1024, reasoning_effort='low')
        else:
            payload['max_tokens'] = 1024 if vision else 128
        if args.disable_deepseek_thinking and model.startswith('deepseek-'):
            payload['thinking'] = {'type': 'disabled'}
        raw = request('/chat/completions', payload)
        result = {k: v for k, v in raw.items() if k != 'data'}
        result.update(model=model, test='vision' if vision else 'text')
        if 'thinking' in payload:
            result['thinking'] = payload['thinking']
        data = raw.get('data', {})
        result['returned_model'] = data.get('model')
        result['usage'] = data.get('usage')
        choices = data.get('choices') or []
        message = (choices[0].get('message') or {}) if choices else {}
        output = message.get('content') or ''
        if isinstance(output, list): output = '\n'.join(x.get('text', '') for x in output if isinstance(x, dict))
        result['response'] = safe(output)[:1800]
        result['finish_reason'] = choices[0].get('finish_reason') if choices else None
        if data.get('error'): result['error'] = safe(json.dumps(data['error'], ensure_ascii=False))[:1800]
        result['api_response_ok'] = raw.get('http_status') == 200 and bool(choices) and bool(output)
        if vision:
            try:
                match = re.search(r'\{.*\}', output, re.S)
                answer = json.loads(match.group(0) if match else output)
                checks = {k: str(answer.get(k, '')).strip().lower() == str(v) for k, v in EXPECTED.items()}
                result.update(checks=checks, vision_pass=all(checks.values()))
            except (ValueError, TypeError, AttributeError):
                result.update(checks={}, vision_pass=False)
        else:
            result['text_pass'] = output.strip().strip('`').strip() == 'API_OK'
        return result
    def family(platform, candidates):
        attempts = []
        for model in [m for m in candidates if m in model_ids]:
            visual = probe(model, True)
            attempts.append(visual)
            print(safe(json.dumps({'platform': platform, **visual}, ensure_ascii=False)), flush=True)
            if visual.get('vision_pass'): break
            text_result = probe(model, False)
            attempts.append(text_result)
            print(safe(json.dumps({'platform': platform, **text_result}, ensure_ascii=False)), flush=True)
        value = {'platform': platform, 'attempts': attempts,
                 'vision_available': any(a.get('vision_pass') for a in attempts)}
        save(platform.lower() + '.json', value)
        return value
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        tasks = {pool.submit(family, p, CHOICES[p]): p for p in args.platforms}
        for task in concurrent.futures.as_completed(tasks):
            try:
                results.append(task.result())
            except Exception as exc:
                value = {'platform': tasks[task], 'vision_available': False, 'error': safe(str(exc))}
                results.append(value)
                print(safe(json.dumps(value)), flush=True)
    report = {'tested_at': dt.datetime.now(dt.timezone.utc).isoformat(), 'base_url': base,
              'scope': 'Representative model routes through configured gateway; not provider-wide uptime',
              'expected': EXPECTED, 'results': results}
    save('results.json', report)
    print('COMPLETE ' + str(args.output_dir / 'results.json'), flush=True)


if __name__ == '__main__':
    main()
