'use strict';
const key='snapflow:two-day-checklist:20260914';
let saved={};try{saved=JSON.parse(localStorage.getItem(key)||'{}');}catch{}
const boxes=[...document.querySelectorAll('[data-step]')];
const notes=document.getElementById('notes');notes.value=typeof saved.notes==='string'?saved.notes:'';
for(const box of boxes){box.checked=saved.steps?.[box.dataset.step]===true;box.addEventListener('change',persist);}
notes.addEventListener('input',persist);
function value(){return{date:new Date().toISOString(),steps:Object.fromEntries(boxes.map(b=>[b.dataset.step,b.checked])),notes:notes.value,kind:'user-reported acceptance checklist; not automated test evidence'};}
function persist(){const n=boxes.filter(b=>b.checked).length;document.getElementById('progress').value=n;document.getElementById('progress-label').textContent=`已完成 ${n} / ${boxes.length} 步`;try{localStorage.setItem(key,JSON.stringify(value()));}catch{}}
persist();
document.getElementById('check').onclick=async()=>{const b=document.getElementById('check');b.disabled=true;try{const responses=await Promise.all([fetch('/api/config'),fetch('/api/feishu/status')]);if(responses.some(r=>!r.ok))throw new Error('本机服务未返回有效状态');const [c,f]=await Promise.all(responses.map(r=>r.json()));document.getElementById('status').textContent=`模型：${c.vision?'已配置（不代表本次已测试）':'未配置'}\n飞书应用：${f.configured?'已配置':'未配置'}\n账号：${f.authorized?'已授权':'未授权'}\n目标日历：${f.calendar_name||'未选择个人日历'}\n当前目标的创建成功记录：${f.successful_events||0} 条\n提醒是否送达：需要你在飞书与设备上核对。`;}catch(e){document.getElementById('status').textContent=e.message;}finally{b.disabled=false;}};
document.getElementById('export').onclick=()=>{const url=URL.createObjectURL(new Blob([JSON.stringify(value(),null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='SnapFlow-我的两天验收记录.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
