// Real Chrome interaction checks through its built-in debugging protocol.
// No packages, external services, model requests, or credentials are used.
import { mkdir, writeFile, readFile } from 'node:fs/promises';
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
async function waitFor(expression) { for (let i = 0; i < 600; i++) { if (await evaluate(`(() => { try { return !!(${expression}); } catch { return false; } })()`)) return; await new Promise(r => setTimeout(r, 100)); } throw new Error(`Timed out: ${expression}`); }
async function click(selector) { await evaluate(`document.querySelector(${JSON.stringify(selector)}).click()`); }
async function screenshot(name) { const data = await cdp('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true }); await writeFile(new URL(name, output), Buffer.from(data.data, 'base64')); }

const results=[];
function pass(name){results.push(name);console.log('PASS',name);}
async function field(id,key,value){await evaluate(`(()=>{const el=document.querySelector('[data-job="${id}"] [data-field="${key}"]');el.value=${JSON.stringify(value)};el.dispatchEvent(new Event('input',{bubbles:true}));})()`);}
const dataset = new URL('../tmp/screenshot-feishu-20260913/', root);
const samples = JSON.parse(await readFile(new URL('sources.json',dataset),'utf8'));
try {
 await cdp('Page.enable');await cdp('Runtime.enable');await cdp('Log.enable');await cdp('DOM.enable');
 await cdp('Emulation.setDeviceMetricsOverride',{width:1440,height:1050,deviceScaleFactor:1,mobile:false});
 await cdp('Page.navigate',{url:'http://127.0.0.1:8768'});
 await waitFor('typeof intake!=="undefined" && intake.timer');
 const doc=await cdp('DOM.getDocument'); const input=await cdp('DOM.querySelector',{nodeId:doc.root.nodeId,selector:'#file-input'});
 await cdp('DOM.setFileInputFiles',{nodeId:input.nodeId,files:samples.map(s=>decodeURIComponent(new URL(s.file,dataset).pathname))});
 await waitFor('!intake.uploading && intake.jobs.size>=30 && [...intake.jobs.values()].every(j=>!["queued","running"].includes(j.status))');
 const jobs=await evaluate('[...intake.jobs.values()]');
 assert.equal(new Set(jobs.map(j=>j.image_job_id)).size,30);
 assert.ok(jobs.every(j=>j.status==='ready'),JSON.stringify(jobs.filter(j=>j.status!=='ready')));
 assert.equal(await evaluate('state.items.length'),0);
 pass('30 public original images including 2 GIFs upload in one batch; all recorded cloud responses become drafts');
 assert.equal(jobs.filter(j=>j.filename.startsWith('05-')).length,2);
 const train=jobs.find(j=>j.filename.startsWith('25-'));assert.equal(train.fields.kind,'bookmark');
 const weekly=jobs.find(j=>j.filename.startsWith('29-'));assert.equal(weekly.fields.kind,'task');
 pass('Mixed tutorial chat preserves both tasks; query form stays reference; weekly assignment is a task');
 await screenshot('web30-batch-desktop.png');
 await click('#batch-save');await waitFor('!intake.saving && state.items.length>0');
 const remaining=await evaluate('[...intake.jobs.values()].filter(j=>j.status==="ready").map(j=>({file:j.filename,kind:j.fields.kind,start:j.fields.start_at,end:j.fields.end_at}))');
 assert.ok(remaining.length>0);assert.ok(remaining.every(j=>j.kind==='event'&&(!j.start||!j.end)));
 pass('Single confirmation saves complete actions and leaves undated/incomplete events for review');
 await cdp('Page.reload');await waitFor('intake.timer && state.items.length>0');
 pass('Saved items and incomplete drafts survive reload');
 await click('#resume-batch');await cdp('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
 assert.equal(await evaluate('document.querySelector("#batch-dialog").scrollWidth<=document.querySelector("#batch-dialog").clientWidth'),true);
 await screenshot('web30-batch-mobile.png');
 const saved=await evaluate('state.items.length');
 assert.deepEqual(errors,[]);
 await writeFile(new URL('browser/web30-report.json',dataset),JSON.stringify({passed:results,errors,images:30,actions:jobs.length,saved,remaining,model_calls_in_browser_test:0,note:'Real cloud response replay through actual upload UI; no live model inference locally.'},null,2));
} finally {await cdp('Page.close').catch(()=>{});ws.close();}
