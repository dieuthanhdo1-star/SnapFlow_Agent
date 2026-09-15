"""Offline replay of recorded cloud responses. PIL is needed for this test only."""
import hashlib
import json
import re
import sys
from pathlib import Path
from PIL import Image
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server import App, Handler, ThreadingHTTPServer, Problem
root = Path(sys.argv[1]).resolve()
rows = json.loads((root/'sources.json').read_text())
results = {x['id']: x for x in json.loads((root/'results-v3.json').read_text())}
def pixel_key(path):
    with Image.open(path) as im:
        im.seek(0); im=im.convert('RGB')
        return hashlib.sha256(str(im.size).encode()+im.tobytes()).hexdigest()
lookup = {pixel_key(root/r['normalized_file']): results[r['id']] for r in rows}
class ReplayApp(App):
    def call_vision(self, image, body):
        result = lookup.get(pixel_key(self.uploads/image))
        if not result: raise Problem('离线回放找不到此样例', 502)
        data = json.loads(re.sub(r'^```(?:json)?\s*|\s*```$', '', result['response'].strip()))
        return data, {'requested_model': result['model'], 'returned_model': result['returned_model'], 'source': 'recorded-cloud-response', 'seconds': result['seconds'], 'upstream_verified': False}
app = ReplayApp(root/'browser'/'web30-final-data', config={'VISION_BASE_URL':'https://offline.invalid','VISION_API_KEY':'offline','VISION_MODEL':'recorded-cloud-response'})
server = ThreadingHTTPServer(('127.0.0.1',8768), Handler);server.app=app
print('Offline recorded-response replay on 8768; no model calls.',flush=True)
server.serve_forever()
