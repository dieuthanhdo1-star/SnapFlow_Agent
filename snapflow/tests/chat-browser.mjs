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
 await cdp('Page.enable'); await cdp('Runtime.enable'); await cdp('Log.enable');
 await cdp('Emulation.setDeviceMetricsOverride',{width:1440,height:1050,deviceScaleFactor:1,mobile:false});
 await cdp('Page.navigate',{url:'http://127.0.0.1:8767'});
 await waitFor('typeof intake !== "undefined" && intake.timer && state.config?.vision');
 const baseline=await evaluate('state.items.length');
 await evaluate(`(()=>{
  const canvas=document.createElement('canvas');canvas.width=600;canvas.height=800;
  const c=canvas.getContext('2d');c.fillStyle='#eee';c.fillRect(0,0,600,800);
  c.fillStyle='#222';c.font='24px sans-serif';c.fillText('群通知 · 完全虚构的离线测试示例',25,55);
  for(const [y,lines] of [[140,['通知一：设备借用','11月3日14:00开放办理','适用于本科生']],[420,['通知二：奖学金申请','11月5日10:00开放申请','适用于符合申请条件的同学']]]){
    c.fillStyle='white';c.fillRect(20,y-40,560,200);c.fillStyle='#222';lines.forEach((t,i)=>c.fillText(t,40,y+i*48));
  }
  const bytes=Uint8Array.from(atob(canvas.toDataURL('image/png').split(',')[1]),s=>s.charCodeAt(0));
  const file=new File([bytes,'CASE:chat'],'虚构聊天样例.png',{type:'image/png'});
  const dt=new DataTransfer();dt.items.add(file);const input=document.querySelector('#file-input');input.files=dt.files;input.dispatchEvent(new Event('change',{bubbles:true}));
 })()`);
 await waitFor('intake.jobs.size===2 && !intake.uploading && [...intake.jobs.values()].every(j=>j.status==="ready")');
 assert.match(await evaluate('document.querySelector("#batch-progress").textContent'),/1 张截图 · 2 条事项/);
 assert.deepEqual(await evaluate('[...intake.jobs.values()].map(j=>j.fields.kind)'),['task','task']);
 assert.equal(await evaluate('[...intake.jobs.values()].every(j=>!j.fields.due_at && !j.fields.start_at && !j.fields.end_at)'),true);
 assert.equal(await evaluate('document.querySelectorAll(".batch-time").length'),2);
 assert.match(await evaluate('document.querySelector("#batch-list").textContent'),/年份未注明/);
 assert.equal(await evaluate('document.querySelector("#batch-save").disabled'),false);
 pass('One image produces two editable notices with visible original times and no invented deadline');
 await evaluate('document.querySelector("#batch-progress").textContent += " · 离线虚构示例"');
 await screenshot('chat-desktop.png');
 const ids=await evaluate('[...intake.jobs.keys()]');
 await field(ids[1],'title','核对奖学金申请条件');
 await cdp('Page.reload'); await waitFor('intake.jobs.size===2 && intake.timer'); await click('#resume-batch');
 assert.equal(await evaluate(`intake.jobs.get('${ids[1]}').fields.title`),'核对奖学金申请条件');
 assert.equal(await evaluate('imageCount([...intake.jobs.values()])'),1);
 pass('Both notices and individual edits survive reload while upload quota still counts one image');
 await click(`[data-job="${ids[0]}"] [data-job-action="cancel"]`);
 await waitFor(`intake.jobs.get('${ids[0]}').status==='cancelled'`);
 assert.equal(await evaluate(`intake.jobs.get('${ids[1]}').status`),'ready');
 await click('#batch-save'); await waitFor(`state.items.length===${baseline+1} && !intake.saving`);
 const saved=await evaluate('state.items.find(i=>i.title==="核对奖学金申请条件")');
 assert.equal(saved.due_at,'');assert.match(saved.notes,/11月5日10:00开放/);
 pass('Removing one notice leaves its sibling independently saveable with original time retained');
 await cdp('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:false});
 assert.equal(await evaluate('document.querySelector("#batch-dialog").scrollWidth<=document.querySelector("#batch-dialog").clientWidth'),true);
 await screenshot('chat-mobile.png');
 assert.deepEqual(errors,[]);
 pass('Mobile layout has no horizontal overflow or JavaScript errors');
 await writeFile(new URL('../tmp/screenshot-feishu-20260913/browser/chat-browser-report.json',root),JSON.stringify({date:new Date().toISOString(),passed:results,errors,real_model_calls:0,note:'Fictional offline fixture, not recognition of the user private screenshot.'},null,2));
} finally {await cdp('Page.close').catch(()=>{});ws.close();}
