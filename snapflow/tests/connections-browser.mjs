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
 await cdp('Emulation.setDeviceMetricsOverride',{width:1440,height:1000,deviceScaleFactor:1,mobile:false});
 await cdp('Page.navigate',{url:'http://127.0.0.1:8767'});
 await waitFor('typeof intake !== "undefined" && intake.timer && typeof photoLibrary !== "undefined"');
 await click('#settings-button'); await waitFor('document.querySelector("#feishu-callback").textContent.includes("8767")');
 assert.match(await evaluate('document.querySelector("#feishu-status").textContent'),/未连接/);
 assert.equal(await evaluate('document.querySelector("#feishu-secret").type'),'password');
 await screenshot('feishu-settings-desktop.png');
 pass('Feishu setup displays callback, private secret field, login and calendar picker');
 await click('[data-close="settings-dialog"]');
 await evaluate(`window.showDirectoryPicker=async()=>({name:'测试照片',async *values(){for(let i=0;i<3;i++){yield {kind:'file',name:'相册'+i+'.png',getFile:async()=>{const c=document.createElement('canvas');c.width=40+i;c.height=50;c.getContext('2d').fillRect(0,0,20,20);const blob=await new Promise(r=>c.toBlob(r));return new File([blob], '相册'+i+'.png',{type:'image/png'})}}}}})`);
 await click('#folder-button'); await waitFor('photoLibrary.files.length===3');
 assert.equal(await evaluate('document.querySelectorAll("#photo-grid input").length'),3);
 await screenshot('photo-library-desktop.png');
 const before=await evaluate('intake.jobs.size');
 await evaluate('document.querySelectorAll("#photo-grid input")[0].checked=true');
 await click('#photo-use'); await waitFor('!intake.uploading');
 assert.equal(await evaluate('photoLibrary.urls.length'),0);
 assert.ok(await evaluate('intake.jobs.size')>=1);
 pass('Directory permission adapter previews locally; only chosen files enter intake; URLs released');
 await click('#batch-close');
 await evaluate(`window.showDirectoryPicker=async()=>{throw new DOMException('Cancelled','AbortError')}`);
 await click('#folder-button'); assert.equal(await evaluate('document.querySelector("#photo-dialog").open'),false);
 pass('Cancelled directory permission leaves the current page usable');
 await evaluate(`window.showDirectoryPicker=undefined;window.pickerOpened=false;document.querySelector('#file-input').click=()=>window.pickerOpened=true`);
 await click('#folder-button'); assert.equal(await evaluate('window.pickerOpened'),true);
 await click('#album-button'); assert.equal(await evaluate('window.pickerOpened'),true);
 pass('Unsupported directory API falls back to native photo picker');
 const gif='R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7';
 const result=await evaluate(`preparePhoto(new File([Uint8Array.from(atob('${gif}'),x=>x.charCodeAt(0))],'meme.gif',{type:'image/gif'}))`);
 assert.ok(result.startsWith('data:image/png;base64,'));
 assert.match(await evaluate(`preparePhoto(new File(['bad'],'bad.heic',{type:'image/heic'})).catch(e=>e.message)`),/无法解码/);
 pass('GIF becomes a supported static image; unsupported HEIC reports a clear error');
 await cdp('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
 await click('#settings-button');
 assert.equal(await evaluate('document.querySelector("#settings-dialog").scrollWidth<=document.querySelector("#settings-dialog").clientWidth'),true);
 await screenshot('feishu-settings-mobile.png');
 await click('[data-close="settings-dialog"]');
 assert.equal(await evaluate('document.documentElement.scrollWidth<=innerWidth'),true);
 await screenshot('photo-home-mobile.png');
 pass('390px viewport fits photo buttons and Feishu setup');
 assert.deepEqual(errors,[]);
 await writeFile(new URL('../tmp/screenshot-feishu-20260913/browser/connections-report.json',root),JSON.stringify({passed:results,errors,native_permission_dialog_automated:false,feishu_live:false},null,2));
} finally {await cdp('Page.close').catch(()=>{});ws.close();}
