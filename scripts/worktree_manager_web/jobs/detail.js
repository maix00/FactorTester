(() => {
  const {text, scalar, date, table, statusPill, kindTitle, jobPort} = FTJobs;

  function fieldSection(context, title, value) {
    const section = document.createElement("section"); section.className = "job-section";
    const heading = document.createElement("h2"); heading.textContent = title; section.append(heading);
    const entries = Object.entries(value || {}).filter(([, item]) => scalar(item));
    if (entries.length) {
      const result = table([context.t("字段"), context.t("值")], entries.map(([key, item]) => [key, fieldValue(context, key, item)]));
      result.shell.classList.add("field-table"); section.append(result.shell);
    }
    const residual = Object.fromEntries(Object.entries(value || {}).filter(([, item]) => !scalar(item)));
    if (Object.keys(residual).length) section.append(code(JSON.stringify(residual, null, 2)));
    return section;
  }

  function fieldValue(context, key, value) {
    if (key === "status") return statusPill(value, context);
    if (value != null && /(?:^|_)(?:at|time)$/.test(String(key).toLowerCase())) {
      const rendered = date(value);
      if (rendered) {
        const time = document.createElement("time");
        time.textContent = rendered;
        const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
        time.title = zone ? `${context.t("本地时间")}（${zone}）` : context.t("本地时间");
        const numeric = Number(value);
        const parsed = Number.isFinite(numeric)
          ? new Date(numeric < 10 ** 12 ? numeric * 1000 : numeric)
          : new Date(value);
        if (!Number.isNaN(parsed.valueOf())) time.dateTime = parsed.toISOString();
        return time;
      }
    }
    return text(value);
  }

  function code(value) {
    const pre = document.createElement("pre");
    pre.className = "json-code";
    pre.textContent = text(value);
    return pre;
  }

  async function detail(context, port, jobID) {
    const isCurrent = () => context.isRouteCurrent?.() !== false;
    if (!isCurrent()) return;
    FTJobProgress.stopProgress();
    context.activeNav("jobs"); context.setHeading(context.t("测试任务详情"));
    context.content.replaceChildren(FTUI.loading(context.t("正在读取任务详情…")));
    const selectedPort = jobPort(port);
    let portQuery = selectedPort ? `?port=${selectedPort}` : "";
    let payload;
    try {
      payload = await context.api(`/api/jobs/${encodeURIComponent(jobID)}${portQuery}`);
    } catch (error) {
      // Manager owns the cross-port lookup, so retry without a stale hint.
      if (!selectedPort) throw error;
      if (!isCurrent()) return;
      portQuery = "";
      payload = await context.api(`/api/jobs/${encodeURIComponent(jobID)}`);
    }
    if (!isCurrent()) return;
    const taskDetail = payload.task_detail || payload;
    const job = taskDetail.job || payload;
    const artifacts = taskDetail.artifacts || [];
    const jobTitle = `${kindTitle(job.kind, context)} · ${jobID}`;
    context.updateActiveTab?.({title: jobTitle});
    context.setHeading(jobTitle, context.t("测试任务详情"));
    context.toolbar.append(context.button("↻", () => detailPage(), context.t("刷新详情")));
    if (artifacts.some(item => item.state === "active") && context.session) {
      context.toolbar.append(context.button("⇩", () => FTJobArtifacts.downloadAllArtifacts(context, activeArtifactList(), jobID, portQuery), context.t("下载全部生成物")));
      context.toolbar.append(context.button("⌫", () => FTJobArtifacts.clearArtifacts(context, portQuery, jobID), context.t("清空生成物")));
    }
    const root = document.createElement("div"); root.className = "job-detail";
    const progress = FTJobProgress.progressView(context, job.status);
    root.append(progress.root);
    root.append(fieldSection(context, context.t("任务字段"), {...job, port}));
    root.append(fieldSection(context, context.t("测试配置"), taskDetail.configuration || {}));
    if (taskDetail.research_binding) root.append(fieldSection(context, context.t("研究绑定"), taskDetail.research_binding));
    if (taskDetail.caller || taskDetail.submission_context) root.append(fieldSection(context, context.t("调用方"), taskDetail.caller || taskDetail.submission_context));
    const declarations = FTJobArtifacts.effectiveDeclarations(taskDetail.output_declarations || [], artifacts, context);
    if (declarations.length) root.append(fieldSection(context, context.t("结果展示声明"), Object.fromEntries(declarations.map(item => [item.label || item.name, `${item.presentation || "data"} · ${item.viewer || "json"}`]))));
    const results = taskDetail.results || payload.result_summary || payload.result;
    const activeArtifacts = artifacts.filter(item => item.state === "active");
    declarations.forEach(declaration => {
      const artifact = FTJobArtifacts.declarationArtifact(declaration, activeArtifacts);
      if (artifact) root.append(FTJobArtifacts.lazyArtifactPreview(context, declaration, artifact, jobID, portQuery));
    });
    if (results != null) root.append(FTJobArtifacts.collapsible(context.t("结果预览"), code(JSON.stringify(results, null, 2))));
    const artifactSection = document.createElement("section"); artifactSection.className = "job-section";
    const artifactTitle = document.createElement("h2"); artifactTitle.textContent = context.t("生成物"); artifactSection.append(artifactTitle);
    if (artifacts.some(item => item.state === "active")) artifactSection.append(FTJobArtifacts.artifactRows(context, artifacts, item => {
      if (!context.session) return context.openLogin(context.t("登录后才能下载生成物"));
      return FTJobArtifacts.saveBlob(context, `/api/jobs/${encodeURIComponent(jobID)}/artifacts/${encodeURIComponent(item.name)}${portQuery}`, item.file_name || item.name);
    }));
    else artifactSection.append(Object.assign(document.createElement("p"), {textContent: context.t("暂无生成物")}));
    root.append(artifactSection); context.content.replaceChildren(root);
    if (["queued", "planning", "running", "paused"].includes(job.status)) FTJobProgress.watchProgress(context, jobID, portQuery, progress);

    async function detailPage() { return window.FTJobs.detail(context, port, jobID); }
    function activeArtifactList() { return artifacts.filter(item => item.state === "active"); }
  }

  window.FTJobs.detail = detail;
})();
