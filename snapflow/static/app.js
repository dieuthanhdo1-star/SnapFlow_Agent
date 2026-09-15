'use strict';
const $=id=>document.getElementById(id);
let config={},state=null,feishu={},filter='all',candidate=null,busy=false,toastTimer;
const names={task:'任务',todo:'待办',homework:'作业',event:'日程',idea:'灵感',reference:'资料'};
const kinds={task:'task',todo:'task',homework:'task',event:'event',idea:'bookmark',reference:'bookmark'};
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function toast(message){$('toast').textContent=message;$('toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('toast').hidden=true,7000);}
async function api(path,body){
 if(body!==undefined&&!config.csrf)config=await api('/api/config');
 const controller=new AbortController();const timer=setTimeout(()=>controller.abort(),path==='/api/agent/pick'?190000:45000);
 try{const response=await fetch(path,body===undefined?{signal:controller.signal}:{method:'POST',signal:controller.signal,headers:{'Content-Type':'application/json','X-Snapflow-Token':config.csrf},body:JSON.stringify(body)});
 const value=await response.json();if(!response.ok)throw Error(value.error||'操作未完成');return value;
 }catch(e){if(e.name==='AbortError')throw Error('本机服务响应超时，请查看启动窗口中的诊断日志。');throw e;}finally{clearTimeout(timer);}
}
function on(id,fn){$(id).addEventListener('click',async()=>{const button=$(id);button.disabled=true;try{await fn();}catch(e){toast(e.message);}finally{button.disabled=false;}});}
function skill(item){return names[item.skill]?item.skill:(item.kind==='event'?'event':item.kind==='task'?'task':'reference');}
function dateText(value){return value?value.slice(0,16).replace('T',' '):'';}
async function refresh(){if(busy)return;busy=true;try{state=await api('/api/agent/status');render();}finally{busy=false;}}
function render(){
 if(!state)return;
 const active=state.sources.find(s=>s.enabled),source=active||state.sources[0];
 $('source-badge').textContent=active?(config.vision?'自动整理中':'等待连接识别服务'):source?'已暂停':'尚未授权';
 $('source-title').textContent=source?source.path.split(/[\\/]/).filter(Boolean).pop():'连接你的截图文件夹';
 $('source-description').textContent=active?(config.vision?'新截图自动整理 · '+(state.last_scan?'最近检查 '+dateText(state.last_scan):'正在等待首次检查'):'文件夹已授权，连接识别服务后开始整理。'):source?'暂停期间不会自动读取新截图。':'';
 $('source-error').textContent=(!config.vision&&config.vision_config_error)||state.error||(!config.vision?'请先在设置中连接识别服务。':'');
 $('pick-folder').hidden=!!source;$('pause-source').hidden=!source;$('pause-source').textContent=active?'暂停整理':'继续整理';
 const count=state.items.length;$('result-count').textContent=count?`${count} 条`:'';
 const tabs=[['all','全部'],['review',`待核对${state.reviews.length?' · '+state.reviews.length:''}`],...Object.entries(names)];
 $('filters').innerHTML=tabs.map(([id,name])=>`<button data-filter="${id}" class="${filter===id?'selected':''}" aria-pressed="${filter===id}">${esc(name)}</button>`).join('');
 const query=$('search').value.trim().toLowerCase();
 const reviews=state.reviews.map(r=>({...r.draft,id:r.id,review:true,reasons:r.reasons}));
 const entries=[...reviews,...state.items].filter(item=>(filter==='all'||filter==='review'&&item.review||filter===skill(item))&&(!query||[item.title,item.notes,item.course,item.skill_data].join(' ').toLowerCase().includes(query)));
 $('cards').innerHTML=entries.map(i=>`<button class="card ${i.review?'review':''} ${i.status==='completed'?'completed':''}" data-detail="${esc(i.id)}" data-review="${i.review?'1':'0'}"><span class="type">${i.review?'待核对 · ':''}${names[skill(i)]}</span><h3>${esc(i.title||'待确认的截图')}</h3><p>${esc(i.notes||'已保存截图内容')}</p><span class="meta">${esc(dateText(i.start_at||i.due_at)||(i.review?'需要你核对':'已归档'))}${i.status==='completed'?' · 已完成':''}${i.sync_state==='synced'?' · 已同步飞书':''}${['uncertain','error'].includes(i.sync_state)?' · 同步待核对':''}</span></button>`).join('');
 $('empty').hidden=entries.length>0;
 if(!entries.length)$('empty').querySelector('h3').textContent=count||state.reviews.length?'这里暂时没有记录':'让截图变成有用的记录';
 const running=state.pending.filter(p=>['queued','running'].includes(p.status));
 $('activity').innerHTML=(running.length?`<p>正在整理 ${running.length} 张截图，完成后会自动出现。</p>`:'')+state.pending.filter(p=>!['queued','running'].includes(p.status)).map(p=>`<div class="activity-row">${esc(p.filename)}：${esc(p.error)} <button data-retry="${p.id}">重试识别</button><button data-dismiss="${p.id}">忽略</button></div>`).join('')+state.file_errors.map(p=>`<div class="activity-row">${esc(p.name)}：${esc(p.error)}</div>`).join('');
}
let folderGeneration=0,folderParent=null;
async function pick(){
 folderGeneration++;candidate=null;$('folder-input').value='';$('folder-path').hidden=true;$('folder-error').textContent='';
 $('consent').showModal();await browseFolder('');
}
async function browseFolder(path){
 const generation=++folderGeneration;
 if(typeof path!=='string')path=$('folder-input').value.trim();
 $('folder-browser').hidden=false;$('folder-list').setAttribute('aria-busy','true');$('folder-error').textContent='正在读取文件夹…';
 try{
  const selected=await api('/api/agent/folders',{path});
  if(generation!==folderGeneration||!$('consent').open)return;
  candidate=null;folderParent=selected.parent;$('folder-up').disabled=!folderParent;
  $('folder-input').value=selected.path;$('folder-current').textContent=selected.path||'选择磁盘';
  $('folder-list').innerHTML=selected.folders.length?selected.folders.map(f=>`<button type="button" class="folder-entry" data-folder="${esc(f.path)}"><span aria-hidden="true">▱</span> ${esc(f.name)} <span aria-hidden="true">›</span></button>`).join(''):'<p class="hint">没有子文件夹，可以直接授权当前文件夹。</p>';
  $('folder-path').textContent=selected.path;$('folder-path').hidden=!selected.path;
  $('folder-error').textContent=selected.truncated?'子文件夹较多，显示前 500 项；也可填写具体路径。':'';
 }catch(e){if(generation===folderGeneration)$('folder-error').textContent=e.message;}
 finally{if(generation===folderGeneration)$('folder-list').setAttribute('aria-busy','false');}
}
async function openSettings(){
 if(!state){config=await api('/api/config');await refresh();}
 $('feishu-callback').textContent=location.origin+'/api/feishu/callback';
 feishu=await api('/api/feishu/status');if(!$('settings').open)$('settings').showModal();
 $('source-settings').innerHTML=state.sources.map(s=>`<div>${esc(s.path)}<br><button data-source="${s.id}" data-action="${s.enabled?'pause':'resume'}">${s.enabled?'暂停':'继续'}</button><button data-source="${s.id}" data-action="revoke">撤销授权</button></div>`).join('')||'尚未授权文件夹';
 $('skill-options').innerHTML=Object.entries(state.skills).map(([id,s])=>`<label class="check"><input type="checkbox" data-skill="${id}" ${state.settings.skills.includes(id)?'checked':''}><span>${esc(s.name)}<small>${esc(s.description)}</small></span></label>`).join('');
 $('daily-limit').value=state.settings.daily_limit;
 $('vision-status').textContent=config.vision?'已连接 · '+config.vision_model:'尚未连接识别服务';
 $('feishu-status').textContent=feishu.authorized?`已授权${feishu.calendar_name?' · 日历：'+feishu.calendar_name:''}${feishu.task_connected?' · 任务：'+feishu.task_user_name:''}`:feishu.configured?'应用已准备好，登录飞书即可连接。':'尚未配置飞书应用，请由应用提供者完成下方配置。';
 $('feishu-connect').disabled=!feishu.configured;$('feishu-disconnect').hidden=!feishu.authorized;$('feishu-authorized').hidden=!feishu.authorized;
 $('feishu-app-id').value=feishu.app_id||'';
 $('sync-events').checked=state.settings.sync_events;$('sync-tasks').checked=state.settings.sync_tasks;
 $('sync-events').disabled=!feishu.sync_target;$('sync-tasks').disabled=!feishu.task_target;
 const mismatch=(state.settings.sync_events&&state.settings.calendar_target!==feishu.sync_target)||(state.settings.sync_tasks&&state.settings.task_target!==feishu.task_target);
 $('sync-targets').textContent=(mismatch?'账号或日历已变化，自动同步已停止。请重新确认。 ': '')+`目标日历：${feishu.calendar_name||'未选择'}；目标任务：${feishu.task_user_name||'未连接'}`;
}
function detail(id,isReview,editing=false){
 const review=isReview?state.reviews.find(r=>r.id===id):null;
 const item=review?review.draft:state.items.find(i=>i.id===id);if(!item)return;
 $('detail-heading').textContent=review?'核对事项':editing?'编辑事项':'事项详情';
 let data={};try{data=JSON.parse(item.skill_data||'{}');}catch{}
 const steps=item.steps||data.steps||[];
 const original=item.image?`<a href="/uploads/${esc(item.image)}" target="_blank" rel="noopener"><img class="detail-image" src="/uploads/${esc(item.image)}" alt="原始截图"></a>`:'';
 if(review||editing){
 $('detail-content').innerHTML=`<p class="review-reasons">${review?review.reasons.map(esc).join('<br>'):'修改保存在本机；已同步的飞书记录需要在飞书中另行修改。'}</p><form id="review-form"><label>分类<select id="review-skill">${Object.entries(names).map(([k,n])=>`<option value="${k}" ${skill(item)===k?'selected':''}>${n}</option>`).join('')}</select></label><label>标题<input id="review-title" maxlength="160" required value="${esc(item.title)}"></label><div id="event-dates" class="date-row"><label>开始时间<input id="review-start" type="datetime-local" value="${esc((item.start_at||'').slice(0,16))}"></label><label>结束时间<input id="review-end" type="datetime-local" value="${esc((item.end_at||'').slice(0,16))}"></label></div><label id="task-date">截止时间（原图没有要求可留空）<input id="review-due" type="datetime-local" value="${esc((item.due_at||'').slice(0,16))}"></label><label>地点<input id="review-location" value="${esc(item.location)}"></label><label>备注<textarea id="review-notes" rows="4">${esc(item.notes)}</textarea></label><div class="buttons">${review?'<button type="button" id="review-ignore">忽略此事项</button>':''}<button type="submit" class="primary">确认并保存</button></div></form>${original}`;
 const toggle=()=>{$('event-dates').hidden=$('review-skill').value!=='event';$('task-date').hidden=kinds[$('review-skill').value]!=='task';};$('review-skill').onchange=toggle;toggle();
 $('review-form').onsubmit=async e=>{e.preventDefault();const button=e.submitter;button.disabled=true;try{const selected=$('review-skill').value;const d=id=>$(id).value?$(id).value+':00+08:00':'';await api(review?'/api/agent/review':'/api/items/'+item.id+'/update',{id:review?.id,action:'edit',fields:{kind:kinds[selected],skill:selected,title:$('review-title').value,start_at:d('review-start'),end_at:d('review-end'),due_at:d('review-due'),location:$('review-location').value,notes:$('review-notes').value}});$('detail').close();await refresh();toast('已保存');}catch(e){toast(e.message);}finally{button.disabled=false;}};
 if(review)on('review-ignore',async()=>{await api('/api/image-jobs/'+review.id,{action:'cancel'});$('detail').close();await refresh();});
 }else{
 $('detail-content').innerHTML=`<p class="badge">${names[skill(item)]}${item.status==='completed'?' · 已完成':''}</p><h2>${esc(item.title)}</h2><p>${esc(dateText(item.start_at||item.due_at))}${item.end_at?' — '+esc(dateText(item.end_at)):''}${item.location?' · '+esc(item.location):''}</p>${data.course?`<p>课程：${esc(data.course)}</p>`:''}<div class="notes">${esc(item.notes)}</div>${steps.length?'<h3>执行清单</h3><ol>'+steps.map(s=>`<li>${esc(s)}</li>`).join('')+'</ol>':''}<p class="error">${esc(item.sync_error)}</p><div class="buttons"><button id="edit-item">编辑</button>${item.kind==='event'?`<a class="link" href="/api/items/${item.id}/calendar">导出到日历</a>`:''}${item.kind!=='bookmark'&&item.sync_state!=='synced'&&item.status==='active'?'<button id="sync-item">同步飞书</button>':''}${item.status==='active'?'<button id="complete-item">'+(item.kind==='bookmark'?'标记已读':'标记完成')+'</button>':''}</div>${item.sync_state==='synced'?'<p class="hint">已同步到飞书；本地修改不回写飞书。</p>':''}${original}`;
 on('edit-item',()=>detail(item.id,false,true));
 if($('complete-item'))on('complete-item',async()=>{await api('/api/items/'+item.id+'/update',{action:'complete'});$('detail').close();await refresh();});
 if($('sync-item'))on('sync-item',async()=>{feishu=await api('/api/feishu/status');const target=item.kind==='task'?feishu.task_target:feishu.sync_target;if(!target){$('detail').close();await openSettings();throw Error('请先连接对应的飞书任务或日历。');}if(!confirm(`将「${item.title}」同步到${item.kind==='task'?feishu.task_user_name+'的飞书任务':feishu.calendar_name}？${item.sync_state==='uncertain'?'上次结果不确定，请先在飞书核对。':''}`))return;await api('/api/items/'+item.id+'/sync',{confirmed:true,expected_target:target});$('detail').close();await refresh();toast('已同步飞书');});
 }
 $('detail').showModal();
}
async function init(){
 document.querySelectorAll('[data-close]').forEach(b=>b.onclick=()=>$(b.dataset.close).close());
 on('settings-open',openSettings);on('pick-folder',pick);on('change-folder',pick);on('browse-folder',browseFolder);
 on('folder-home',()=>browseFolder(''));on('folder-up',()=>browseFolder(folderParent||''));
 $('folder-list').onclick=e=>{const button=e.target.closest('[data-folder]');if(button)browseFolder(button.dataset.folder);};
 $('folder-input').addEventListener('input',()=>{folderGeneration++;candidate=null;$('folder-list').setAttribute('aria-busy','false');});
 $('consent').addEventListener('close',()=>folderGeneration++);
 on('pause-source',async()=>{const source=state.sources.find(s=>s.enabled)||state.sources[0];await api('/api/agent/source',{id:source.id,action:source.enabled?'pause':'resume'});await refresh();});
 $('consent-form').onsubmit=async e=>{
  e.preventDefault();e.submitter.disabled=true;folderGeneration++;$('folder-error').textContent='正在检查文件夹并保存授权…';
  try{
   const path=$('folder-input').value.trim();
   if(!candidate||candidate.path!==path)candidate=await api('/api/agent/folder-path',{path});
   await api('/api/agent/authorize',{token:candidate.token,confirmed:true,include_existing:$('include-existing').checked});
   $('consent').close();if($('settings').open)$('settings').close();await refresh();
   if(config.vision)toast('已授权，开始自动整理');
   else{await openSettings();$('vision-details').open=true;toast('文件夹已保存，连接识别服务后会自动整理');}
  }catch(e){$('folder-error').textContent=e.message;toast(e.message);}finally{e.submitter.disabled=false;}
 };
 on('upload-open',()=>{$('upload-dialog').showModal();});
 on('upload-start',async()=>{const files=[...$('files').files];if(!files.length||files.length>30)throw Error('请选择 1～30 张截图。');if(files.some(f=>f.size>8*1024*1024))throw Error('单张图片不能超过 8 MB。');let count=0,duplicates=0;for(const file of files){const image=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result);reader.onerror=()=>reject(Error('无法读取图片'));reader.readAsDataURL(file);});const result=await api('/api/agent/upload',{confirmed:true,image,filename:file.name});if(result.duplicate)duplicates++;count++;$('upload-progress').textContent=`已接收 ${count}/${files.length} 张${duplicates?'，跳过重复 '+duplicates+' 张':''}`;}await refresh();$('files').value='';toast('已开始整理，结果会自动出现');});
 $('filters').onclick=e=>{const b=e.target.closest('[data-filter]');if(b){filter=b.dataset.filter;render();}};
 $('search').oninput=render;$('cards').onclick=e=>{const b=e.target.closest('[data-detail]');if(b)detail(b.dataset.detail,b.dataset.review==='1');};
 $('activity').onclick=async e=>{const b=e.target.closest('button');if(!b)return;b.disabled=true;try{if(b.dataset.retry&&!confirm('重新识别会再次调用模型，确认重试？'))return;await api('/api/image-jobs/'+(b.dataset.retry||b.dataset.dismiss),{action:b.dataset.retry?'retry':'cancel'});await refresh();}catch(e){toast(e.message);}finally{b.disabled=false;}};
 $('source-settings').onclick=async e=>{const b=e.target.closest('[data-source]');if(!b)return;try{await api('/api/agent/source',{id:b.dataset.source,action:b.dataset.action});await refresh();await openSettings();toast(b.dataset.action==='revoke'?'已撤销文件夹授权，已有结果保留':'已更新');}catch(e){toast(e.message);}};
 on('save-skills',async()=>{await api('/api/agent/settings',{skills:[...document.querySelectorAll('[data-skill]:checked')].map(i=>i.dataset.skill),daily_limit:Number($('daily-limit').value)});await refresh();toast('处理设置已保存');});
 on('save-vision',async()=>{config=await api('/api/vision/configure',{base_url:$('vision-base').value,api_key:$('vision-key').value,model:$('vision-model').value});$('vision-key').value='';await openSettings();await refresh();toast('识别服务配置已保存');});
 on('save-feishu-app',async()=>{await api('/api/feishu/configure',{app_id:$('feishu-app-id').value,app_secret:$('feishu-app-secret').value});$('feishu-app-secret').value='';await openSettings();toast('应用配置已保存');});
 on('feishu-connect',async()=>{const result=await api('/api/feishu/connect',{});const url=new URL(result.url);if(url.protocol!=='https:'||url.hostname!=='accounts.feishu.cn')throw Error('授权地址无效');location.href=url.href;});
 on('feishu-disconnect',async()=>{await api('/api/feishu/disconnect',{});await api('/api/agent/settings',{sync_events:false,sync_tasks:false});await refresh();await openSettings();});
 on('load-calendars',async()=>{const calendars=await api('/api/feishu/calendars',{});$('calendar-select').innerHTML=calendars.map(c=>`<option value="${esc(c.id)}">${esc(c.name)}</option>`).join('');$('calendar-select-wrap').hidden=false;if(!calendars.length)throw Error('没有可写入的日历，请检查飞书权限。');});
 on('save-calendar',async()=>{await api('/api/feishu/select',{calendar_id:$('calendar-select').value});await openSettings();toast('日历已连接');});
 on('connect-tasks',async()=>{await api('/api/feishu/tasks-connect',{});await openSettings();toast('我的飞书任务已连接');});
 on('save-sync',async()=>{await api('/api/agent/settings',{sync_events:$('sync-events').checked,sync_tasks:$('sync-tasks').checked,calendar_target:feishu.sync_target,task_target:feishu.task_target});await refresh();toast('同步授权已保存，只对之后保存的事项生效');});
 config=await api('/api/config');await refresh();$('startup-status').hidden=true;
 const query=new URLSearchParams(location.search);if(query.has('feishu')){await openSettings();toast(query.get('feishu')==='connected'?'飞书已授权，请选择日历并连接任务':query.get('message')||'飞书授权未完成');history.replaceState({},'', '/');}
 setInterval(()=>refresh().catch(()=>{$('source-error').textContent='本机服务未连接，请重新打开 Windows 启动程序。';}),3500);
}
init().catch(e=>{const banner=$('startup-status');banner.hidden=false;banner.textContent='页面连接失败：'+e.message+'。请查看启动窗口，修复后按 Ctrl+F5 刷新。';toast('启动失败：'+e.message);});
