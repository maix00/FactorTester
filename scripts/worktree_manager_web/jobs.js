(() => {
  const text = value => value == null ? "" : String(value);
  const scalar = value => value == null || ["string", "number", "boolean"].includes(typeof value);
  const date = value => value ? new Date(Number(value) * 1000).toLocaleString() : "";

  function table(headers, rows) {
    const shell = document.createElement("div"); shell.className = "table-shell";
    const element = document.createElement("table");
    const head = element.createTHead().insertRow();
    headers.forEach(value => { const cell = document.createElement("th"); cell.textContent = value; head.append(cell); });
    const body = element.createTBody();
    rows.forEach(values => {
      const row = body.insertRow();
      values.forEach(value => { const cell = row.insertCell(); cell.textContent = text(value); });
    });
    shell.append(element); return {shell, body};
  }

  function statusTitle(value) {
    return {succeeded: "成功", failed: "失败", running: "运行中", queued: "排队中", cancelled: "已取消", paused: "已暂停"}[value] || value || "未知";
  }

  async function list(context) {
    context.activeNav("jobs"); context.setHeading("测试任务");
    context.content.innerHTML = '<div class="empty"><p>正在读取跨端口任务…</p></div>';
    const jobs = (await context.api("/api/jobs?limit=200&port=all")).jobs || [];
    if (!jobs.length) {
      context.content.innerHTML = '<div class="empty"><h2>暂无测试任务</h2><p>Web、CLI 与研究 Agent 提交的任务都会在这里显示</p></div>';
      return;
    }
    const result = table(["端口", "任务", "类型", "状态", "Profile", "更新时间"], jobs.map(job => [
      job.port, job.job_id, job.kind || "test", statusTitle(job.status), job.server_context?.profile || job.profile || "", date(job.updated_at),
    ]));
    [...result.body.rows].forEach((row, index) => {
      const job = jobs[index]; row.dataset.href = "true";
      row.addEventListener("click", () => context.navigate(`/jobs/${job.port}/${encodeURIComponent(job.job_id)}`));
    });
    context.content.replaceChildren(result.shell);
  }

  function fieldSection(title, value) {
    const section = document.createElement("section"); section.className = "job-section";
    const heading = document.createElement("h2"); heading.textContent = title; section.append(heading);
    const entries = Object.entries(value || {}).filter(([, item]) => scalar(item));
    if (entries.length) {
      const result = table(["字段", "值"], entries.map(([key, item]) => [key, item]));
      result.shell.classList.add("field-table"); section.append(result.shell);
    }
    const residual = Object.fromEntries(Object.entries(value || {}).filter(([, item]) => !scalar(item)));
    if (Object.keys(residual).length) section.append(code(JSON.stringify(residual, null, 2)));
    return section;
  }

  function code(value) {
    const pre = document.createElement("pre"); pre.textContent = text(value); return pre;
  }

  function collapsible(title, content, open = false) {
    const details = document.createElement("details"); details.className = "result-section"; details.open = open;
    const summary = document.createElement("summary"); summary.textContent = title; details.append(summary, content); return details;
  }

  function artifactRows(artifacts, onOpen) {
    const result = table(["中文说明", "原文件名", "文件大小"], []);
    artifacts.filter(item => item.state === "active").forEach(item => {
      const row = result.body.insertRow();
      const description = row.insertCell(); description.textContent = item.description || item.name;
      const file = row.insertCell();
      const link = document.createElement("a"); link.href = "#"; link.textContent = item.file_name || item.name;
      link.addEventListener("click", event => { event.preventDefault(); onOpen(item); }); file.append(link);
      const size = row.insertCell(); size.textContent = formatBytes(item.size_bytes || 0);
    });
    return result.shell;
  }

  function formatBytes(value) {
    if (value < 1024) return `${value} B`;
    if (value < 1024 ** 2) return `${(value / 1024).toFixed(1)} KiB`;
    return `${(value / 1024 ** 2).toFixed(1)} MiB`;
  }

  async function saveBlob(context, path, fileName) {
    const response = await context.raw(path);
    const blob = await response.blob();
    const url = URL.createObjectURL(blob); const anchor = document.createElement("a");
    anchor.href = url; anchor.download = fileName; document.body.append(anchor); anchor.click(); anchor.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  async function detail(context, port, jobID) {
    context.activeNav("jobs"); context.setHeading("测试任务详情");
    context.content.innerHTML = '<div class="empty"><p>正在读取任务详情…</p></div>';
    const portQuery = port > 0 ? `?port=${port}` : "";
    const payload = await context.api(`/api/jobs/${encodeURIComponent(jobID)}${portQuery}`);
    const taskDetail = payload.task_detail || payload;
    const job = taskDetail.job || payload;
    const artifacts = taskDetail.artifacts || [];
    context.setHeading(job.kind || "测试任务", jobID);
    context.toolbar.append(context.button("↻", () => detailPage(), "刷新详情"));
    if (artifacts.some(item => item.state === "active")) {
      context.toolbar.append(context.button("⇩", () => saveBlob(context, `/api/jobs/${encodeURIComponent(jobID)}/artifacts/archive${portQuery}`, `job-${jobID}-artifacts.zip`), "下载全部生成物"));
    }
    const root = document.createElement("div"); root.className = "job-detail";
    root.append(fieldSection("任务字段", {...job, port}));
    root.append(fieldSection("测试配置", taskDetail.configuration || {}));
    if (taskDetail.research_binding) root.append(fieldSection("研究绑定", taskDetail.research_binding));
    if (taskDetail.caller || taskDetail.submission_context) root.append(fieldSection("调用方", taskDetail.caller || taskDetail.submission_context));
    const declarations = taskDetail.output_declarations || [];
    if (declarations.length) root.append(fieldSection("结果展示声明", Object.fromEntries(declarations.map(item => [item.label || item.name, `${item.presentation || "data"} · ${item.viewer || "json"}`]))));
    const results = taskDetail.results || payload.result_summary || payload.result;
    if (results != null) {
      const resultBody = code(JSON.stringify(results, null, 2));
      root.append(collapsible("结果预览", resultBody));
    }
    const artifactSection = document.createElement("section"); artifactSection.className = "job-section";
    const artifactTitle = document.createElement("h2"); artifactTitle.textContent = "生成物"; artifactSection.append(artifactTitle);
    if (artifacts.some(item => item.state === "active")) artifactSection.append(artifactRows(artifacts, item => saveBlob(context, `/api/jobs/${encodeURIComponent(jobID)}/artifacts/${encodeURIComponent(item.name)}${portQuery}`, item.file_name || item.name)));
    else artifactSection.append(Object.assign(document.createElement("p"), {textContent: "暂无生成物"}));
    root.append(artifactSection); context.content.replaceChildren(root);

    async function detailPage() { return window.FTJobs.detail(context, port, jobID); }
  }

  window.FTJobs = {list, detail};
})();
