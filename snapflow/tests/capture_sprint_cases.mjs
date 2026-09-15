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
const {readFile}=await import('node:fs/promises');
const rows=JSON.parse(await readFile(new URL('../tmp/sprint-20260914/new-cases/cases.json',root),'utf8'));
const htmlEscape=s=>s.replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;');
try {
 await cdp('Page.enable'); await cdp('Runtime.enable');
 await cdp('Emulation.setDeviceMetricsOverride',{width:780,height:1120,deviceScaleFactor:1,mobile:false});
 const tree=await cdp('Page.getFrameTree');
 for(const row of rows){
  const chat=row.category==='chat';
  const html=`<!doctype html><meta charset="utf-8"><style>*{box-sizing:border-box}body{margin:0;background:${chat?'#ededed':'#f3f0e7'};color:#243449;font:24px 'Noto Sans CJK SC',sans-serif}header{padding:30px;border-bottom:1px solid #d7d7d7;background:white;font-size:29px;font-weight:700}main{padding:28px}.msg{margin:0 0 24px;max-width:690px}.name{font-size:18px;color:#777;margin-bottom:9px}.bubble{padding:20px;background:white;border-radius:10px;line-height:1.8;overflow-wrap:anywhere}.poster header{background:#213f63;color:white}.poster .bubble{border-left:5px solid #577fac}.slide header{font-size:35px}.meme .bubble{font-size:35px;text-align:center;padding:36px}</style><body class="${row.category}"><header>${htmlEscape(row.title)}</header><main>${row.blocks.map(([who,text])=>`<section class="msg"><div class="name">${htmlEscape(who)}</div><div class="bubble">${htmlEscape(text)}</div></section>`).join('')}</main></body>`;
  await cdp('Page.setDocumentContent',{frameId:tree.frameTree.frame.id,html});
  await evaluate('document.fonts.ready');
  await screenshot(row.id+'.png'); console.log('CAPTURED',row.id);
 }
} finally {await cdp('Page.close').catch(()=>{});ws.close();}
