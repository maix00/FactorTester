(() => {
  let progressAbort = null;
  const text = value => value == null ? "" : String(value);
  const scalar = value => value == null || ["string", "number", "boolean"].includes(typeof value);
  const date = value => value ? FTUI.formatDate(value) : "";

  function table(headers, rows) {
    return FTUI.table(headers, rows);
  }

  function statusTitle(value, context) {
    const title = {
      succeeded: "成功", failed: "失败", running: "运行中", queued: "排队中",
      planning: "规划中", cancelled: "已取消", paused: "已暂停",
    }[value];
    return title ? context.t(title) : value || context.t("未知");
  }

  function kindTitle(value, context) {
    const title = {
      ic: "IC 测试", ic_test: "IC 测试", "ic-test": "IC 测试",
      backtest: "回测", group_backtest: "回测", test: "测试",
    }[String(value || "").toLowerCase()];
    return title ? context.t(title) : value || context.t("测试");
  }

  function jobPort(value) {
    const port = Number(value);
    return Number.isInteger(port) && port > 0 ? port : null;
  }

  function displayProfile(job, context) {
    const profile = job.server_context?.profile || job.profile || "";
    const owner = job.owner || job.server_context?.owner || "";
    if (owner && profile) return `${owner}（${profile}）`;
    return profile || owner || context.t("未知");
  }

  async function list(context) {
    stopProgress();
    context.activeNav("jobs"); context.setHeading(context.t("测试任务"));
    context.content.replaceChildren(FTUI.loading(context.t("正在读取跨端口任务…")));
    const jobs = (await context.api("/api/jobs?limit=20&port=all")).jobs || [];
    if (!jobs.length) {
      context.content.replaceChildren(FTUI.empty(
        context.t("暂无测试任务"),
        context.t("Web、CLI 与研究 Agent 提交的任务都会在这里显示"),
      ));
      return;
    }
    const result = table([context.t("任务"), context.t("端口"), context.t("时间"), context.t("状态"), context.t("Profile"), context.t("生成物")], jobs.map(job => [
      `${kindTitle(job.kind, context)} · ${job.job_id}`, jobPort(job.port) || context.t("未知"), date(job.updated_at), statusTitle(job.status, context), displayProfile(job, context), job.artifact_count || 0,
    ]));
    [...result.body.rows].forEach((row, index) => {
      const job = jobs[index]; row.dataset.href = "true";
      const port = jobPort(job.port);
      const path = port ? `/jobs/${port}/${encodeURIComponent(job.job_id)}` : `/jobs/${encodeURIComponent(job.job_id)}`;
      row.addEventListener("click", () => context.navigate(path));
    });
    context.content.replaceChildren(result.shell);
  }

  function fieldSection(context, title, value) {
    const section = document.createElement("section"); section.className = "job-section";
    const heading = document.createElement("h2"); heading.textContent = title; section.append(heading);
    const entries = Object.entries(value || {}).filter(([, item]) => scalar(item));
    if (entries.length) {
      const result = table([context.t("字段"), context.t("值")], entries.map(([key, item]) => [key, item]));
      result.shell.classList.add("field-table"); section.append(result.shell);
    }
    const residual = Object.fromEntries(Object.entries(value || {}).filter(([, item]) => !scalar(item)));
    if (Object.keys(residual).length) section.append(code(JSON.stringify(residual, null, 2)));
    return section;
  }

  function code(value) {
    const pre = document.createElement("pre"); pre.className = "json-code"; pre.textContent = text(value); return pre;
  }

  function collapsible(title, content, open = false) {
    const details = document.createElement("details"); details.className = "result-section"; details.open = open;
    const summary = document.createElement("summary"); summary.textContent = title; details.append(summary, content); return details;
  }

  function artifactRows(context, artifacts, onOpen) {
    const result = table([context.t("中文说明"), context.t("原文件名"), context.t("文件大小")], []);
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
    stopProgress();
    context.activeNav("jobs"); context.setHeading(context.t("测试任务详情"));
    context.content.replaceChildren(FTUI.loading(context.t("正在读取任务详情…")));
    const selectedPort = jobPort(port);
    const portQuery = selectedPort ? `?port=${selectedPort}` : "";
    const payload = await context.api(`/api/jobs/${encodeURIComponent(jobID)}${portQuery}`);
    const taskDetail = payload.task_detail || payload;
    const job = taskDetail.job || payload;
    const artifacts = taskDetail.artifacts || [];
    context.setHeading(kindTitle(job.kind, context), jobID);
    context.toolbar.append(context.button("↻", () => detailPage(), context.t("刷新详情")));
    if (artifacts.some(item => item.state === "active")) {
      if (context.session) {
        context.toolbar.append(context.button("⇩", () => downloadAllArtifacts(context, activeArtifactList(), jobID, portQuery), context.t("下载全部生成物")));
        context.toolbar.append(context.button("⌫", () => clearArtifacts(context, portQuery, jobID), context.t("清空生成物")));
      }
    }
    const root = document.createElement("div"); root.className = "job-detail";
    const progress = progressView(context, job.status);
    root.append(progress.root);
    root.append(fieldSection(context, context.t("任务字段"), {...job, port}));
    root.append(fieldSection(context, context.t("测试配置"), taskDetail.configuration || {}));
    if (taskDetail.research_binding) root.append(fieldSection(context, context.t("研究绑定"), taskDetail.research_binding));
    if (taskDetail.caller || taskDetail.submission_context) root.append(fieldSection(context, context.t("调用方"), taskDetail.caller || taskDetail.submission_context));
    const declarations = taskDetail.output_declarations || [];
    if (declarations.length) root.append(fieldSection(context, context.t("结果展示声明"), Object.fromEntries(declarations.map(item => [item.label || item.name, `${item.presentation || "data"} · ${item.viewer || "json"}`]))));
    const results = taskDetail.results || payload.result_summary || payload.result;
    const activeArtifacts = artifacts.filter(item => item.state === "active");
    declarations.forEach(declaration => {
      const artifact = declarationArtifact(declaration, activeArtifacts);
      if (artifact) root.append(lazyArtifactPreview(context, declaration, artifact, jobID, portQuery));
    });
    if (results != null) {
      const resultBody = code(JSON.stringify(results, null, 2));
      root.append(collapsible(context.t("结果预览"), resultBody));
    }
    const artifactSection = document.createElement("section"); artifactSection.className = "job-section";
    const artifactTitle = document.createElement("h2"); artifactTitle.textContent = context.t("生成物"); artifactSection.append(artifactTitle);
    if (artifacts.some(item => item.state === "active")) artifactSection.append(artifactRows(context, artifacts, item => {
      if (!context.session) return context.openLogin(context.t("登录后才能下载生成物"));
      return saveBlob(context, `/api/jobs/${encodeURIComponent(jobID)}/artifacts/${encodeURIComponent(item.name)}${portQuery}`, item.file_name || item.name);
    }));
    else artifactSection.append(Object.assign(document.createElement("p"), {textContent: context.t("暂无生成物")}));
    root.append(artifactSection); context.content.replaceChildren(root);
    if (["queued", "planning", "running", "paused"].includes(job.status)) {
      watchProgress(context, jobID, portQuery, progress);
    }

    async function detailPage() { return window.FTJobs.detail(context, port, jobID); }
    function activeArtifactList() { return artifacts.filter(item => item.state === "active"); }
  }

  function progressView(context, status) {
    const root = document.createElement("section"); root.className = "job-progress job-section";
    const heading = document.createElement("h2"); heading.textContent = context.t("任务进度");
    const bar = document.createElement("progress"); bar.max = 100;
    const label = document.createElement("span"); label.textContent = statusTitle(status, context);
    root.append(heading, bar, label);
    if (status === "succeeded") bar.value = 100;
    else if (!["running", "planning"].includes(status)) bar.value = 0;
    return {root, bar, label};
  }

  function updateProgress(view, payload) {
    const source = payload?.latest_progress?.data || payload?.data || payload || {};
    const completed = Number(source.completed); const total = Number(source.total);
    const percent = Number.isFinite(Number(source.percent)) ? Number(source.percent)
      : Number.isFinite(completed) && Number.isFinite(total) && total > 0 ? completed / total * 100 : null;
    if (percent != null) view.bar.value = Math.max(0, Math.min(100, percent));
    else view.bar.removeAttribute("value");
    const phase = source.phase || payload?.status || "";
    const count = Number.isFinite(completed) && Number.isFinite(total) && total > 0 ? ` · ${completed}/${total}` : "";
    view.label.textContent = `${phase}${count}${percent == null ? "" : ` · ${percent.toFixed(1)}%`}`;
  }

  async function watchProgress(context, jobID, portQuery, view) {
    const controller = new AbortController(); progressAbort = controller;
    try {
      const response = await context.raw(`/api/jobs/${encodeURIComponent(jobID)}/stream${portQuery}`, {signal: controller.signal});
      const reader = response.body.getReader(); const decoder = new TextDecoder(); let buffer = "";
      while (!controller.signal.aborted) {
        const {done, value} = await reader.read(); if (done) break;
        buffer += decoder.decode(value, {stream: true});
        const frames = buffer.split(/\r?\n\r?\n/); buffer = frames.pop() || "";
        frames.forEach(frame => {
          const data = frame.split(/\r?\n/).filter(line => line.startsWith("data:"))
            .map(line => line.slice(5).trim()).join("\n");
          if (!data) return;
          try { updateProgress(view, JSON.parse(data)); } catch (_) {}
        });
      }
    } catch (error) {
      if (error.name !== "AbortError") view.label.textContent = context.t("实时进度暂不可用");
    }
  }

  function stopProgress() { progressAbort?.abort(); progressAbort = null; }

  async function clearArtifacts(context, portQuery, jobID) {
    await context.api(`/api/jobs/${encodeURIComponent(jobID)}/artifacts${portQuery}`, {method: "DELETE"});
    return window.FTJobs.detail(context, Number(new URLSearchParams(portQuery.slice(1)).get("port") || 0), jobID);
  }

  async function downloadAllArtifacts(context, artifacts, jobID, portQuery) {
    let directory = null;
    if (window.showDirectoryPicker) {
      directory = await window.showDirectoryPicker({mode: "readwrite"});
    }
    for (const artifact of artifacts) {
      const fileName = artifact.file_name || artifact.name;
      const path = `/api/jobs/${encodeURIComponent(jobID)}/artifacts/${encodeURIComponent(artifact.name)}${portQuery}`;
      if (!directory) {
        await saveBlob(context, path, fileName);
        continue;
      }
      const response = await context.raw(path);
      const handle = await directory.getFileHandle(fileName, {create: true});
      const writable = await handle.createWritable();
      await writable.write(await response.blob());
      await writable.close();
    }
  }

  function declarationArtifact(declaration, artifacts) {
    const names = declaration.artifacts || [];
    return artifacts.find(item => names.includes(item.name)) || artifacts.find(item => {
      const viewer = String(declaration.viewer || "").toLowerCase();
      const type = String(item.content_type || "").toLowerCase();
      return viewer.includes("image") ? type.startsWith("image/")
        : viewer.includes("table") || viewer.includes("order") ? type.includes("csv") || type.includes("json")
        : viewer.includes("price") || viewer.includes("kline") ? type.includes("json") : false;
    });
  }

  function lazyArtifactPreview(context, declaration, artifact, jobID, portQuery) {
    const target = document.createElement("div"); target.className = "artifact-preview";
    const details = collapsible(declaration.label || declaration.name, target);
    let loaded = false;
    details.addEventListener("toggle", async () => {
      if (!details.open || loaded) return; loaded = true;
      try {
        await FTJobArtifactViewers.mount(context, target, {declaration, artifact, jobID, portQuery});
      } catch (error) {
        target.textContent = error.message;
      }
    });
    return details;
  }

  window.FTJobs = {list, detail};
})();
