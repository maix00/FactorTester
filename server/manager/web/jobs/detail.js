(() => {
  const {
    text, scalar, date, table, statusPill, kindTitle, jobPort,
    formatBytes, taskTitle,
  } = FTJobs;

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
      label = context.t("运行配置");
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

  function runSpecReference(taskDetail, job, context, serverID = "") {
    const hash = String(job.run_spec_hash || taskDetail.run_spec_hash
      || taskDetail.configuration?.run_spec_hash || "");
    if (!/^(?:sha256:)?[a-f0-9]{64}$/i.test(hash)) return null;
    const target = `runspec:sha256:${hash.replace(/^sha256:/i, "")}`;
    const targetServerID = String(
      serverID || job.execution_server_id || job.server_id
        || taskDetail.execution_server_id || taskDetail.server_id || "",
    ).trim();
    return {
      target,
      serverID: targetServerID,
      path: FTReferencePage.routeFor(
        "run-spec", target, context.t("运行配置"), targetServerID,
      ),
    };
  }

  function routeQuery(port, serverID = "") {
    const params = new URLSearchParams();
    const selected = jobPort(port);
    if (selected) params.set("port", String(selected));
    if (serverID) params.set("server_id", String(serverID));
    const value = params.toString();
    return value ? `?${value}` : "";
  }

  function executionTarget(port, serverID, payload, taskDetail, job) {
    const targetServerID = String(
      serverID
        || job?.execution_server_id
        || taskDetail?.execution_server_id
        || payload?.execution_server_id
        || job?.server_id
        || taskDetail?.server_id
        || payload?.server_id
        || "",
    ).trim();
    const candidates = [
      job?.execution_port,
      taskDetail?.execution_port,
      payload?.execution_port,
      payload?.port,
      job?.server_context?.port,
      job?.port,
      taskDetail?.port,
      // The URL may contain the historical execution port.  It is only a
      // last resort: a terminal Job can be read through another live sibling
      // service after its original worktree has stopped.
      port,
    ];
    const targetPort = candidates
      .map(value => jobPort(value))
      .find(value => value) || 0;
    return {port: targetPort, serverID: targetServerID};
  }

  async function fetchDetail(context, port, jobID, serverID = "") {
    const selectedPort = jobPort(port);
    let executionQuery = routeQuery(selectedPort, serverID);
    let payload;
    try {
      payload = await context.api(`/api/jobs/${encodeURIComponent(jobID)}${executionQuery}`);
    } catch (error) {
      if (!selectedPort) throw error;
      executionQuery = routeQuery(null, serverID);
      payload = await context.api(`/api/jobs/${encodeURIComponent(jobID)}${executionQuery}`);
    }
    const taskDetail = payload.task_detail || payload;
    const job = taskDetail.job || payload;
    const target = executionTarget(
      selectedPort, serverID, payload, taskDetail, job,
    );
    const resolvedPort = target.port;
    const resolvedExecutionQuery = routeQuery(resolvedPort, target.serverID);
    // Artifact storage is owned by the server, not by the worker port that
    // happened to execute the Job.  Keep this query server-only so a stopped
    // worktree cannot break 7997 reads for a retained artifact.
    const artifactQuery = routeQuery(null, target.serverID);
    return {
      payload, taskDetail, job, resolvedPort,
      serverID: target.serverID,
      executionQuery: resolvedExecutionQuery,
      artifactQuery,
      // Backward-compatible name for callers that issue execution actions.
      portQuery: resolvedExecutionQuery,
    };
  }

  async function detail(context, port, jobID, serverID = "", watchLive = true) {
    const isCurrent = () => context.isRouteCurrent?.() !== false;
    if (!isCurrent()) return;
    FTJobProgress.stopProgress();
    context.activeNav("jobs"); context.setHeading(context.t("测试任务详情"));
    context.content.replaceChildren(FTUI.loading(context.t("正在读取任务详情…")));
    const loaded = await fetchDetail(context, port, jobID, serverID);
    if (!isCurrent()) return;
    const {
      payload, taskDetail, job, resolvedPort, serverID: resolvedServerID,
      executionQuery, artifactQuery, portQuery,
    } = loaded;
    const localRun = Boolean(
      payload.local_run || taskDetail.local_run
        || job.local_run || job.execution_mode === "local",
    );
    const artifacts = taskDetail.artifacts || [];
    const inputNames = new Set(
      (taskDetail.input_artifacts || []).map(item => item.name),
    );
    const inputArtifacts = artifacts.filter(item => (
      item.role === "input" || inputNames.has(item.name)
    ));
    const outputArtifacts = artifacts.filter(item => (
      item.role !== "input" && !inputNames.has(item.name)
    ));
    const jobTitle = taskTitle(job, context);
    context.updateActiveTab?.({title: jobTitle});
    context.setHeading(jobTitle, context.t("测试任务详情"));
    context.toolbar.append(FTUI.refreshButton(
      context, () => detailPage(), {label: "刷新详情"},
    ));
    const runSpec = runSpecReference(taskDetail, job, context, resolvedServerID);
    if (context.session && FTJobActions.workbenchKind(job) && FTJobActions.runID(job)) {
      const openConfiguration = context.button(context.t("在配置页面打开"), async () => {
        openConfiguration.disabled = true;
        try {
          await FTJobActions.cloneRunWorkspace(context, {
            job, jobID, portQuery, resolvedPort,
            serverID: resolvedServerID, openNewTab: true,
            title: `${context.t("从测试任务恢复")} ${jobID.slice(0, 8)}`,
          });
        } catch (error) {
          context.showNotice(
            `${context.t("恢复冻结配置失败")}: ${error.message}`, true,
          );
          openConfiguration.disabled = false;
        }
      }, context.t("在配置页面打开"));
      context.toolbar.append(openConfiguration);
    }
    if (!localRun) FTJobActions.install(context, {
      job, jobID, portQuery, resolvedPort, onRefresh: detailPage,
    });
    if (!localRun && artifacts.some(item => item.state === "active") && context.session) {
      context.toolbar.append(context.button("⇩", () => FTJobArtifacts.downloadAllArtifacts(context, activeArtifactList(), jobID, artifactQuery), context.t("下载全部任务文件")));
      context.toolbar.append(context.button("⌫", () => FTJobArtifacts.clearArtifacts(context, artifactQuery, jobID), context.t("清空任务文件")));
    }
    const root = document.createElement("div"); root.className = "job-detail";
    root.dataset.ftRerenderOnTabRestore = "true";
    root.__ftBeforeTabSave = () => FTJobProgress.stopProgress();
    const detailTabs = FTJobDetailTabs.create(
      context, `job-detail-section:${resolvedServerID}:${jobID}`,
    );
    const {
      overview, results: resultsPanel, configuration, inputs,
      artifacts: artifactPanel, supplementals,
    }
      = detailTabs.panels;
    root.append(detailTabs.root);
    const progress = FTJobProgress.progressView(context, job.status);
    overview.append(progress.root);
    overview.append(fieldSection(context, context.t("任务字段"), {
      ...job, port: resolvedPort || port,
    }));
    const storage = taskDetail.storage || {};
    overview.append(fieldSection(context, context.t("文件占用"), {
      [context.t("生成物数量")]: storage.output_artifact_count || 0,
      [context.t("生成物空间")]: formatBytes(storage.output_artifact_bytes || 0),
      [context.t("提交物数量")]: storage.input_artifact_count || 0,
      [context.t("提交物空间")]: formatBytes(storage.input_artifact_bytes || 0),
      [context.t("合计空间")]: formatBytes(storage.artifact_bytes || 0),
    }));
    if (taskDetail.research_binding) overview.append(fieldSection(context, context.t("研究绑定"), taskDetail.research_binding));
    if (taskDetail.caller || taskDetail.submission_context) overview.append(fieldSection(context, context.t("调用方"), taskDetail.caller || taskDetail.submission_context));
    const activeInputs = inputArtifacts.filter(item => item.state === "active");
    if (activeInputs.length) {
      const inputSection = document.createElement("section");
      inputSection.className = "job-section job-inputs";
      const inputTitle = document.createElement("h2");
      inputTitle.textContent = context.t("运行输入");
      inputSection.append(inputTitle, FTJobArtifacts.artifactRows(
        context,
        activeInputs,
       item => context.navigate(
         `/jobs/${resolvedPort || port}/${encodeURIComponent(jobID)}`
           + `/inputs/${encodeURIComponent(item.name)}`
           + (resolvedServerID ? `?server_id=${encodeURIComponent(resolvedServerID)}` : ""),
       ),
      ));
      inputs.append(inputSection);
    } else {
      inputs.append(FTUI.empty(
        context.t("暂无提交物"), context.t("此任务没有可查看的运行输入"),
      ));
    }
    let configurationLoaded = false;
    const loadConfiguration = async () => {
      if (configurationLoaded) return;
      configurationLoaded = true;
      if (runSpec) {
        configuration.replaceChildren(FTUI.loading(context.t("正在读取运行配置…")));
        try {
          const value = await FTRunSpecView.load(
            context, runSpec.target, runSpec.serverID,
          );
          if (configuration.isConnected !== false) {
            configuration.replaceChildren(FTRunSpecView.render(context, value));
          }
          return;
        } catch (error) {
          if (taskDetail.configuration == null) {
            configuration.replaceChildren(FTUI.empty(
              context.t("无法读取运行配置"), error.message || String(error),
            ));
            return;
          }
        }
      }
      configuration.replaceChildren(taskDetail.configuration != null
        ? FTRunSpecView.render(context, taskDetail.configuration)
        : FTUI.empty(context.t("暂无运行配置"), context.t("任务没有绑定运行配置")));
    };
    const declarations = FTJobArtifacts.effectiveDeclarations(
      taskDetail.output_declarations || [], outputArtifacts, context,
    );
    const results = taskDetail.results || payload.result_summary || payload.result;
    const activeArtifacts = localRun
      ? [] : outputArtifacts.filter(item => item.state === "active");
    const resultGroupName = FTJobResultViewers.group(
      job, activeArtifacts, results,
    );
    const resultHost = document.createElement("div");
    resultHost.className = "job-result-host";
    if (!localRun) resultHost.append(FTUI.loading(context.t("正在加载结果查看器…")));
    resultsPanel.append(resultHost);
    // Domain result viewers own their result tabs and load canonical JSON on
    // demand. Generic artifact previews here would duplicate those tabs and
    // eagerly introduce a second, inconsistent rendering path.
    if (!resultGroupName && localRun) resultHost.replaceChildren(
      FTJobResultViewers.genericSection(context, {
        declarations, activeArtifacts, results, jobID, artifactQuery,
        customAnalyses: null,
      }),
    );
    const generationHost = document.createElement("div");
    if (["succeeded", "failed", "cancelled"].includes(job.status) && context.session) {
      generationHost.className = "job-generation-host";
      artifactPanel.append(generationHost);
    }
    const artifactSection = document.createElement("section"); artifactSection.className = "job-section";
    const artifactTitle = document.createElement("h2"); artifactTitle.textContent = context.t("输出生成物"); artifactSection.append(artifactTitle);
    if (localRun) {
      artifactSection.append(Object.assign(document.createElement("p"), {
        className: "job-local-run-note",
        textContent: context.t("本地运行的原始文件保存在客户端；服务器只保存摘要和文件清单，只有主动上传的文件可以下载"),
      }));
      if (outputArtifacts.length) artifactSection.append(FTJobArtifacts.artifactRows(
        context, outputArtifacts,
        item => downloadArtifact(item, context.t("该文件尚未主动上传到服务器")),
        {
          includeLocalOnly: true,
          onUpload: item => uploadLocalArtifact(item),
        },
      ));
      else artifactSection.append(Object.assign(document.createElement("p"), {
        textContent: context.t("暂无输出生成物"),
      }));
    } else if (activeArtifacts.length) artifactSection.append(FTJobArtifacts.artifactRows(
      context, activeArtifacts,
      item => downloadArtifact(item, context.t("登录后才能下载生成物")),
      context.session ? {onDelete: async item => {
          await FTJobArtifacts.deleteArtifact(
            context, artifactQuery, jobID, item.name,
          );
          await detailPage();
        }} : {},
    ));
    else artifactSection.append(Object.assign(document.createElement("p"), {textContent: context.t("暂无输出生成物")}));
    artifactPanel.append(artifactSection);
    const customAnalyses = FTJobCustomAnalyses.create(context, {
      jobID, artifactQuery,
    });
    const supplementalView = FTJobSupplementals.create(context, {
      jobID, artifactQuery,
      onOpen: job => {
        detailTabs.select("results", true);
        if (job.recoverable === false) {
          resultHost.replaceChildren(FTUI.empty(
            context.t("提交物已删除，无法恢复"),
            context.t("补充任务历史仍保留，但对应的提交物已经被显式删除"),
          ));
          return;
        }
        if (job.supplemental_kind === "custom_python_analysis") {
          const tabID = String(job.target?.tab_id || "");
          if (tabID) {
            customAnalyses.request(tabID);
            resultsLoaded = false;
            loadResults();
          }
          return;
        }
        customAnalyses.state.requestedSupplemental = job;
        resultsLoaded = false;
        loadResults();
      },
    });
    supplementals.append(supplementalView.root);
    // Paint the overview and artifact metadata immediately. Configuration,
    // result runtimes, and generation capabilities load only when selected.
    context.content.replaceChildren(root);
    let resultsLoaded = false;
    const loadResults = () => {
      if (resultsLoaded || localRun) return;
      resultsLoaded = true;
      Promise.all([
        resultGroupName
          ? FTJobResultViewers.loadGroup(job, activeArtifacts, results)
          : Promise.resolve(),
        customAnalyses.load(),
      ]).then(() => {
        if (!isCurrent()) return;
        if (resultGroupName) {
          resultHost.replaceChildren(FTJobResultViewers.domainSections(
            context, {
              job, taskDetail, payload, activeArtifacts, results, jobID,
              artifactQuery, executionQuery, customAnalyses,
            },
          ));
        } else {
          resultHost.replaceChildren(FTJobResultViewers.genericSection(context, {
            declarations, activeArtifacts, results, jobID, artifactQuery,
            customAnalyses,
            state: {
              activeTab: customAnalyses.state.requestedKey || "result",
            },
          }));
        }
      }).catch(error => {
        if (isCurrent()) resultHost.replaceChildren(FTUI.empty(
          context.t("结果查看器不可用"), error.message || String(error),
        ));
      });
    };
    let generationLoaded = false;
    const loadGeneration = () => {
      if (generationLoaded || localRun
        || !["succeeded", "failed", "cancelled"].includes(job.status)
        || !context.session) return;
      generationLoaded = true;
      (async () => {
        let capabilities = [];
        let capabilityError = "";
        try {
          capabilities = await FTJobGeneration.capabilities(context, artifactQuery);
        } catch (error) { capabilityError = error.message; }
        if (!isCurrent()) return;
        generationHost.replaceChildren(FTJobGeneration.panel(context, {
          capabilities, error: capabilityError, jobID,
          portQuery: executionQuery, executionQuery, artifactQuery,
          taskDetail, payload, onGenerated: detailPage,
        }));
      })();
    };
    const loadSelectedSection = id => {
      if (id === "configuration") loadConfiguration();
      if (id === "results") loadResults();
      if (id === "artifacts") loadGeneration();
      if (id === "supplementals") supplementalView.load();
    };
    detailTabs.root.addEventListener("job-detail-tab-change", event => {
      loadSelectedSection(event.detail?.id || "overview");
    });
    loadSelectedSection(detailTabs.current());
    if (watchLive && ["queued", "planning", "running", "paused"].includes(job.status)) {
      FTJobProgress.watchProgress(context, jobID, executionQuery, progress, {
        onPayload: () => {
          if (progress.progressState?.terminal) FTJobProgress.stopProgress();
        },
        onComplete: () => {
          // Converge once against the authoritative detail projection.  The
          // replacement view deliberately stays static when the stream ended
          // non-terminally, avoiding an unbounded reconnect loop while a
          // remote execution server remains unavailable.
          if (isCurrent()) void detail(
            context, resolvedPort || port, jobID, resolvedServerID, false,
          );
        },
      });
    }

    async function detailPage() {
      return window.FTJobs.detail(
        context, resolvedPort || port, jobID, resolvedServerID,
      );
    }
    function activeArtifactList() { return artifacts.filter(item => item.state === "active"); }
    async function uploadLocalArtifact(item) {
      const handler = window.webkit?.messageHandlers?.factorTesterLocalRun;
      if (!handler?.postMessage) {
        throw new Error(context.t("主动上传只能从 Swift 客户端发起"));
      }
      const value = await handler.postMessage({
        action: "upload", local_job_id: jobID, name: item.name,
      });
      if (!value || value.success === false) {
        throw new Error(value?.error || context.t("本地生成物上传失败"));
      }
      await detailPage();
    }
    function downloadArtifact(item, loginMessage) {
      if (!context.session) return context.openLogin(loginMessage);
      if (localRun && item.state !== "active") {
        return context.alert?.(loginMessage)
          || context.showMessage?.(loginMessage);
      }
      const path = `/api/jobs/${encodeURIComponent(jobID)}`
        + `/artifacts/${encodeURIComponent(item.name)}${artifactQuery}`;
      return FTJobArtifacts.saveBlob(
        context, path, item.file_name || item.name,
      );
    }
  }

  async function configuration(context, port, jobID, serverID = "") {
    const isCurrent = () => context.isRouteCurrent?.() !== false;
    if (!isCurrent()) return;
    FTJobProgress.stopProgress();
    context.activeNav("jobs");
    context.setHeading(context.t("运行配置"));
    context.content.replaceChildren(FTUI.loading(context.t("正在读取运行配置…")));
    const loaded = await fetchDetail(context, port, jobID, serverID);
    if (!isCurrent()) return;
    const {taskDetail, job} = loaded;
    const runSpec = runSpecReference(taskDetail, job, context, loaded.serverID);
    if (!runSpec) {
      context.content.replaceChildren(FTUI.empty(
        context.t("无法读取运行配置"), context.t("任务没有绑定运行配置"),
      ));
      return;
    }
    return FTReferencePage.render(context, {
      kind: "run-spec", target: runSpec.target, label: context.t("运行配置"),
      serverID: runSpec.serverID,
    });
  }

  window.FTJobs.detail = detail;
  window.FTJobs.configuration = configuration;
  window.FTJobs.loadDetail = fetchDetail;
})();
