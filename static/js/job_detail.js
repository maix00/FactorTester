(function () {
  const root = document.getElementById('job-detail');
  const jobId = root.dataset.jobId;
  const api = async (url, options) => {
    const response = await fetch(url, options);
    const body = await response.json();
    if (!response.ok || body.success === false) throw new Error(body.error || ('HTTP ' + response.status));
    return body;
  };
  const text = (value) => String(value == null || value === '' ? '—' : value);
  async function load() {
    try {
      const [job, artifacts] = await Promise.all([api('/api/jobs/' + encodeURIComponent(jobId)), api('/api/jobs/' + encodeURIComponent(jobId) + '/artifacts')]);
      root.replaceChildren();
      const heading = document.createElement('h2'); heading.textContent = text(job.kind) + ' · ' + text(job.status); root.appendChild(heading);
      const meta = document.createElement('p'); meta.textContent = 'Job=' + jobId + ' · 端口=' + text(job.port || (job.server_context || {}).port) + ' · workspace=' + text(job.workspace_id) + ' · profile=' + text((job.server_context || {}).profile); root.appendChild(meta);
      const config = document.createElement('details'); config.open = true; const summary = document.createElement('summary'); summary.textContent = '配置与输出声明'; config.appendChild(summary); const pre = document.createElement('pre'); pre.textContent = JSON.stringify({run_spec_hash: job.run_spec_hash, output_requests: job.output_requests, research_binding: job.research_binding, configuration: job.configuration}, null, 2); config.appendChild(pre); root.appendChild(config);
      const files = document.createElement('section'); const title = document.createElement('h3'); title.textContent = '生成物'; files.appendChild(title); (artifacts.artifacts || []).filter(item => item.state === 'active').forEach(item => { const row = document.createElement('p'); row.textContent = (item.description || item.name) + ' · ' + text(item.size_bytes) + ' bytes · 请通过 Manager 7998 下载'; files.appendChild(row); }); root.appendChild(files);
    } catch (error) { root.textContent = error.message || String(error); }
  }
  load();
})();
