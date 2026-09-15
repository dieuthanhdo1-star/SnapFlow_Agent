// Real Chrome interaction checks through its built-in debugging protocol.
// No packages, external services, model requests, or credentials are used.
import { mkdir, writeFile } from 'node:fs/promises';
import assert from 'node:assert/strict';
const root = new URL('../', import.meta.url);
const output = new URL('../tmp/screenshot-feishu-20260913/browser/screenshots/', root);
await mkdir(output, { recursive: true });
const target = await (await fetch('http://127.0.0.1:9223/json/new?about:blank', { method: 'PUT' })).json();
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

const results=[];
function pass(name){results.push(name);console.log('PASS',name);}
async function field(id,key,value){await evaluate(`(()=>{const el=document.querySelector('[data-job="${id}"] [data-field="${key}"]');el.value=${JSON.stringify(value)};el.dispatchEvent(new Event('input',{bubbles:true}));})()`);}
try {
 await cdp('Page.enable');await cdp('Runtime.enable');await cdp('Log.enable');
 await cdp('Emulation.setDeviceMetricsOverride',{width:1440,height:1050,deviceScaleFactor:1,mobile:false});
 await cdp('Page.navigate',{url:'http://127.0.0.1:8767'});
 await waitFor('typeof intake !== "undefined" && intake.timer && state.config?.vision');
 await evaluate(`(()=>{
  const make=marker=>{const canvas=document.createElement('canvas');canvas.width=420;canvas.height=540;const c=canvas.getContext('2d');const colors={event:'#eee6fb',task:'#f8f0dc',bookmark:'#e2f2eb',missing:'#eef0fa',failure:'#f1eef2'};c.fillStyle=colors[marker];c.fillRect(0,0,420,540);c.fillStyle='#534868';c.font='16px sans-serif';c.fillText('SNAPFLOW · 测试示例',35,55);c.font='bold 30px sans-serif';const titles={event:'校园摄影分享会',task:'交互设计作业',bookmark:'设计灵感阅读',missing:'周末主题讲座',failure:'模糊截图示例'};c.fillText(titles[marker],35,130);c.font='18px sans-serif';c.fillText('为下一个想法，留一步。',35,180);c.fillText('2026 / 09 / 15',35,320);c.fillText('预设测试数据',35,460);const bytes=Uint8Array.from(atob(canvas.toDataURL('image/png').split(',')[1]),s=>s.charCodeAt(0));return new File([bytes,'CASE:'+marker],marker+'.png',{type:'image/png'});};
  const event=make('event');const transfer=new DataTransfer();for(const file of [event,make('task'),make('bookmark'),make('missing'),make('failure'),event,new File(['bad'],'bad.txt',{type:'text/plain'})])transfer.items.add(file);
  const input=document.querySelector('#file-input');input.files=transfer.files;input.dispatchEvent(new Event('change',{bubbles:true}));
 })()`);
 await waitFor('intake.jobs.size === 5 && !intake.uploading && [...intake.jobs.values()].every(j=>!["queued","running"].includes(j.status))');
 assert.equal(await evaluate('document.querySelector("#upload-dialog") === null'),true);
 assert.equal(await evaluate('state.items.length'),0);
 assert.equal(await evaluate('[...intake.jobs.values()].filter(j=>j.status==="ready").length'),4);
 assert.match(await evaluate('document.querySelector("#batch-error").textContent'),/相同图片/);
 assert.match(await evaluate('document.querySelector("#batch-error").textContent'),/bad.txt/);
 pass('Multi-select starts classification directly; duplicate and invalid files are isolated');
 assert.match(await evaluate('document.querySelector("#batch-save").textContent'),/3/);
 const ids=await evaluate('Object.fromEntries([...intake.jobs.values()].map(j=>[j.filename.split(".")[0],j.id]))');
 assert.deepEqual(await evaluate('[...intake.jobs.values()].filter(j=>j.status==="ready").map(j=>j.fields.kind).slice(0,3)'),['event','task','bookmark']);
 pass('Three action types appear automatically; missing end time is excluded from ready selection');
 await evaluate('document.querySelector("#batch-progress").textContent += " · 离线演示数据"');
 await screenshot('batch-desktop.png');
 await field(ids.task,'title','明晚提交设计作业');
 await new Promise(r=>setTimeout(r,2200));
 assert.equal(await evaluate(`document.querySelector('[data-job="${ids.task}"] [data-field="title"]').value`),'明晚提交设计作业');
 await cdp('Page.reload');await waitFor('intake.jobs.size===5 && intake.timer');
 await click('#resume-batch');
 assert.equal(await evaluate(`intake.jobs.get('${ids.task}').fields.title`),'明晚提交设计作业');
 pass('Polling and page reload preserve pending results and user edits');
 await click('#batch-save');await waitFor('state.items.length===3 && !intake.saving');
 assert.equal(await evaluate('state.items.find(i=>i.kind==="task").title'),'明晚提交设计作业');
 assert.equal(await evaluate('[...intake.jobs.values()].filter(j=>j.status==="saved").length'),3);
 pass('One confirmation saves all ready rows while preserving incomplete and failed rows');
 const end=await evaluate(`localValue(new Date(new Date(intake.jobs.get('${ids.missing}').fields.start_at+'+08:00').getTime()+3600000).toISOString())`);
 await field(ids.missing,'end_at',end);assert.match(await evaluate('document.querySelector("#batch-save").textContent'),/1/);
 await click('#batch-save');await waitFor('state.items.length===4 && !intake.saving');
 pass('Only the missing field needs editing before the remaining event can be saved');
 await click(`[data-job="${ids.failure}"] [data-job-action="retry"]`);
 await waitFor(`intake.jobs.get('${ids.failure}').status==='failed' && !intake.jobs.get('${ids.failure}').actionBusy`);
 assert.equal(await evaluate('state.items.length'),4);
 await click(`[data-job="${ids.failure}"] [data-job-action="manual"]`);
 await waitFor(`intake.jobs.get('${ids.failure}').status==='ready' && intake.jobs.get('${ids.failure}').draft.source==='manual'`);
 await field(ids.failure,'kind','bookmark');await field(ids.failure,'title','稍后查看的资料');
 await click('#batch-save');await waitFor('state.items.length===5 && !intake.saving');
 pass('A failed image can be retried or entered manually without repeating successful images');
 await click('#batch-close');
 assert.equal(await evaluate('document.querySelector("#resume-batch").hidden'),true);
 await cdp('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:false});
 assert.equal(await evaluate('document.documentElement.scrollWidth<=innerWidth'),true);
 await evaluate('openDialog("batch-dialog")');
 assert.equal(await evaluate('document.querySelector("#batch-dialog").scrollWidth<=document.querySelector("#batch-dialog").clientWidth'),true);
 await screenshot('batch-mobile.png');
 pass('Completed batch and 390px mobile dialog have no horizontal overflow');
 assert.deepEqual(errors,[]);pass('No uncaught JavaScript exceptions');
 await writeFile(new URL('../tmp/screenshot-feishu-20260913/browser/batch-browser-report.json',root),JSON.stringify({date:new Date().toISOString(),passed:results,errors,real_model_calls:0,note:'Offline fixture responses exercise the real upload queue and save endpoints.'},null,2));
} finally {await cdp('Page.close').catch(()=>{});ws.close();}
