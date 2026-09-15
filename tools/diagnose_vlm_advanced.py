#!/usr/bin/env python3
"""Bounded follow-up: image-free controls, text-route tests, and one timeout retry."""
import argparse
import concurrent.futures
import json
from pathlib import Path
from benchmark_vlm_advanced import score
from vlm_client import VLMClient


def main():
    p=argparse.ArgumentParser();p.add_argument('--output-dir',type=Path,required=True)
    p.add_argument('--config',type=Path,default=Path(__file__).resolve().parents[1]/'api_key.json')
    args=p.parse_args();out=args.output_dir;target=out/'diagnostics';target.mkdir(exist_ok=False)
    manifest=json.loads((out/'fixtures.json').read_text())
    chart=next(t for t in manifest['tasks'] if t['id']=='chart')
    spatial=next(t for t in manifest['tasks'] if t['id']=='spatial')
    jobs=[]
    for model in ['gemini-3.5-flash','qwen3.7-plus','doubao-seed-2-1-pro','doubao-seed-2-1-turbo','qwen3.8-max','gpt-5.5']:
        jobs.append((model,'chart_without_image',[],chart['prompt'],chart['expected'],55))
    for model in ['qwen3.7-max','qwen3.7-max-cc']:
        jobs.append((model,'text_control',[],'Reply exactly: API_OK',None,55))
    jobs.append(('doubao-seed-2-1-pro','spatial_retry_120s',[out/'assets'/f for f in spatial['images']],spatial['prompt'],spatial['expected'],120))
    def run(job):
        model,kind,images,prompt,expected,timeout=job
        client=VLMClient(args.config,timeout)
        r=client.understand(model,images,prompt,2048)
        r.update(test=kind,timeout=timeout)
        if expected:r.update(score(r['response'],expected))
        else:r['text_pass']=r['response'].strip()=='API_OK'
        (target/(model+'--'+kind+'.json')).write_text(client.safe(json.dumps(r,ensure_ascii=False,indent=2))+'\n')
        print(json.dumps({k:r.get(k) for k in ['model','test','http_status','seconds','correct','possible','text_pass','finish_reason']},ensure_ascii=False),flush=True)
        return r
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:results=list(pool.map(run,jobs))
    client=VLMClient(args.config)
    (target/'results.json').write_text(client.safe(json.dumps(results,ensure_ascii=False,indent=2))+'\n')
    print('COMPLETE diagnostics',flush=True)


if __name__=='__main__':main()
