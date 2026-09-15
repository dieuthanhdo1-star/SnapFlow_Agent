'use strict';
const intake = { id: '', jobs: new Map(), uploading: false, saving: false, polling: false, timer: null, filter: 'all' };
function rememberJob(job) {
  try { localStorage.setItem('snapflow:batch:' + job.id, JSON.stringify({ draft_id: job.draft?.id, fields: job.fields, selected: job.selected })); } catch { /* Optional local cache. */ }
}
function jobGroup(job) {
  if (job.status === 'ready') return jobIssue(job) ? 'attention' : 'ready';
  if (['failed', 'interrupted'].includes(job.status)) return 'attention';
  return job.status;
}
function jobSummary(job) {
  const f = job.fields;
  const when = f.kind === 'event' ? [f.start_at, f.end_at].filter(Boolean).map(v => v.replace('T', ' ')).join(' — ') : (f.due_at ? '截止 ' + f.due_at.replace('T', ' ') : '不设截止时间');
  return `<strong>${esc(f.title || '待补充标题')}</strong><span>${esc(kindNames[f.kind] || '待分类')}${f.kind !== 'bookmark' ? ' · ' + esc(when) : ''}${f.location ? ' · ' + esc(f.location) : ''}</span>`;
}
function imageCount(jobs) { return new Set(jobs.map(j => j.image_job_id || j.id)).size; }
function randomId() { return crypto.randomUUID().replaceAll('-', ''); }
function jobFields(draft) {
  const values = {};
  for (const key of ['kind', 'title', 'location', 'notes', 'start_at', 'end_at', 'due_at', 'reminder_at']) values[key] = draft?.[key] || '';
  if (!kindNames[values.kind]) values.kind = '';
  for (const key of ['start_at', 'end_at', 'due_at', 'reminder_at']) values[key] = localValue(values[key]);
  return values;
}
function jobIssue(job) {
  if (job.status !== 'ready') return '';
  const f = job.fields;
  if (!f.kind) return '请选择行动类型';
  if (!f.title.trim()) return '请补充标题';
  if (f.kind === 'event') {
    if (!f.start_at) return '请补充完整的开始日期和时间';
    if (!f.end_at) return '原图未明确结束时间，请补充';
    if (new Date(f.end_at + '+08:00') <= new Date(f.start_at + '+08:00')) return '结束时间必须晚于开始时间';
  }
  return '';
}
function mergeBatch(result) {
  if (result.batch_id) intake.id = result.batch_id;
  for (const incoming of result.jobs || []) {
    const old = intake.jobs.get(incoming.id);
    const changedDraft = incoming.draft?.id && incoming.draft.id !== old?.draft?.id;
    const job = { ...old, ...incoming };
    if (!old?.fields || changedDraft) {
      job.fields = jobFields(incoming.draft);
      job.questionsReviewed = false;
      job.selected = incoming.status === 'ready';
      try {
        const saved = JSON.parse(localStorage.getItem('snapflow:batch:' + job.id) || 'null');
        if (saved?.draft_id && saved.draft_id === incoming.draft?.id) {
          job.fields = { ...job.fields, ...saved.fields }; job.selected = saved.selected; job.questionsReviewed = saved.questionsReviewed;
        }
      } catch { /* Local draft caching is optional. */ }
    }
    if (old?.status !== incoming.status) job.renderVersion = (old?.renderVersion || 0) + 1;
    intake.jobs.set(job.id, job);
  }
  renderBatch();
}
function batchCard(job) {
  const ready = job.status === 'ready';
  const f = job.fields;
  const names = { queued: '等待整理', running: job.mode === 'manual' ? '正在准备截图…' : `正在自动识别和分类…等待上限 ${state.config?.vision_timeout_seconds || 120} 秒`, ready: '待确认', failed: '识别未完成', interrupted: '上次处理已中断', saved: '已保存', cancelled: '已移出' };
  let body = '';
  if (ready) {
    const input = (key, label, type = 'text') => `<label class="field">${label}<input data-field="${key}" type="${type}" value="${esc(f[key])}" ${key === 'title' ? 'maxlength="160"' : ''}></label>`;
    body = `<div class="batch-action-summary" data-action-summary>${jobSummary(job)}</div><p class="batch-issue" data-issue></p><details class="batch-edit" ${jobIssue(job) ? 'open' : ''}><summary>修改事项 / 核对原文</summary><div class="batch-main-fields"><label class="field">${job.mode === 'manual' ? '行动类型（模型未连接）' : '自动分类'}<select data-field="kind"><option value="">请选择类型</option>${Object.entries(kindNames).map(([k, v]) => `<option value="${k}" ${f.kind === k ? 'selected' : ''}>${v}</option>`).join('')}</select></label>${input('title', '标题')}</div>
      ${job.draft.time_text ? `<p class="batch-time"><b>原文时间：</b>${esc(job.draft.time_text)}</p>` : ''}
      <div class="batch-dates" data-event-fields ${f.kind !== 'event' ? 'hidden' : ''}>${input('start_at', '开始时间 · 北京时间', 'datetime-local')}${input('end_at', '结束时间', 'datetime-local')}</div>
      <div data-task-fields ${f.kind !== 'task' ? 'hidden' : ''}>${input('due_at', '截止时间（可选，北京时间）', 'datetime-local')}</div>
      ${job.draft.questions?.length ? `<details class="batch-questions"><summary>原图有待核对信息（不影响无截止时间任务保存）</summary><p>${job.draft.questions.map(esc).join(' ')}</p></details>` : ''}
      <details class="batch-more"><summary>地点、备注与提醒</summary>${input('location', '地点（可选）')}<label class="field">备注<textarea data-field="notes" rows="2" maxlength="4000">${esc(f.notes)}</textarea></label>${input('reminder_at', '提醒时间（可选，北京时间）', 'datetime-local')}</details>
      </details><p class="form-error" data-save-error>${esc(job.saveError || '')}</p>`;
  } else if (['failed', 'interrupted'].includes(job.status)) {
    body = `<p class="form-error">${esc(job.error)}</p><div class="batch-retry-actions"><button class="secondary-button" data-job-action="retry">${job.status === 'interrupted' ? '确认重试这一张' : '重试这一张'}</button><button class="secondary-button" data-job-action="manual">手动填写</button></div>`;
  } else if (job.status === 'saved') {
    body = `<p class="batch-saved">✓ ${esc(job.fields.title || job.draft?.title)} · 已保存到${kindNames[job.fields.kind] || '行动列表'}</p>`;
  } else {
    body = job.mode === 'manual' ? '<p class="muted">视觉模型未连接，可直接在清单中填写。</p>' : '<p class="muted">不用补充说明，SnapFlow 会根据图片内容判断下一步。</p>';
  }
  return `<div class="batch-card-head"><button class="batch-preview" data-preview aria-label="查看原图：${esc(job.filename)}"><img src="/uploads/${job.image}" alt="${esc(job.filename)}"></button><div><span class="batch-filename">${esc(job.filename)}${job.action_count > 1 ? ` · 事项 ${job.action_index}/${job.action_count}` : ''}</span><b class="batch-state" data-state-label>${names[job.status]}</b></div>${ready ? `<label class="batch-pick"><input type="checkbox" data-selected ${job.selected ? 'checked' : ''}>保存</label>` : ''}${job.status !== 'saved' ? '<button class="icon-button" data-job-action="cancel" aria-label="移出这张截图">' + icon('close') + '</button>' : ''}</div>${body}`;
}
function renderBatch() {
  const jobs = [...intake.jobs.values()].filter(j => j.status !== 'cancelled');
  const list = $('batch-list');
  list.querySelectorAll('.batch-card').forEach(card => { if (!jobs.some(j => j.id === card.dataset.job)) card.remove(); });
  for (const job of jobs) {
    let card = list.querySelector(`[data-job="${job.id}"]`);
    if (!card) { card = document.createElement('article'); card.className = 'batch-card'; card.dataset.job = job.id; list.append(card); }
    const version = `${job.status}-${job.renderVersion || 0}`;
    if (card.dataset.version !== version) { card.innerHTML = batchCard(job); card.dataset.version = version; }
    const issue = jobIssue(job);
    if (job.status === 'ready') {
      card.querySelector('[data-issue]').textContent = issue;
      card.querySelector('[data-action-summary]').innerHTML = jobSummary(job);
      card.querySelector('[data-state-label]').textContent = issue ? '需要核对' : `${job.mode === 'manual' ? '手动填写' : '已识别为' + kindNames[job.fields.kind]} · 可保存`;
      card.querySelector('[data-selected]').checked = job.selected;
      card.querySelector('[data-save-error]').textContent = job.saveError || '';
      card.querySelector('[data-event-fields]').hidden = job.fields.kind !== 'event';
      card.querySelector('[data-task-fields]').hidden = job.fields.kind !== 'task';
    }
    card.classList.toggle('needs-attention', !!issue || ['failed', 'interrupted'].includes(job.status));
    card.classList.toggle('is-processing', ['queued', 'running'].includes(job.status));
    // Keep the active editor visible while a field correction changes its group.
    card.hidden = intake.filter !== 'all' && jobGroup(job) !== intake.filter && !card.contains(document.activeElement);
  }
  $('batch-filter-empty').hidden = !![...list.children].some(card => !card.hidden);
  updateBatchSummary();
}
function updateBatchSummary() {
  const jobs = [...intake.jobs.values()].filter(j => j.status !== 'cancelled');
  const working = jobs.filter(j => ['queued', 'running'].includes(j.status)).length;
  const ready = jobs.filter(j => j.status === 'ready' && !jobIssue(j));
  const selected = ready.filter(j => j.selected);
  const saved = jobs.filter(j => j.status === 'saved').length;
  const blocked = jobs.filter(j => ['failed', 'interrupted'].includes(j.status) || (j.status === 'ready' && jobIssue(j))).length;
  $('batch-progress').textContent = working ? `正在整理 ${working} 张 · 已收到 ${imageCount(jobs)} 张` : (saved === jobs.length && jobs.length ? '这一批已整理好，行动已保存。' : `已整理 ${imageCount(jobs)} 张截图 · ${jobs.length} 条事项，核对后一次保存。`);
  $('batch-summary').innerHTML = [['可保存', ready.length, 'ready'], ['待核对', blocked, 'attention'], ['已保存', saved, 'saved']].map(([text, n, style]) => `<span class="batch-count ${style}"><b>${n}</b>${text}</span>`).join('');
  $('batch-selection').textContent = `已选 ${selected.length} 条可保存行动`;
  $('batch-save').textContent = intake.saving ? '正在保存…' : `确认保存 ${selected.length} 条`;
  $('batch-save').disabled = !selected.length || intake.saving || intake.uploading;
  $('batch-select-ready').disabled = !ready.length || intake.saving;
  document.querySelectorAll('[data-batch-filter]').forEach(button => {
    const filter = button.dataset.batchFilter;
    const count = filter === 'all' ? jobs.length : jobs.filter(job => jobGroup(job) === filter).length;
    button.textContent = `${{all:'全部', attention:'待核对', ready:'可保存', saved:'已保存'}[filter]} ${count}`;
    button.setAttribute('aria-pressed', String(filter === intake.filter));
  });
  const events = jobs.filter(j => j.status === 'saved' && j.fields.kind === 'event');
  $('batch-sync').hidden = !events.length;
  $('batch-sync').disabled = intake.saving || intake.uploading;
  const unfinished = jobs.filter(j => j.status !== 'saved').length;
  $('resume-batch').hidden = !unfinished && !intake.uploading;
  $('resume-batch-count').textContent = working ? `${working} 张正在识别` : `${unfinished} 条待处理`;
}
async function pollBatch() {
  if (!intake.id || intake.polling) return;
  intake.polling = true;
  try { mergeBatch(await api(`/api/batches/${intake.id}`)); }
  catch (error) { $('batch-error').textContent = error.message; }
  finally { intake.polling = false; }
}
function readImage(file) {
  return new Promise((resolve, reject) => { const reader = new FileReader(); reader.onload = () => resolve(reader.result); reader.onerror = () => reject(new Error(`${file.name} 读取失败`)); reader.readAsDataURL(file); });
}
async function intakeFiles(files) {
  if (!files.length || state.busy || intake.uploading || intake.saving) return;
  const remaining = [...intake.jobs.values()].filter(j => !['saved', 'cancelled'].includes(j.status));
  if (!remaining.length) { intake.id = randomId(); intake.jobs.clear(); intake.filter = 'all'; $('batch-list').replaceChildren(); }
  if (!intake.id) intake.id = randomId();
  const existingCount = imageCount([...intake.jobs.values()].filter(j => j.status !== 'cancelled'));
  const accepted = files.slice(0, Math.max(0, (state.config?.max_batch_images || 30) - existingCount));
  const notices = [];
  if (accepted.length < files.length) notices.push('每批最多 30 张，超出部分尚未上传。');
  intake.uploading = true; $('batch-error').textContent = ''; openDialog('batch-dialog'); updateBatchSummary();
  for (let i = 0; i < accepted.length; i++) {
    const file = accepted[i]; $('batch-upload-status').textContent = `正在上传 ${i + 1}/${accepted.length}：${file.name}`;

    try {
      const image = await preparePhoto(file);
      const result = await api('/api/batches/upload', { batch_id: intake.id, request_id: randomId(), filename: file.name, image });
      if (result.duplicate) notices.push(`${file.name}：本批已有相同图片，已跳过。`);
      await pollBatch();
    } catch (error) { notices.push(`${file.name}：${error.message}`); }
  }
  intake.uploading = false;
  $('batch-upload-status').textContent = ''; $('batch-error').textContent = notices.join('\n');
  await pollBatch(); updateBatchSummary();
}
async function saveBatch() {
  if (intake.saving || intake.uploading) return;
  const selected = [...intake.jobs.values()].filter(j => j.status === 'ready' && j.selected && !jobIssue(j));
  if (!selected.length) return;
  const entries = selected.map(job => {
    const fields = { ...job.fields };
    for (const key of ['start_at', 'end_at', 'due_at', 'reminder_at']) if (fields[key]) fields[key] += ':00+08:00';
    return { job_id: job.id, fields };
  });
  intake.saving = true; $('batch-error').textContent = ''; updateBatchSummary();
  try {
    const result = await api('/api/batches/confirm', { batch_id: intake.id, confirmed: true, entries });
    let count = 0;
    for (const row of result.results) { const job = intake.jobs.get(row.job_id); if (!job) continue; if (row.saved) { count++; job.status = 'saved'; job.saved_item_id = row.item_id; } else { job.saveError = row.error; } }
    renderBatch(); await refresh();
    if (count) toast(`已保存 ${count} 条行动。`);
    await pollBatch();
  } catch (error) { $('batch-error').textContent = error.message + ' 请刷新清单核对，重复确认不会重复保存。'; }
  finally { intake.saving = false; updateBatchSummary(); }
}
async function initBatch() {
  $('batch-close').addEventListener('click', () => { if (!intake.saving) $('batch-dialog').close(); });
  $('batch-dialog').addEventListener('cancel', event => { if (intake.saving) event.preventDefault(); });
  $('resume-batch').addEventListener('click', () => { openDialog('batch-dialog'); pollBatch(); });
  $('batch-save').addEventListener('click', saveBatch);
  $('batch-select-ready').addEventListener('click', () => { for (const job of intake.jobs.values()) { job.selected = job.status === 'ready' && !jobIssue(job); rememberJob(job); } renderBatch(); });
  document.querySelectorAll('[data-batch-filter]').forEach(button => button.addEventListener('click', () => { intake.filter = button.dataset.batchFilter; renderBatch(); }));
  $('batch-sync').addEventListener('click', () => openBatchSync().catch(error => { $('batch-error').textContent = error.message; }));
  $('batch-list').addEventListener('input', event => {
    const card = event.target.closest('[data-job]'); if (!card) return;
    const job = intake.jobs.get(card.dataset.job); if (!job || intake.saving) return;
    if (event.target.dataset.field) job.fields[event.target.dataset.field] = event.target.value;
    if (event.target.matches('[data-selected]')) job.selected = event.target.checked;
    if (event.target.matches('[data-reviewed]')) job.questionsReviewed = event.target.checked;
    job.saveError = ''; renderBatch();
    rememberJob(job);
  });
  $('batch-list').addEventListener('click', async event => {
    const preview = event.target.closest('[data-preview]');
    if (preview) { const job = intake.jobs.get(preview.closest('[data-job]').dataset.job); $('batch-original').src = '/uploads/' + job.image; $('batch-image-name').textContent = job.filename; openDialog('batch-image-dialog'); return; }
    const button = event.target.closest('[data-job-action]'); if (!button || intake.saving || button.disabled) return;
    const job = intake.jobs.get(button.closest('[data-job]').dataset.job);
    if (job.actionBusy) return;
    job.actionBusy = true;
    button.closest('[data-job]').querySelectorAll('[data-job-action]').forEach(b => { b.disabled = true; });
    try { mergeBatch(await api(`/api/image-jobs/${job.id}`, { action: button.dataset.jobAction })); }
    catch (error) { $('batch-error').textContent = error.message; }
    finally { const current = intake.jobs.get(job.id); if (current) current.actionBusy = false; $('batch-list').querySelector(`[data-job="${job.id}"]`)?.querySelectorAll('[data-job-action]').forEach(b => { b.disabled = false; }); }
  });
  mergeBatch(await api('/api/batches/current'));
  intake.timer = setInterval(pollBatch, 2000);
}
init();
