"""Replay new, recorded cloud results through the actual app; no local inference."""
import hashlib,json,re,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from server import App,Handler,ThreadingHTTPServer,Problem
root=Path(sys.argv[1])
rows=json.loads((root/'manifest.json').read_text())
results={r['id']:r for r in json.loads((root/'results.json').read_text())}
lookup={r['sha256']:results[r['id']] for r in rows}
class Replay(App):
    def call_vision(self,image,body):
        result=lookup.get(hashlib.sha256((self.uploads/image).read_bytes()).hexdigest())
        if not result:raise Problem('离线回放：不认识这张图片',502)
        return json.loads(re.sub(r'^```(?:json)?\s*|\s*```$','',result['response'].strip())), {'requested_model':result['model'],'returned_model':result['returned_model'],'seconds':result['seconds'],'source':'recorded-cloud-response','upstream_verified':False}
app=Replay(root/(sys.argv[2] if len(sys.argv)>2 else 'replay-data'),config={'VISION_BASE_URL':'https://offline.invalid','VISION_API_KEY':'offline','VISION_MODEL':'recorded-cloud-response'})
http=ThreadingHTTPServer(('127.0.0.1',8769),Handler);http.app=app
print('Recorded cloud response replay on 8769; zero local model requests',flush=True)
try:http.serve_forever()
finally:http.server_close();app.batch_pool.shutdown(wait=True)
