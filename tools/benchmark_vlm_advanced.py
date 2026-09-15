#!/usr/bin/env python3
"""Run a bounded multi-provider image-understanding benchmark through one gateway."""
import argparse
import concurrent.futures
import datetime as dt
import json
from pathlib import Path
import random
import re
import statistics
from vlm_client import VLMClient

MODELS = ['gemini-3.5-flash','qwen3.7-plus','qwen3.7-max','qwen3.7-max-cc',
          'doubao-seed-2-1-pro','doubao-seed-2-1-turbo','gemini-3.8-flash','qwen3.8-max',
          'gpt-5.5','gpt-5.6-sol','claude-opus-5','claude-sonnet-5','kimi-k3','minimax-m3']


def equal(actual, expected):
    if isinstance(expected, bool): return isinstance(actual, bool) and actual == expected
    if isinstance(expected, (int,float)):
        return not isinstance(actual,bool) and isinstance(actual,(int,float)) and abs(actual-expected)<1e-6
    if isinstance(expected,list):
        return isinstance(actual,list) and len(actual)==len(expected) and all(equal(a,e) for a,e in zip(actual,expected))
    return isinstance(actual,str) and actual.strip().casefold() == expected.casefold()


def score(response, expected):
    try:
        match=re.search(r'\{.*\}', response, re.S)
        answer=json.loads(match.group(0) if match else response)
        if not isinstance(answer,dict): raise ValueError('Expected JSON object')
        checks={k:equal(answer.get(k),v) for k,v in expected.items()}
        return {'parsed_answer':answer,'checks':checks,'correct':sum(checks.values()),'possible':len(expected),'json_valid':True}
    except (ValueError,TypeError):
        return {'checks':{k:False for k in expected},'correct':0,'possible':len(expected),'json_valid':False}


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--config',type=Path,default=Path(__file__).resolve().parents[1]/'api_key.json')
    p.add_argument('--output-dir',type=Path,required=True)
    p.add_argument('--models',nargs='+',default=MODELS)
    p.add_argument('--tasks',nargs='+')
    p.add_argument('--workers',type=int,default=3)
    p.add_argument('--max-output-tokens',type=int,default=2048)
    p.add_argument('--timeout',type=int,default=55)
    p.add_argument('--run-name',default='main')
    p.add_argument('--disable-thinking',action='store_true')
    args=p.parse_args(); client=VLMClient(args.config,args.timeout)
    out=args.output_dir
    target=out/args.run_name; target.mkdir(exist_ok=False)
    def save(path,value):
        path.write_text(client.safe(json.dumps(value,ensure_ascii=False,indent=2))+'\n',encoding='utf-8')
    manifest=json.loads((out/'fixtures.json').read_text())
    tasks=[t for t in manifest['tasks'] if not args.tasks or t['id'] in args.tasks]
    inventory=client.request('/models'); save(target/'models.json',inventory)
    if inventory.get('http_status')!=200: raise SystemExit('Inventory failed; no inference calls made')
    available={m['id'] for m in inventory['data']['data']}
    started=dt.datetime.now(dt.timezone.utc).isoformat()
    def run(model,task):
        if model not in available:
            r={'model':model,'http_status':None,'seconds':0,'api_response_ok':False,'response':'','error':'Not in inventory'}
        else:
            r=client.understand(model,[out/'assets'/f for f in task['images']],task['prompt'],args.max_output_tokens,args.disable_thinking)
        r.update(task=task['id'],**score(r.get('response',''),task['expected']))
        save(target/(model+'--'+task['id']+'.json'),r)
        print(json.dumps({k:r.get(k) for k in ['model','task','http_status','seconds','correct','possible','finish_reason','error']},ensure_ascii=False),flush=True)
        return r
    jobs=[(m,t) for m in args.models for t in tasks]
    random.Random(20260909).shuffle(jobs)
    results=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures=[pool.submit(run,m,t) for m,t in jobs]
        for f in concurrent.futures.as_completed(futures): results.append(f.result())
    summary=[]
    for m in args.models:
        rs=[r for r in results if r['model']==m]
        summary.append({'model':m,'correct':sum(r['correct'] for r in rs),'possible':sum(r['possible'] for r in rs),
                        'responses_ok':sum(bool(r['api_response_ok']) for r in rs),'requests':len(rs),
                        'median_seconds':round(statistics.median(r['seconds'] for r in rs),3),
                        'task_scores':{r['task']:r['correct'] for r in rs},
                        'reported_tokens':sum((r.get('usage') or {}).get('total_tokens',0) for r in rs)})
    save(target/'results.json',{'started_at':started,'completed_at':dt.datetime.now(dt.timezone.utc).isoformat(),
        'gateway':client.base,'max_output_tokens':args.max_output_tokens,'workers':args.workers,'disable_thinking':args.disable_thinking,
        'scope':'Gateway route tests, not verified upstream model identity or global model ranking',
        'summary':summary,'results':results})
    print('COMPLETE '+str(target/'results.json'),flush=True)


if __name__=='__main__': main()
