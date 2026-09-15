// Real Chrome interaction checks through its built-in debugging protocol.
// No packages, external services, model requests, or credentials are used.
import { mkdir, writeFile } from 'node:fs/promises';
import assert from 'node:assert/strict';
const root = new URL('../', import.meta.url);
const output = new URL('../tmp/sprint-20260914/browser-run2/', root);
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
try {
 await cdp('Page.enable'); await cdp('Runtime.enable'); await cdp('Log.enable');
 await cdp('Emulation.setDeviceMetricsOverride',{width:1440,height:1050,deviceScaleFactor:1,mobile:false});
 await cdp('Page.navigate',{url:'http://127.0.0.1:8768'});
 await waitFor('typeof intake !== "undefined" && intake.timer');
 await click('#settings-button'); await waitFor('document.querySelector("#feishu-next").textContent.includes("还没有创建成功")');
 assert.equal(await evaluate('document.querySelectorAll("#feishu-steps .done").length'),3);
 await screenshot('setup-desktop.png'); await click('[data-close="settings-dialog"]');
 pass('Configured and authorized calendar is distinguished from verified creation');
 await evaluate(`(()=>{const files=['event','task','bookmark','missing','failure','chat'].map(marker=>{const c=document.createElement('canvas');c.width=320;c.height=400;const x=c.getContext('2d');x.fillStyle='#efeafb';x.fillRect(0,0,320,400);x.fillStyle='#403050';x.font='24px sans-serif';x.fillText('离线流程测试',24,55);x.fillText(marker,24,100);return new File([Uint8Array.from(atob(c.toDataURL('image/png').split(',')[1]),x=>x.charCodeAt(0)),'CASE:'+marker],marker+'.png',{type:'image/png'});});const dt=new DataTransfer();files.forEach(f=>dt.items.add(f));document.querySelector('#file-input').files=dt.files;document.querySelector('#file-input').dispatchEvent(new Event('change',{bubbles:true}));})()`);
 await waitFor('intake.jobs.size===7 && !intake.uploading && [...intake.jobs.values()].every(j=>!["queued","running"].includes(j.status))');
 const ids=await evaluate('Object.fromEntries([...intake.jobs.values()].map(j=>[j.filename.split(".")[0],j.id]))');
 assert.equal(await evaluate('document.querySelectorAll(".batch-edit[open]").length'),1);
 assert.equal(await evaluate('state.items.length'),0);
 await screenshot('review-desktop.png');
 pass('Complete items use compact summaries; only missing critical fields open an editor');
 await click('[data-batch-filter="attention"]');
 assert.equal(await evaluate('document.querySelectorAll(".batch-card:not([hidden])").length'),2);
 await click('[data-batch-filter="ready"]');
 assert.equal(await evaluate('document.querySelectorAll(".batch-card:not([hidden])").length'),5);
 pass('Filters separate ready items from missing fields and failed images');
 await click(`[data-job="${ids.task}"] .batch-edit>summary`);
 await field(ids.task,'title','我修改的任务标题');
 await new Promise(r=>setTimeout(r,2100));
 assert.equal(await evaluate(`intake.jobs.get('${ids.task}').fields.title`),'我修改的任务标题');
 await cdp('Page.reload'); await waitFor('intake.jobs.size===7 && intake.timer'); await click('#resume-batch');
 assert.equal(await evaluate(`intake.jobs.get('${ids.task}').fields.title`),'我修改的任务标题');
 await click('#batch-save'); await waitFor('state.items.length===5 && !intake.saving');
 assert.equal(await evaluate('state.items.filter(i=>i.kind==="task" && !i.due_at).length'),2);
 pass('Polling/reload preserve edits; tasks with optional questions save without clarification');
 const end=await evaluate(`localValue(new Date(new Date(intake.jobs.get('${ids.missing}').fields.start_at+'+08:00').getTime()+3600000).toISOString())`);
 await field(ids.missing,'end_at',end); await field(ids.missing,'title','模拟失败的第二场活动');
 await click('#batch-save'); await waitFor('state.items.length===6 && !intake.saving');
 await click('#batch-sync'); await waitFor('document.querySelector("#batch-sync-dialog").open');
 assert.equal(await evaluate('calendarTransfer.rows.length'),2);
 assert.equal(await evaluate('state.items.filter(i=>i.sync_state==="synced").length'),0);
 await screenshot('calendar-confirm-desktop.png');
 pass('Bulk calendar preview contains only saved events and does not write before confirmation');
 await click('#batch-sync-confirm'); await waitFor('!calendarTransfer.busy && calendarTransfer.rows.some(r=>r.done)');
 assert.equal(await evaluate('calendarTransfer.rows.filter(r=>r.done).length'),1);
 assert.equal(await evaluate('calendarTransfer.rows.filter(r=>r.selected).length'),0);
 assert.equal(await evaluate('state.items.length'),6);
 assert.match(await evaluate('document.querySelector("#batch-sync-error").textContent'),/不会自动重复调用/);
 pass('Per-event sync failure preserves local items; successful events cannot be resubmitted');
 await click('#batch-sync-close'); await click('#batch-close'); await click('#settings-button');
 await waitFor('document.querySelector("#feishu-next").textContent.includes("1 条创建成功")');
 assert.equal(await evaluate('document.querySelectorAll("#feishu-steps .done").length'),4);
 pass('Connection progress reflects actual successful responses from the offline contract server');
 await click('[data-close="settings-dialog"]');
 await cdp('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
 await click('#resume-batch'); await click('[data-batch-filter="attention"]');
 assert.equal(await evaluate('document.documentElement.scrollWidth<=innerWidth'),true);
 assert.equal(await evaluate('document.querySelector("#batch-dialog").scrollWidth<=document.querySelector("#batch-dialog").clientWidth'),true);
 await screenshot('review-mobile.png');
 await click('#batch-sync'); await waitFor('document.querySelector("#batch-sync-dialog").open');
 assert.equal(await evaluate('document.querySelector("#batch-sync-dialog").scrollWidth<=document.querySelector("#batch-sync-dialog").clientWidth'),true);
 await screenshot('calendar-confirm-mobile.png');
 pass('Review and calendar preview fit a 390px viewport');
 assert.deepEqual(errors,['Failed to load resource: the server responded with a status of 502 (Bad Gateway)']);
 await writeFile(new URL('../tmp/sprint-20260914/browser-run2/report.json',root),JSON.stringify({passed:results,errors:[],expected_network_errors:errors,real_model_calls:0,feishu_live:false,windows_native:false},null,2));
} finally {await cdp('Page.close').catch(()=>{});ws.close();}
