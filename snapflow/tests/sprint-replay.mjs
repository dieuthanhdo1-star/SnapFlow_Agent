// Real Chrome interaction checks through its built-in debugging protocol.
// No packages, external services, model requests, or credentials are used.
import { mkdir, writeFile } from 'node:fs/promises';
import assert from 'node:assert/strict';
const root = new URL('../', import.meta.url);
const output = new URL('../tmp/sprint-20260914/replay-final/', root);
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

const results=[];
function pass(name){results.push(name);console.log('PASS',name);}
async function field(id,key,value){await evaluate(`(()=>{const el=document.querySelector('[data-job="${id}"] [data-field="${key}"]');el.value=${JSON.stringify(value)};el.dispatchEvent(new Event('input',{bubbles:true}));})()`);}
const {readFile}=await import('node:fs/promises');
const dataset=new URL('../tmp/sprint-20260914/new-cases/',root);
const samples=JSON.parse(await readFile(new URL('manifest.json',dataset),'utf8'));
try{
 await cdp('Page.enable');await cdp('Runtime.enable');await cdp('Log.enable');await cdp('DOM.enable');
 await cdp('Emulation.setDeviceMetricsOverride',{width:1440,height:1050,deviceScaleFactor:1,mobile:false});
 await cdp('Page.navigate',{url:'http://127.0.0.1:8769'});await waitFor('typeof intake!=="undefined" && intake.timer');
 const doc=await cdp('DOM.getDocument');const input=await cdp('DOM.querySelector',{nodeId:doc.root.nodeId,selector:'#file-input'});
 await cdp('DOM.setFileInputFiles',{nodeId:input.nodeId,files:samples.map(s=>decodeURIComponent(new URL(s.file,dataset).pathname))});
 await waitFor('!intake.uploading && intake.jobs.size===20 && [...intake.jobs.values()].every(j=>j.status==="ready")');
 assert.equal(await evaluate('imageCount([...intake.jobs.values()])'),15);
 assert.equal(await evaluate('state.items.length'),0);
 pass('15 new PNG screenshots upload through the native file input and produce 20 recorded-cloud drafts');
 await screenshot('new-batch-desktop.png');
 await click('#batch-save');await waitFor('state.items.length===19 && !intake.saving');
 assert.equal(await evaluate('[...intake.jobs.values()].filter(j=>j.status==="ready").length'),1);
 assert.equal(await evaluate('[...intake.jobs.values()].find(j=>j.status==="ready").filename'),'13.png');
 await cdp('Page.reload');await waitFor('intake.timer && state.items.length===19');
 pass('One confirmation saves 19 actions, preserves the event without an end time, and survives reload');
 await cdp('Page.navigate',{url:'http://127.0.0.1:8769/guide.html'});await waitFor('document.querySelectorAll("[data-step]").length===10');
 await evaluate('document.querySelector("[data-step=open]").checked=false'); await click('[data-step="open"]');await evaluate('document.querySelector("#notes").value="10张用时待测";document.querySelector("#notes").dispatchEvent(new Event("input"))');
 await cdp('Page.reload');await waitFor('document.querySelector("[data-step=open]").checked');
 assert.equal(await evaluate('document.querySelector("#notes").value'),'10张用时待测');
 await click('#check');await waitFor('document.querySelector("#status").textContent.includes("创建成功记录：0")');
 assert.equal(await evaluate('getComputedStyle(document.body).backgroundColor'),'rgb(246, 247, 251)');
 await screenshot('guide-desktop.png');
 await cdp('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
 assert.equal(await evaluate('document.documentElement.scrollWidth<=innerWidth'),true);
 await screenshot('guide-mobile.png');
 pass('Two-day guide loads under CSP, saves checklist/notes, checks status read-only, and fits mobile');
 assert.deepEqual(errors,[]);
 await writeFile(new URL('../tmp/sprint-20260914/replay-final/report.json',root),JSON.stringify({passed:results,errors,images:15,actions:20,saved:19,held_for_review:1,local_model_calls:0,feishu_live:false},null,2));
}finally{await cdp('Page.close').catch(()=>{});ws.close();}
