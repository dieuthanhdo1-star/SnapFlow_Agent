/* Native photo selection and explicit Feishu account connection. */
async function preparePhoto(file) {
  if (!file.size || file.size > 8 * 1024 * 1024) throw new Error('请选择 8 MB 以内的图片。');
  if (['image/png', 'image/jpeg', 'image/webp'].includes(file.type)) return readImage(file);
  if (!file.type.startsWith('image/') && !/\.(gif|bmp|heic|heif)$/i.test(file.name)) throw new Error('这不是支持的图片文件。');
  const url = URL.createObjectURL(file);
  try {
    const img = new Image(); img.src = url;
    try { await img.decode(); } catch { throw new Error('浏览器无法解码此图片，请转为 JPG 或 PNG 后再选。'); }
    if (!img.width || img.width * img.height > 24000000) throw new Error('图片像素过大，请缩小后再选。');
    const canvas = document.createElement('canvas'); canvas.width = img.width; canvas.height = img.height;
    canvas.getContext('2d').drawImage(img, 0, 0);
    const data = canvas.toDataURL('image/png');
    if (data.length > 8 * 1024 * 1024 * 4 / 3 + 30) throw new Error('转换后的图片超过 8 MB，请缩小后再选。');
    return data;
  } finally { URL.revokeObjectURL(url); }
}
const photoLibrary = {handle: null, files: [], urls: [], generation: 0};
function releasePhotos() {
  photoLibrary.generation++;
  for (const url of photoLibrary.urls) URL.revokeObjectURL(url);
  photoLibrary.urls = []; photoLibrary.files = [];
  $('photo-grid').replaceChildren();
}
async function browsePhotos() {
  if (!window.showDirectoryPicker) { $('file-input').click(); return; }
  try {
    const handle = await window.showDirectoryPicker({mode: 'read', id: 'snapflow-photos'});
    releasePhotos(); photoLibrary.handle = handle;
    const generation = photoLibrary.generation;
    openDialog('photo-dialog'); $('photo-status').textContent = `正在读取 ${handle.name}…`;
    const entries = [];
    for await (const entry of handle.values()) {
      if (entry.kind === 'file' && /\.(png|jpe?g|webp|gif|bmp|heic|heif)$/i.test(entry.name)) entries.push(entry);
      if (entries.length >= 300) break;
    }
    for (const entry of entries) {
      if (generation !== photoLibrary.generation) return;
      const file = await entry.getFile();
      if (generation !== photoLibrary.generation) return;
      const index = photoLibrary.files.push(file)-1;
      const url = URL.createObjectURL(file); photoLibrary.urls.push(url);
      const label = document.createElement('label'); label.className = 'photo-tile';
      const input = document.createElement('input'); input.type = 'checkbox'; input.value = index;
      const img = document.createElement('img'); img.src = url; img.alt = file.name; img.loading = 'lazy';
      const title = document.createElement('span'); title.textContent = file.name;
      label.append(input, img, title); $('photo-grid').append(label);
    }
    $('photo-status').textContent = `${handle.name} · ${photoLibrary.files.length} 张（仅显示当前文件夹前 300 张）`;
  } catch (error) { if (error.name !== 'AbortError') toast('读取图片文件夹失败，请重新授权或使用打开相册。'); }
}
async function loadFeishuStatus() {
  const status = await api('/api/feishu/status');
  $('feishu-app-id').value = status.app_id;
  $('feishu-status').textContent = status.connected ? `已连接 · ${status.calendar_name}` : status.authorized ? '已授权 · 请选择日历' : status.configured ? '应用已配置 · 待登录' : '未连接';
  $('feishu-secret').placeholder = status.configured ? '已保存；留空保留原值' : '仅保存在本机';
  $('feishu-callback').textContent = `${location.origin}/api/feishu/callback`;
  const steps = [['保存应用配置', status.configured], ['登录并授权账号', status.authorized], ['选择可写日历', status.connected], ['飞书确认创建日程', status.successful_events > 0]];
  $('feishu-steps').innerHTML = steps.map(([label, done]) => `<li class="${done ? 'done' : ''}">${done ? '✓ ' : ''}${label}</li>`).join('');
  $('feishu-next').textContent = status.successful_events ? `当前日历已有 ${status.successful_events} 条创建成功记录。请在飞书核对时间与提醒。` : status.connected ? '下一步：保存一条时间完整的日程，再确认同步；目前还没有创建成功记录。' : status.authorized ? '下一步：点“读取我的日历”，选择后点“连接此日历”。' : status.configured ? '下一步：点“登录飞书授权”。' : '下一步：在飞书开放平台创建应用、开通上方用户权限并发布，再在这里保存 App ID 和 App Secret。';
  state.config = await api('/api/config');
  return status;
}
async function feishuAction(action) {
  const buttons = [...$('feishu-controls').querySelectorAll('button')];
  buttons.forEach(b => b.disabled = true); $('feishu-error').textContent = '';
  try { await action(); }
  catch (error) { $('feishu-error').textContent = error.message; }
  finally { buttons.forEach(b => b.disabled = false); }
}
function initConnections() {
  $('feishu-copy-callback').onclick = async () => {
    try { await navigator.clipboard.writeText($('feishu-callback').textContent); toast('重定向地址已复制。'); }
    catch { toast('未能自动复制，请选中上方地址复制。'); }
  };
  $('batch-sync-close').onclick = () => { if (!calendarTransfer.busy) $('batch-sync-dialog').close(); };
  $('batch-sync-dialog').addEventListener('cancel', event => { if (calendarTransfer.busy) event.preventDefault(); });
  $('batch-sync-confirm').onclick = runBatchSync;
  $('batch-sync-list').addEventListener('change', event => {
    if (event.target.matches('[data-sync-item]') && !calendarTransfer.busy) {
      const row = calendarTransfer.rows.find(row => row.id === event.target.dataset.syncItem);
      if (row) row.selected = event.target.checked;
      updateSyncButton();
    }
  });
  $('album-button').onclick = () => $('file-input').click();
  $('folder-button').onclick = browsePhotos;
  $('photo-use').onclick = () => {
    const selected = [...$('photo-grid').querySelectorAll('input:checked')].map(i => photoLibrary.files[Number(i.value)]);
    if (!selected.length || selected.length > 30) { $('photo-status').textContent = '请选中 1～30 张照片。'; return; }
    $('photo-dialog').close(); releasePhotos(); photoLibrary.handle = null; intakeFiles(selected);
  };
  $('photo-dialog').addEventListener('close', () => {releasePhotos(); photoLibrary.handle = null;});
  $('settings-button').addEventListener('click', () => feishuAction(loadFeishuStatus));
  $('feishu-save').onclick = () => feishuAction(async () => {
    await api('/api/feishu/configure', {app_id: $('feishu-app-id').value, app_secret: $('feishu-secret').value});
    $('feishu-secret').value = ''; await loadFeishuStatus(); toast('应用配置已保存，下一步登录飞书。');
  });
  $('feishu-login').onclick = () => feishuAction(async () => { const r = await api('/api/feishu/connect', {}); location.assign(r.url); });
  $('feishu-calendars').onclick = () => feishuAction(async () => {
    const rows = await api('/api/feishu/calendars', {}); $('feishu-calendar').replaceChildren();
    for (const row of rows) { const option = document.createElement('option'); option.value = row.id; option.textContent = row.name; $('feishu-calendar').append(option); }
    if (!rows.length) throw new Error('没有可写日历，请给应用开通日历权限并重新授权。');
    toast('日历已读取，请选择并连接。');
  });
  $('feishu-select').onclick = () => feishuAction(async () => { await api('/api/feishu/select', {calendar_id: $('feishu-calendar').value}); await loadFeishuStatus(); toast('飞书日历已连接，日程详情中可确认同步。'); });
  $('feishu-disconnect').onclick = () => feishuAction(async () => {await api('/api/feishu/disconnect', {}); $('feishu-calendar').replaceChildren(); await loadFeishuStatus();});
  const query = new URLSearchParams(location.search);
  if (['connected', 'error'].includes(query.get('feishu'))) {
    history.replaceState(null, '', '/'); openDialog('settings-dialog');
    feishuAction(async () => {await loadFeishuStatus(); if (query.get('feishu') === 'error') $('feishu-error').textContent = query.get('message') || '授权未完成，请重试。';});
  }
}

const calendarTransfer = {busy: false, target: '', rows: []};
function updateSyncButton() {
  const count = calendarTransfer.rows.filter(row => row.selected && !row.done).length;
  $('batch-sync-confirm').disabled = calendarTransfer.busy || !count;
  $('batch-sync-confirm').textContent = calendarTransfer.busy ? '正在同步…' : `确认同步 ${count} 条日程`;
  $('batch-sync-close').disabled = calendarTransfer.busy;
}
function renderSyncRows() {
  $('batch-sync-list').innerHTML = calendarTransfer.rows.map(row => `<label class="batch-sync-row"><input type="checkbox" data-sync-item="${row.id}" ${row.selected ? 'checked' : ''} ${calendarTransfer.busy || row.done ? 'disabled' : ''}><span><b>${esc(row.title)}</b><small>${esc(fmt(row.start_at))} — ${esc(fmt(row.end_at))}</small><small>${esc(row.done ? '✓ 飞书已确认创建成功' : row.error || '等待你确认')}</small></span></label>`).join('');
  updateSyncButton();
}
async function openBatchSync() {
  if (calendarTransfer.busy) { openDialog('batch-sync-dialog'); return; }
  const status = await api('/api/feishu/status');
  if (!status.sync_target) {
    openDialog('settings-dialog'); await loadFeishuStatus(); toast('先连接飞书日历；已保存的事项会保留。'); return;
  }
  await refresh();
  const ids = new Set([...intake.jobs.values()].filter(job => job.status === 'saved').map(job => job.saved_item_id));
  calendarTransfer.target = status.sync_target;
  calendarTransfer.rows = state.items.filter(item => ids.has(item.id) && item.kind === 'event' && item.status === 'active').map(item => ({...item, done: item.sync_state === 'synced', selected: item.sync_state !== 'synced', error: item.sync_error || ''}));
  $('batch-sync-target').textContent = `目标日历：${status.calendar_name || '已配置的团队日历'}。以下仅包含这一批已保存的日程。`;
  $('batch-sync-error').textContent = '';
  renderSyncRows(); openDialog('batch-sync-dialog');
}
async function runBatchSync() {
  if (calendarTransfer.busy) return;
  const selected = calendarTransfer.rows.filter(row => row.selected && !row.done);
  if (!selected.length) return;
  calendarTransfer.busy = true; $('batch-sync-error').textContent = ''; renderSyncRows();
  let success = 0;
  try {
    for (const row of selected) {
      try {
        const result = await api(`/api/items/${row.id}/sync`, {confirmed: true, expected_target: calendarTransfer.target});
        if (result.sync_state !== 'synced') throw new Error('创建结果待核对，请在飞书检查后再决定是否重试。');
        row.done = true; row.selected = false; row.error = ''; success++;
      } catch (error) { row.error = error.message; row.selected = false; }
      renderSyncRows();
    }
    await refresh();
    const failed = selected.filter(row => !row.done).length;
    $('batch-sync-error').textContent = failed ? `${failed} 条未确认成功，本地记录已保留。请先核对飞书，再勾选需要重试的日程；不会自动重复调用。` : '';
    toast(`飞书已确认 ${success} 条日程。请在飞书核对时间和提醒。`);
  } catch (error) { $('batch-sync-error').textContent = error.message + ' 请重新打开同步清单核对结果。'; }
  finally { calendarTransfer.busy = false; renderSyncRows(); }
}
