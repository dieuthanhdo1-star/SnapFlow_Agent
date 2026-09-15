// Real Chrome interaction checks through its built-in debugging protocol.
// No packages, external services, model requests, or credentials are used.
import { mkdir, writeFile } from 'node:fs/promises';
import assert from 'node:assert/strict';
const root = new URL('../', import.meta.url);
const output = new URL('../tmp/album-agent-20260914/browser/', root);
await mkdir(output, { recursive: true });
const target = await (await fetch('http://127.0.0.1:9244/json/new?about:blank', { method: 'PUT' })).json();
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
async function waitFor(expression) { for (let i = 0; i < 120; i++) { if (await evaluate(`(() => { try { return !!(${expression}); } catch { return false; } })()`)) return; await new Promise(r => setTimeout(r, 100)); } throw new Error(`Timed out: ${expression}`); }
async function click(selector) { await evaluate(`document.querySelector(${JSON.stringify(selector)}).click()`); }
async function screenshot(name) { const data = await cdp('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true }); await writeFile(new URL(name, output), Buffer.from(data.data, 'base64')); }

const results=[];const pass=name=>{results.push(name);console.log('PASS',name);};
try{
 await cdp('Page.enable');await cdp('Runtime.enable');await cdp('Log.enable');
 await cdp('Emulation.setDeviceMetricsOverride',{width:1440,height:1050,deviceScaleFactor:1,mobile:false});
 await cdp('Page.navigate',{url:'http://127.0.0.1:8774'});await waitFor('state && config.csrf');
 assert.equal(await evaluate('document.querySelectorAll("nav button").length'),8);
 assert.equal(await evaluate('document.querySelectorAll("a[href*=guide]").length'),0);
 await screenshot('01-empty-desktop.png');pass('Clean six-skill homepage without old guide/demo');
 await click('#pick-folder');await waitFor('document.querySelector("#consent").open');
 assert.equal(await evaluate('state.sources.length'),0);
 await click('#consent-form [type=submit]');await waitFor('state.sources.length===1 && state.sources[0].enabled');
 await click('#pause-source');await waitFor('!state.sources[0].enabled');
 await click('#pause-source');await waitFor('state.sources[0].enabled');
 pass('Native picker consent, pause and resume use persistent APIs');
 await click('#upload-open');
 await evaluate(`(()=>{window.fixtureFiles=['event','task','bookmark','missing','failure','chat'].map(marker=>{const c=document.createElement('canvas');c.width=320;c.height=400;const x=c.getContext('2d');x.fillStyle='#edf4ed';x.fillRect(0,0,320,400);x.fillStyle='#245533';x.font='24px sans-serif';x.fillText('离线流程测试',24,55);x.fillText(marker,24,100);return new File([Uint8Array.from(atob(c.toDataURL('image/png').split(',')[1]),x=>x.charCodeAt(0)),'CASE:'+marker],marker+'.png',{type:'image/png'});});const dt=new DataTransfer();fixtureFiles.forEach(f=>dt.items.add(f));document.querySelector('#files').files=dt.files;})()`);
 await click('#upload-start');await waitFor('state.items.length===3 && state.reviews.length===3');
 await click('[data-close="upload-dialog"]');
 assert.equal(await evaluate('state.pending.filter(j=>j.status==="failed").length'),1);
 pass('Batch upload automatically saves reliable results and isolates ambiguity/failure');
 await click('[data-filter="homework"]');assert.equal(await evaluate('document.querySelectorAll(".card").length'),1);
 await click('[data-filter="review"]');assert.equal(await evaluate('document.querySelectorAll(".card").length'),3);
 const missing=await evaluate('state.reviews.find(r=>r.draft.kind==="event").id');await click(`[data-detail="${missing}"]`);
 await evaluate(`document.querySelector('#review-title').value='已核对的讲座';document.querySelector('#review-notes').value='<img src=x onerror=alert(1)> 保留原文';document.querySelector('#review-end').value=document.querySelector('#review-start').value.replace('18:00','19:00');`);
 await new Promise(r=>setTimeout(r,4000));assert.equal(await evaluate('document.querySelector("#review-title").value'),'已核对的讲座');
 await click('#review-form [type=submit]');await waitFor('state.items.length===4 && !document.querySelector("#detail").open');
 assert.equal(await evaluate('document.querySelectorAll("#cards img[src=x]").length'),0);
 pass('Filters, review edits across polling and safe rendering work');
 await click('[data-filter="all"]');const eventId=await evaluate('state.items.find(i=>i.title==="已核对的讲座").id');await click(`[data-detail="${eventId}"]`);
 const calendar=await evaluate(`fetch('/api/items/${eventId}/calendar').then(r=>r.text())`);assert.match(calendar,/BEGIN:VEVENT/);
 await click('[data-close="detail"]');
 const taskId=await evaluate('state.items.find(i=>i.kind==="task").id');await click(`[data-detail="${taskId}"]`);await click('#complete-item');await waitFor(`state.items.find(i=>i.id==='${taskId}').status==='completed'`);
 pass('Saved event exports valid calendar; task completion persists');
 const bookmarkId=await evaluate('state.items.find(i=>i.kind==="bookmark").id');await click(`[data-detail="${bookmarkId}"]`);await click('#edit-item');
 await evaluate('document.querySelector("#review-skill").value="reference";document.querySelector("#review-title").value="修改后的资料标题"');await click('#review-form [type=submit]');await waitFor(`state.items.find(i=>i.id==='${bookmarkId}').skill==='reference'`);
 assert.equal(await evaluate('state.items.length'),4);pass('Auto-saved item title and category can be corrected without duplication');
 await click('#upload-open');await evaluate(`(()=>{const dt=new DataTransfer();fixtureFiles.slice(0,3).forEach(f=>dt.items.add(f));document.querySelector('#files').files=dt.files;})()`);await click('#upload-start');await waitFor('document.querySelector("#upload-progress").textContent.includes("跳过重复 3 张")');assert.equal(await evaluate('state.items.length'),4);await click('[data-close="upload-dialog"]');
 pass('Duplicate batch does not create records or rerun models');
 await click('#settings-open');await waitFor('document.querySelector("#settings").open');
 await evaluate('document.querySelector("#sync-events").checked=true;document.querySelector("#sync-tasks").checked=true');await click('#save-sync');await waitFor('state.settings.sync_tasks && state.settings.sync_events');
 await click('[data-source][data-action="revoke"]');await waitFor('state.sources.length===0');
 await screenshot('02-settings-desktop.png');await click('[data-close="settings"]');
 pass('Explicit auto-sync authorization binds targets; revoke removes folder access');
 await screenshot('03-results-desktop.png');
 await cdp('Page.reload');await waitFor('state && state.items.length===4');assert.equal(await evaluate('state.settings.sync_tasks'),true);
 await cdp('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
 assert.equal(await evaluate('document.documentElement.scrollWidth<=innerWidth'),true);await screenshot('04-results-mobile.png');
 await click('#settings-open');assert.equal(await evaluate('document.querySelector("#settings").scrollWidth<=document.querySelector("#settings").clientWidth'),true);
 pass('Reload preserves data/settings; narrow viewport has no horizontal overflow');
 assert.deepEqual(errors,[]);
 await writeFile(new URL('report.json',output),JSON.stringify({passed:results.length,results,errors,scope:'Offline browser fixture; native Windows picker and live Feishu not exercised'},null,2));
 console.log('ALL PASS',results.length);
}catch(error){await screenshot('failure.png');await writeFile(new URL('failure.json',output),JSON.stringify({error:String(error),results,errors},null,2));throw error;}finally{ws.close();}
