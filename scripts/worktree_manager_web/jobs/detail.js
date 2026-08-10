(() => {
  const {text, scalar, date, table, statusPill, kindTitle, jobPort} = FTJobs;

  function fieldSection(context, title, value) {
    const section = document.createElement("section"); section.className = "job-section";
    const heading = document.createElement("h2"); heading.textContent = title; section.append(heading);
    section.append(fieldContent(context, value));
    return section;
  }

  function fieldContent(context, value) {
    const content = document.createDocumentFragment();
    const entries = Object.entries(value || {}).filter(([, item]) => scalar(item));
    if (entries.length) {
      const result = table([context.t("字段"), context.t("值")], entries.map(([key, item]) => [key, fieldValue(context, key, item)]));
      result.shell.classList.add("field-table"); content.append(result.shell);
    }
    const residual = Object.fromEntries(Object.entries(value || {}).filter(([, item]) => !scalar(item)));
    if (Object.keys(residual).length) content.append(FTUI.code(residual));
    return content;
  }

  function lazyConfigurationPreview(context, configuration) {
    const target = document.createElement("div");
    target.className = "job-configuration-preview";
    const details = FTJobArtifacts.collapsible(context.t("测试配置"), target);
    let loaded = false;
    details.addEventListener("toggle", () => {
      if (!details.open || loaded) return;
      loaded = true;
      target.replaceChildren(fieldContent(context, configuration || {}));
    });
    return details;
  }

  function fieldValue(context, key, value) {
    if (key === "status") return statusPill(value, context);
    const reference = fieldReference(context, key, value);
    if (reference) return reference;
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

  function fieldReference(context, key, value) {
    const raw = String(value || "");
    let kind = ""; let target = ""; let label = "";
    if (key === "run_spec_hash" && /^(?:sha256:)?[a-f0-9]{64}$/i.test(raw)) {
      kind = "run-spec";
      target = `runspec:sha256:${raw.replace(/^sha256:/i, "")}`;
      label = context.t("冻结运行配置");
    } else if (key === "trial_plan_hash" && /^(?:sha256:)?[a-f0-9]{64}$/i.test(raw)) {
      kind = "trial-plan";
      target = `trial-plan:sha256:${raw.replace(/^sha256:/i, "")}`;
      label = context.t("冻结试验计划");
    } else if (key === "run_id" && raw) {
      kind = "run"; target = raw.startsWith("run:") ? raw : `run:${raw}`;
      label = context.t("运行");
    }
    if (!target) return null;
    const anchor = document.createElement("a");
    anchor.href = FTReferencePage.routeFor(kind, target, label);
    anchor.textContent = raw;
    anchor.title = label;
    anchor.addEventListener("click", event => {
      event.preventDefault(); context.navigate(anchor.getAttribute("href"));
    });
    return anchor;
  }

  function runSpecReference(taskDetail, job, context) {
    const hash = String(job.run_spec_hash || taskDetail.run_spec_hash
      || taskDetail.configuration?.run_spec_hash || "");
    if (!/^(?:sha256:)?[a-f0-9]{64}$/i.test(hash)) return null;
    const target = `runspec:sha256:${hash.replace(/^sha256:/i, "")}`;
    return {
      title: context.t("查看 RunSpec"),
      path: FTReferencePage.routeFor("run-spec", target, context.t("冻结运行配置")),
    };
  }

  async function fetchDetail(context, port, jobID) {
    const selectedPort = jobPort(port);
    let portQuery = selectedPort ? `?port=${selectedPort}` : "";
    let payload;
    try {
      payload = await context.api(`/api/jobs/${encodeURIComponent(jobID)}${portQuery}`);
    } catch (error) {
      if (!selectedPort) throw error;
      portQuery = "";
      payload = await context.api(`/api/jobs/${encodeURIComponent(jobID)}`);
    }
    const taskDetail = payload.task_detail || payload;
    const job = taskDetail.job || payload;
    const resolvedPort = Number(
      payload.port || job.server_context?.port || selectedPort || 0,
    );
    return {
      payload, taskDetail, job, resolvedPort,
      portQuery: resolvedPort ? `?port=${resolvedPort}` : "",
    };
  }

  async function detail(context, port, jobID) {
    const isCurrent = () => context.isRouteCurrent?.() !== false;
    if (!isCurrent()) return;
    FTJobProgress.stopProgress();
    context.activeNav("jobs"); context.setHeading(context.t("测试任务详情"));
    context.content.replaceChildren(FTUI.loading(context.t("正在读取任务详情…")));
    const loaded = await fetchDetail(context, port, jobID);
    if (!isCurrent()) return;
    const {payload, taskDetail, job, resolvedPort, portQuery} = loaded;
    const artifacts = taskDetail.artifacts || [];
    const jobTitle = `${kindTitle(job.kind, context)} · ${jobID}`;
    context.updateActiveTab?.({title: jobTitle});
    context.setHeading(jobTitle, context.t("测试任务详情"));
    context.toolbar.append(context.button("↻", () => detailPage(), context.t("刷新详情")));
    context.toolbar.append(context.button(context.t("查看测试配置"), () => {
      context.navigate(
        `/jobs/${resolvedPort || port}/${encodeURIComponent(jobID)}/configuration`,
      );
    }, context.t("查看测试配置")));
    const runSpec = runSpecReference(taskDetail, job, context);
    if (runSpec) context.toolbar.append(context.button(runSpec.title, () => {
      context.navigate(runSpec.path);
    }, runSpec.title));
    FTJobActions.install(context, {
      job, jobID, portQuery, resolvedPort, onRefresh: detailPage,
    });
    if (artifacts.some(item => item.state === "active") && context.session) {
      context.toolbar.append(context.button("⇩", () => FTJobArtifacts.downloadAllArtifacts(context, activeArtifactList(), jobID, portQuery), context.t("下载全部生成物")));
      context.toolbar.append(context.button("⌫", () => FTJobArtifacts.clearArtifacts(context, portQuery, jobID), context.t("清空生成物")));
    }
    const root = document.createElement("div"); root.className = "job-detail";
    const progress = FTJobProgress.progressView(context, job.status);
    root.append(progress.root);
    root.append(fieldSection(context, context.t("任务字段"), {
      ...job, port: resolvedPort || port,
    }));
    if (taskDetail.research_binding) root.append(fieldSection(context, context.t("研究绑定"), taskDetail.research_binding));
    if (taskDetail.caller || taskDetail.submission_context) root.append(fieldSection(context, context.t("调用方"), taskDetail.caller || taskDetail.submission_context));
    if (taskDetail.configuration != null) {
      root.append(lazyConfigurationPreview(context, taskDetail.configuration));
    }
    const declarations = FTJobArtifacts.effectiveDeclarations(taskDetail.output_declarations || [], artifacts, context);
    if (declarations.length) root.append(fieldSection(context, context.t("结果展示声明"), Object.fromEntries(declarations.map(item => [item.label || item.name, `${item.presentation || "data"} · ${item.viewer || "json"}`]))));
    const results = taskDetail.results || payload.result_summary || payload.result;
    const activeArtifacts = artifacts.filter(item => item.state === "active");
    const icResults = window.FTICResults?.section(context, {
      artifacts: activeArtifacts, jobID, portQuery,
    });
    if (icResults) root.append(icResults);
    declarations.forEach(declaration => {
      const previewArtifacts = FTJobArtifacts.declarationArtifacts(
        declaration, activeArtifacts,
      );
      if (previewArtifacts.length) {
        root.append(FTJobArtifacts.lazyArtifactPreview(
          context, declaration, previewArtifacts, jobID, portQuery,
        ));
      }
    });
    if (results != null) root.append(FTJobArtifacts.collapsible(context.t("结果预览"), FTUI.code(results)));
    if (["succeeded", "failed", "cancelled"].includes(job.status) && context.session) {
      let capabilities = [];
      let capabilityError = "";
      try {
        capabilities = await FTJobGeneration.capabilities(context, portQuery);
      } catch (error) { capabilityError = error.message; }
      if (!isCurrent()) return;
      root.append(FTJobGeneration.panel(context, {
        capabilities, error: capabilityError, jobID, portQuery,
        taskDetail, payload, onGenerated: detailPage,
      }));
    }
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

  async function configuration(context, port, jobID) {
    const isCurrent = () => context.isRouteCurrent?.() !== false;
    if (!isCurrent()) return;
    FTJobProgress.stopProgress();
    context.activeNav("jobs");
    context.setHeading(context.t("测试配置"));
    context.content.replaceChildren(FTUI.loading(context.t("正在读取测试配置…")));
    const loaded = await fetchDetail(context, port, jobID);
    if (!isCurrent()) return;
    const {taskDetail, job, resolvedPort} = loaded;
    const title = `${kindTitle(job.kind, context)} · ${context.t("测试配置")}`;
    context.updateActiveTab?.({title});
    context.setHeading(title, context.t("测试配置"));
    context.toolbar.append(context.button(context.t("返回任务详情"), () => {
      context.navigate(`/jobs/${resolvedPort || port}/${encodeURIComponent(jobID)}`);
    }, context.t("返回任务详情")));
    const runSpec = runSpecReference(taskDetail, job, context);
    if (runSpec) context.toolbar.append(context.button(runSpec.title, () => {
      context.navigate(runSpec.path);
    }, runSpec.title));
    const root = document.createElement("div");
    root.className = "job-configuration-detail detail-stack";
    root.append(fieldSection(
      context, context.t("具体测试配置"), taskDetail.configuration || {},
    ));
    context.content.replaceChildren(root);
  }

  window.FTJobs.detail = detail;
  window.FTJobs.configuration = configuration;
})();
