// Real Chrome interaction checks through its built-in debugging protocol.
// No packages, external services, model requests, or credentials are used.
import { mkdir, writeFile } from 'node:fs/promises';
import assert from 'node:assert/strict';
const root = new URL('../', import.meta.url);
const output = new URL('../tmp/sprint-20260914/new-cases/images/', root);
await mkdir(output, { recursive: true });
const target = await (await fetch('http://127.0.0.1:9234/json/new?about:blank', { method: 'PUT' })).json();
const ws = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((resolve, reject) => { ws.addEventListener('open', resolve, { once: true }); ws.addEventListener('error', reject, { once: true }); });
let sequence = 0;
const pending = new Map();
const errors = [];
ws.addEventListener('message', event => {
  const message = JSON.parse(event.data);
  if (message.id) { const resolver = pending.get(message.id); if (resolver) { pending.delete(message.id); message.error ? resolver.reject(new Error(JSON.stringify(message.error))) : resolver.resolve(message.result); } }
  if (message.method === 'Runtime.exceptionThrown') errors.push(message.params.exceptionDetails.text + ': ' + (message.params.exceptionDetails.exception?.description || ''));
  if (message.method === 'Log.entryAdded' && message.params.entry.level === 'error' && !message.params.entry.text.includes('favicon')) errors.push(message.params.entry.text);
});
function cdp(method, params = {}) { return new Promise((resolve, reject) => { const id = ++sequence; const timer = setTimeout(() => { pending.delete(id); reject(new Error(`Timeout: ${method}`)); }, 15000); pending.set(id, { resolve: x => { clearTimeout(timer); resolve(x); }, reject: x => { clearTimeout(timer); reject(x); } }); ws.send(JSON.stringify({ id, method, params })); }); }
async function evaluate(expression) { const result = await cdp('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true, userGesture: true }); if (result.exceptionDetails) throw new Error(result.exceptionDetails.exception?.description || result.exceptionDetails.text); return result.result.value; }
async function waitFor(expression) { for (let i = 0; i < 60; i++) { if (await evaluate(`(() => { try { return !!(${expression}); } catch { return false; } })()`)) return; await new Promise(r => setTimeout(r, 100)); } throw new Error(`Timed out: ${expression}`); }
async function click(selector) { await evaluate(`document.querySelector(${JSON.stringify(selector)}).click()`); }
async function screenshot(name) { const data = await cdp('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true }); await writeFile(new URL(name, output), Buffer.from(data.data, 'base64')); }
const rows=[
 {id:'13',category:'public-notice',title:'艺术研究院讲座通知',url:'https://ysyjy.cuc.edu.cn/2026/0902/c8958a273488/page.htm',keyword:'青年学者',expected:{kinds:['event'],dates:['2026-09-07T19:00'],empty:['end_at']}},
 {id:'14',category:'public-notice',title:'烟台大学多智能体报告',url:'https://www.ytu.edu.cn/info/1035/21800.htm',keyword:'不确定性',expected:{kinds:['event'],dates:['2026-09-08T16:00','2026-09-08T18:00']}},
 {id:'15',category:'public-notice',title:'燕山大学科普论坛',url:'https://notice.ysu.edu.cn/info/2050/25833.htm',keyword:'第三届',expected:{required_kinds:['event'],note_contains:['9月19']}},
 {id:'16',category:'public-notice',title:'上海交大人工智能培训',url:'https://www.sjtu.edu.cn/tg/20260904/225675.html',keyword:'人工智能素养',expected:{required_kinds:['event','task']}}
];
try{
 await cdp('Page.enable');await cdp('Runtime.enable');
 await cdp('Emulation.setDeviceMetricsOverride',{width:1100,height:1400,deviceScaleFactor:1,mobile:false});
 for(const row of rows){
  try{
   await cdp('Page.navigate',{url:row.url});
   await waitFor(`document.readyState==='complete' && document.body.innerText.includes(${JSON.stringify(row.keyword)})`);
   const metrics=await cdp('Page.getLayoutMetrics');
   const data=await cdp('Page.captureScreenshot',{format:'png',captureBeyondViewport:true,clip:{x:0,y:0,width:Math.min(metrics.cssContentSize.width,1600),height:Math.min(metrics.cssContentSize.height,7000),scale:1}});
   await writeFile(new URL(row.id+'.png',output),Buffer.from(data.data,'base64'));
   row.file='images/'+row.id+'.png';row.provenance='公开官网页面的浏览器截图；未参与此前提示调试';row.captured=true;
   row.visible_text=await evaluate('document.body.innerText');
   console.log('CAPTURED',row.id,row.visible_text.length);
  }catch(e){row.captured=false;row.error=String(e);console.log('FAILED',row.id,row.error);}
 }
 await writeFile(new URL('../tmp/sprint-20260914/new-cases/public.json',root),JSON.stringify(rows,null,2));
}finally{await cdp('Page.close').catch(()=>{});ws.close();}
