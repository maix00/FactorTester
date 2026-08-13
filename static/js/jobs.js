(function () {
  const jobsEl = document.getElementById('jobs');
  const storageEl = document.getElementById('storage');
  const active = new Set();
  const esc = (value) => String(value == null ? '' : value);
  async function api(url, options, origin='') {
    const response = await fetch(origin + url, {...(options || {}), credentials:'include'});
    const body = await response.json();
    if (!response.ok || body.success === false) throw new Error(body.error || ('HTTP ' + response.status));
    return body;
  }
  function statusLabel(status) { return ({succeeded:'成功',failed:'失败',cancelled:'已取消',running:'运行中',paused:'已暂停',queued:'排队中',planning:'规划中',submitted:'已提交',awaiting_confirmation:'待确认'})[status] || status; }
  function card(job) {
    const card = document.createElement('article'); card.className='job-card'; card.dataset.jobId=job.job_id;
    const binding = job.research_binding || {}; const context = job.server_context || {};
    const head = document.createElement('div'); head.className='job-head';
    const info = document.createElement('div'); info.innerHTML = '<div class="job-title"></div><div class="job-meta"></div>';
    info.querySelector('.job-title').textContent = job.kind + ' · ' + statusLabel(job.status) + ' · ' + job.job_id;
    info.querySelector('.job-meta').textContent = 'workspace=' + (job.workspace_id || '—') + ' · port=' + (job.port || context.port || '—') + ' · profile=' + (context.profile || 'default') + (binding.work_package_ref ? ' · 研究工作=' + binding.work_package_ref : '');
    const origin = job.__origin || '';
    const actions = document.createElement('div'); actions.className='job-actions';
    const details = document.createElement('a'); details.textContent='查看配置/生成物'; details.href=origin+'/jobs/'+encodeURIComponent(job.job_id); actions.appendChild(details);
    const clear = document.createElement('button'); clear.textContent='清空该任务'; clear.onclick=async()=>{ await api('/api/jobs/'+encodeURIComponent(job.job_id)+'/artifacts',{method:'DELETE'},origin); await load(); }; actions.appendChild(clear);
    head.append(info, actions); card.appendChild(head);
    const progress = document.createElement('div'); progress.className='progress'; progress.innerHTML='<i></i>'; card.appendChild(progress);
    const label = document.createElement('div'); label.className='progress-label'; label.textContent='状态：'+statusLabel(job.status); card.appendChild(label);
    if (['submitted','planning','queued','running','paused','awaiting_confirmation'].includes(job.status)) watch(job, progress, label);
    return card;
  }
  async function watch(job, progress, label) {
    if (active.has(job.job_id)) return; active.add(job.job_id);
    try { const response=await fetch((job.__origin||'')+'/api/jobs/'+encodeURIComponent(job.job_id)+'/stream',{credentials:'include'}); if(!response.ok) return; const reader=response.body.getReader(); const decoder=new TextDecoder(); let buffer=''; let event='';
      while(true){ const chunk=await reader.read(); if(chunk.done) break; buffer+=decoder.decode(chunk.value,{stream:true}); const lines=buffer.split('\n'); buffer=lines.pop(); for(const line of lines){ if(line.startsWith('event: ')) event=line.slice(7).trim(); if(!line.startsWith('data: ')) continue; let data={}; try{data=JSON.parse(line.slice(6));}catch(e){continue;} if(event==='progress'||event==='signal_progress'){ const total=Number(data.total||0), done=Number(data.completed||0); progress.firstElementChild.style.width=(total?Math.min(100,done/total*100):Number(data.percent||0))+'%'; label.textContent=data.message||data.phase||event; } if(event==='result'||event==='error'){ label.textContent=event==='result'?'成功':(data.error||'失败'); await load(); return; } } }
    } catch(e) { label.textContent='进度暂不可用：'+e.message; } finally { active.delete(job.job_id); }
  }
  function portState(){ const current=Number(location.port||0); const saved=JSON.parse(localStorage.getItem('factortester.jobPorts')||'[]'); return [...new Set([current,...saved].filter(x=>x>0))].sort((a,b)=>a-b); }
  function originFor(port){ const current=Number(location.port||0); if(port===current) return ''; return location.protocol+'//'+location.hostname+':'+port; }
  function renderPorts(){ const list=document.getElementById('port-list'); list.replaceChildren(); portState().forEach(port=>{ const link=document.createElement('a'); link.href=originFor(port)+'/jobs'; link.textContent='端口 '+port+(Number(location.port||0)===port?'（当前）':''); list.appendChild(link); }); }
  async function load(){ try { renderPorts(); const rows=[]; for(const port of portState()){ const origin=originFor(port); const data=await api('/api/jobs?limit=100',undefined,origin); (data.jobs||[]).forEach(job=>{ job.__origin=origin; rows.push(job); }); } rows.sort((a,b)=>Number(b.updated_at||0)-Number(a.updated_at||0)); jobsEl.replaceChildren(); rows.forEach(job=>jobsEl.appendChild(card(job))); const storage=await api('/api/jobs/storage'); storageEl.textContent='当前端口服务器空间：'+Math.round(storage.usage_bytes/1048576)+' / '+Math.round(storage.quota_bytes/1048576)+' MiB'; } catch(e){ jobsEl.textContent=e.message||String(e); } }
  document.getElementById('add-port').onclick=()=>{ const port=Number(document.getElementById('port-input').value); if(!port) return; const values=portState().filter(x=>x!==Number(location.port||0)); values.push(port); localStorage.setItem('factortester.jobPorts',JSON.stringify(values)); renderPorts(); location.href=location.protocol+'//'+location.hostname+':'+port+'/jobs'; };
  document.getElementById('refresh').onclick=load;
  document.getElementById('clear-all').onclick=async()=>{ if(confirm('清空当前用户全部 Job 生成物？')){ await api('/api/jobs/artifacts',{method:'DELETE'}); await load(); } };
  load();
})();
