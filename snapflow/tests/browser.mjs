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
const results = [];
function pass(name) { results.push(name); console.log('PASS', name); }
try {
  await cdp('Page.enable'); await cdp('Runtime.enable'); await cdp('Log.enable');
  await cdp('Emulation.setDeviceMetricsOverride', { width: 1440, height: 1050, deviceScaleFactor: 1, mobile: false });
  await cdp('Page.navigate', { url: 'http://127.0.0.1:8766' });
  await waitFor('state.config && document.querySelector("#mode-pill").textContent.includes("手动")');
  await screenshot('01-desktop-home.png');
  assert.equal(await evaluate('document.documentElement.scrollWidth <= innerWidth'), true);
  pass('Desktop loads with explicit manual/demo mode and no overflow');

  await click('[data-demo="event"]'); await waitFor('document.querySelector("#review-dialog").open && !state.busy');
  assert.equal(await evaluate('state.items.length'), 0);
  assert.match(await evaluate('document.querySelector("#source-label").textContent'), /演示/);
  await screenshot('02-confirm-event.png');
  await evaluate('document.querySelector("#start-input").value = ""; document.querySelector("#confirm-button").click()');
  assert.equal(await evaluate('state.items.length'), 0);
  assert.equal(await evaluate('document.querySelector("#start-input").validity.valueMissing'), true);
  await click('#cancel-review'); await waitFor('!document.querySelector("#review-dialog").open');
  assert.equal(await evaluate('state.items.length'), 0);
  pass('Missing date blocks confirmation; cancellation creates no action');

  await click('[data-demo="event"]'); await waitFor('document.querySelector("#review-dialog").open && !state.busy');
  await click('#confirm-button'); await waitFor('document.querySelector("#detail-dialog").open && state.items.length === 1');
  const eventId = await evaluate('state.items[0].id');
  const ics = await (await fetch(`http://127.0.0.1:8766/api/items/${eventId}/calendar`)).text();
  assert.match(ics, /BEGIN:VEVENT/);
  assert.match(ics, /校园摄影分享会/);
  pass('Event confirmation persists a real record and exports a calendar file');
  await click('[data-close="detail-dialog"]');

  await click('[data-demo="task"]'); await waitFor('document.querySelector("#review-dialog").open && !state.busy');
  await evaluate('document.querySelector("#title-input").value = "<img src=x onerror=alert(1)>课程作业"');
  await click('#confirm-button'); await waitFor('document.querySelector("#detail-dialog").open && state.items.length === 2');
  assert.equal(await evaluate('document.querySelector("#detail-title img") === null'), true);
  await click('[data-close="detail-dialog"]');
  assert.equal(await evaluate('document.querySelector(".item-title img") === null'), true);
  pass('Task creation and safe rendering of text that resembles HTML');

  await evaluate(`(async () => {
    const data = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aXioAAAAASUVORK5CYII=';
    const bytes = Uint8Array.from(atob(data), c => c.charCodeAt(0));
    const file = new File([bytes], 'fixture.png', { type: 'image/png' });
    const transfer = new DataTransfer(); transfer.items.add(file);
    const input = document.querySelector('#file-input'); input.files = transfer.files; input.dispatchEvent(new Event('change', { bubbles: true }));
  })()`);
  await waitFor('document.querySelector("#batch-dialog").open && [...intake.jobs.values()].some(j => j.status === "ready")');
  assert.equal(await evaluate('document.querySelector("#upload-dialog") === null'), true);
  await evaluate(`const card=document.querySelector('.batch-card'); const kind=card.querySelector('[data-field="kind"]'); kind.value='bookmark'; kind.dispatchEvent(new Event('input',{bubbles:true})); const title=card.querySelector('[data-field="title"]'); title.value='我的设计参考'; title.dispatchEvent(new Event('input',{bubbles:true}));`);
  await click('#batch-save'); await waitFor('state.items.length === 3 && !intake.saving');
  assert.equal(await evaluate('state.items.find(i => i.title === "我的设计参考").source'), 'manual');
  await click('#batch-close');
  await evaluate('showDetail(state.items.find(i => i.title === "我的设计参考").id)');
  await waitFor('document.querySelector(".detail-image").complete && document.querySelector(".detail-image").naturalWidth > 0');
  await click('[data-close="detail-dialog"]');
  pass('Actual file upload, manual clarification, bookmark save, original image preview');

  await click('[data-view="bookmark"]');
  assert.equal(await evaluate('document.querySelectorAll(".action-card").length'), 1);
  await evaluate('document.querySelector("#search-input").value="不存在"; document.querySelector("#search-input").dispatchEvent(new Event("input"))');
  assert.equal(await evaluate('document.querySelector("#empty-state").hidden'), false);
  await evaluate('document.querySelector("#search-input").value=""; document.querySelector("#search-input").dispatchEvent(new Event("input"))');
  await click('[data-view="all"]');
  await screenshot('03-action-list.png');
  pass('Type filters and search update visible results');

  await cdp('Page.reload'); await waitFor('state.items.length === 3');
  pass('Browser reload restores all saved actions');
  await click(`[data-complete="${eventId}"]`); await waitFor(`state.items.find(i => i.id === '${eventId}').status === 'completed'`);
  await click('[data-status="completed"]');
  assert.equal(await evaluate('document.querySelectorAll(".action-card").length'), 1);
  assert.equal(await evaluate('document.querySelector("#stat-completed").textContent'), '1');
  pass('Completion moves action to completed and updates counters');

  await click('#notifications-button'); await waitFor('document.querySelector("#notification-dialog").open');
  assert.match(await evaluate('document.querySelector("#notification-list").textContent'), /暂时没有/);
  await click('[data-close="notification-dialog"]');
  await click('#settings-button');
  assert.match(await evaluate('document.querySelector("#settings-dialog").textContent'), /关闭页面/);
  await click('[data-close="settings-dialog"]');
  pass('Reminder inbox and connection limitations are available in the UI');

  await click('[data-status="active"]');
  await cdp('Emulation.setDeviceMetricsOverride', { width: 390, height: 844, deviceScaleFactor: 1, mobile: false });
  assert.equal(await evaluate('document.documentElement.scrollWidth <= innerWidth'), true);
  await screenshot('04-mobile-home.png');
  await click('[data-demo="event"]'); await waitFor('document.querySelector("#review-dialog").open && !state.busy');
  assert.equal(await evaluate('document.querySelector("#review-dialog").scrollWidth <= document.querySelector("#review-dialog").clientWidth'), true);
  await screenshot('05-mobile-confirm.png');
  await click('#cancel-review'); await waitFor('!document.querySelector("#review-dialog").open');
  pass('390px mobile layout and confirmation dialog have no horizontal overflow');
  assert.deepEqual(errors, []);
  pass('No uncaught JavaScript exceptions or browser security errors');
  await writeFile(new URL('../tmp/screenshot-feishu-20260913/browser/browser-test-report.json', root), JSON.stringify({ date: new Date().toISOString(), passed: results, errors, note: 'No real vision or Feishu calls. Test records isolated under .test-work/browser.' }, null, 2));
} finally {
  await cdp('Page.close').catch(() => {}); ws.close();
}
