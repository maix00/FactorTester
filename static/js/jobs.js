(function () {
  const jobsEl = document.getElementById('jobs');
  const storageEl = document.getElementById('storage');
  const active = new Set();
  const esc = (value) => String(value == null ? '' : value);
  async function api(url, options) {
    const response = await fetch(url, options);
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
    info.querySelector('.job-meta').textContent = 'workspace=' + (job.workspace_id || '—') + ' · port=' + (context.port || '—') + ' · profile=' + (context.profile || 'default') + ' · deployment=' + (context.deployment_id || '—') + (binding.work_package_ref ? ' · 研究工作=' + binding.work_package_ref : '');
    const actions = document.createElement('div'); actions.className='job-actions';
    const details = document.createElement('button'); details.textContent='查看配置/生成物'; actions.appendChild(details);
    const archive = document.createElement('a'); archive.textContent='一键下载'; archive.href='/api/jobs/'+encodeURIComponent(job.job_id)+'/artifacts/archive'; archive.download='job-'+job.job_id+'-artifacts.zip'; actions.appendChild(archive);
    const clear = document.createElement('button'); clear.textContent='清空该任务'; clear.onclick=async()=>{ await api('/api/jobs/'+encodeURIComponent(job.job_id)+'/artifacts',{method:'DELETE'}); await load(); }; actions.appendChild(clear);
    head.append(info, actions); card.appendChild(head);
    const progress = document.createElement('div'); progress.className='progress'; progress.innerHTML='<i></i>'; card.appendChild(progress);
    const label = document.createElement('div'); label.className='progress-label'; label.textContent='状态：'+statusLabel(job.status); card.appendChild(label);
    const detail = document.createElement('div'); detail.className='job-detail'; detail.hidden=true; card.appendChild(detail);
    details.onclick=async()=>{ detail.hidden=!detail.hidden; if(!detail.hidden) await showDetail(job, detail); };
    if (['submitted','planning','queued','running','paused','awaiting_confirmation'].includes(job.status)) watch(job, progress, label);
    return card;
  }
  async function showDetail(job, target) {
    target.textContent='读取中…';
    try { const detail=await api('/api/jobs/'+encodeURIComponent(job.job_id)); const artifacts=await api('/api/jobs/'+encodeURIComponent(job.job_id)+'/artifacts'); target.replaceChildren();
      const pre=document.createElement('pre'); pre.textContent=JSON.stringify({run_spec_hash:detail.run_spec_hash,output_requests:detail.output_requests,server_context:detail.server_context,research_binding:detail.research_binding,configuration:detail.configuration},null,2); target.appendChild(pre);
      (artifacts.artifacts||[]).filter(x=>x.state==='active').forEach(item=>{ const row=document.createElement('div'); row.className='artifact'; const link=document.createElement('a'); link.href='/api/jobs/'+encodeURIComponent(job.job_id)+'/artifacts/'+encodeURIComponent(item.name); link.download=item.name; link.textContent=(item.description||item.name||'artifact')+' · '+(item.name||'artifact')+' · '+(item.content_type||'file')+' · '+(item.size_bytes||0)+' bytes'; row.appendChild(link); target.appendChild(row); });
    } catch (error) { target.textContent=error.message||String(error); }
  }
  async function watch(job, progress, label) {
    if (active.has(job.job_id)) return; active.add(job.job_id);
    try { const response=await fetch('/api/jobs/'+encodeURIComponent(job.job_id)+'/stream'); if(!response.ok) return; const reader=response.body.getReader(); const decoder=new TextDecoder(); let buffer=''; let event='';
      while(true){ const chunk=await reader.read(); if(chunk.done) break; buffer+=decoder.decode(chunk.value,{stream:true}); const lines=buffer.split('\n'); buffer=lines.pop(); for(const line of lines){ if(line.startsWith('event: ')) event=line.slice(7).trim(); if(!line.startsWith('data: ')) continue; let data={}; try{data=JSON.parse(line.slice(6));}catch(e){continue;} if(event==='progress'||event==='signal_progress'){ const total=Number(data.total||0), done=Number(data.completed||0); progress.firstElementChild.style.width=(total?Math.min(100,done/total*100):Number(data.percent||0))+'%'; label.textContent=data.message||data.phase||event; } if(event==='result'||event==='error'){ label.textContent=event==='result'?'成功':(data.error||'失败'); await load(); return; } } }
    } catch(e) { label.textContent='进度暂不可用：'+e.message; } finally { active.delete(job.job_id); }
  }
  async function load(){ try { const data=await api('/api/jobs?limit=100'); jobsEl.replaceChildren(); (data.jobs||[]).forEach(job=>jobsEl.appendChild(card(job))); const storage=await api('/api/jobs/storage'); storageEl.textContent='服务器空间：'+Math.round(storage.usage_bytes/1048576)+' / '+Math.round(storage.quota_bytes/1048576)+' MiB'; } catch(e){ jobsEl.textContent=e.message||String(e); } }
  document.getElementById('refresh').onclick=load;
  document.getElementById('clear-all').onclick=async()=>{ if(confirm('清空当前用户全部 Job 生成物？')){ await api('/api/jobs/artifacts',{method:'DELETE'}); await load(); } };
  load();
})();
