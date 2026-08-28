(() => {
  const terminalStatuses = new Set(["succeeded", "failed", "cancelled"]);

  function recordDetail(item, loaded) {
    item.detailPayload = loaded.payload;
    item.taskDetail = loaded.taskDetail;
    item.job = loaded.job;
    item.port = Number(loaded.resolvedPort || item.port || 0);
    item.serverID = String(loaded.serverID || item.serverID || "");
    item.portQuery = loaded.portQuery || (item.port ? `?port=${item.port}` : "");
    item.artifactQuery = loaded.artifactQuery || item.artifactQuery || "";
    item.phase = String(loaded.job?.status || item.phase || "submitted");
    item.resultError = "";
    return item;
  }

  function resultCode(state) {
    if (state.kind === "ic") {
      return {group: "job-detail-ic", global: "FTICResults"};
    }
    if (state.kind === "backtest") {
      return {group: "job-detail-backtest", global: "FTBacktestResults"};
    }
    return null;
  }

  async function ensureResultCode(state, item, rerender) {
    const descriptor = resultCode(state);
    if (!descriptor || window[descriptor.global]) return true;
    if (!item.resultViewerPromise) {
      item.resultCodeLoading = true;
      item.resultViewerPromise = Promise.resolve(
        window.FTStaticLoader?.loadGroups?.([descriptor.group]),
      )
        .then(() => {
          if (!window[descriptor.global]) {
            throw new Error("结果查看器不可用");
          }
        })
        .catch(error => {
          item.resultError = error.message || String(error);
          item.resultViewerPromise = null;
          throw error;
        })
        .finally(() => {
          item.resultCodeLoading = false;
          rerender?.();
        });
    }
    try {
      await item.resultViewerPromise;
      return true;
    } catch (_) {
      return false;
    }
  }

  async function refresh(context, state, item, rerender) {
    if (!item.jobID || item.resultLoading) return false;
    item.resultLoading = true;
    item.resultError = "";
    rerender?.();
    try {
      recordDetail(item, await window.FTJobs.loadDetail(
        context, item.port, item.jobID, item.serverID || "",
      ));
      await ensureResultCode(state, item, rerender);
      return true;
    } catch (error) {
      item.resultError = error.message || String(error);
      return false;
    } finally {
      item.resultLoading = false;
      rerender?.();
      if (item.progressRefreshPending) {
        item.progressRefreshPending = false;
        queueMicrotask(() => refresh(context, state, item, rerender));
      }
    }
  }

  function resultSection(context, state, item, rerender) {
    const task = item.taskDetail || {};
    const payload = item.detailPayload || {};
    const allArtifacts = Array.isArray(task.artifacts) ? task.artifacts : [];
    const inputNames = new Set(
      (task.input_artifacts || []).map(entry => String(entry?.name || "")),
    );
    const artifacts = allArtifacts.filter(entry => entry.state === "active");
    const outputArtifacts = artifacts.filter(entry => (
      entry.role !== "input" && !inputNames.has(String(entry.name || ""))
    ));
    const options = {
      artifacts, jobID: item.jobID,
      portQuery: item.portQuery || "",
      artifactQuery: item.artifactQuery || "",
      configuration: task.configuration || {}, productGroupRef: item.groupID || "",
      resultDeclarations: task.output_declarations || [],
    };
    let domain = null;
    if (state.kind === "ic") domain = window.FTICResults?.section(context, options);
    if (state.kind === "backtest") {
      domain = window.FTBacktestResults?.section(context, {
        ...options,
        configuration: task.configuration || {},
        resultSummary: payload.result_summary || task.results?.summary || {},
        job: item.job || {},
      });
    }
    const previews = domain ? null : artifactPreviewSection(
      context, task, outputArtifacts, item.jobID, item.artifactQuery || "",
    );
    const outputs = artifactOutputSection(
      context, outputArtifacts, item.jobID, item.artifactQuery || "",
      async artifact => {
        await window.FTJobArtifacts.deleteArtifact(
          context, item.artifactQuery || "", item.jobID, artifact.name,
        );
        await refresh(context, state, item, rerender);
      },
    );
    if (!domain && !previews && !outputs) return null;
    if (domain && !previews && !outputs) return domain;
    if (typeof document === "undefined") return domain || previews || outputs;
    const content = document.createDocumentFragment();
    if (domain) content.append(domain);
    if (previews) content.append(previews);
    if (outputs) content.append(outputs);
    return content;
  }

  function artifactPreviewSection(context, task, artifacts, jobID, artifactQuery) {
    const api = window.FTJobArtifacts;
    if (!api?.effectiveDeclarations || !api.declarationArtifacts
        || !api.lazyArtifactPreview || !artifacts.length) return null;
    const declarations = api.effectiveDeclarations(
      task.output_declarations || [], artifacts, context,
    );
    const root = document.createElement("section");
    root.className = "test-run-artifact-previews";
    const heading = document.createElement("h3");
    heading.textContent = context.t("结果预览");
    root.append(heading);
    let count = 0;
    declarations.forEach(declaration => {
      const matches = api.declarationArtifacts(declaration, artifacts);
      if (!matches.length) return;
      root.append(api.lazyArtifactPreview(
        context, declaration, matches, jobID, artifactQuery,
      ));
      count += 1;
    });
    return count ? root : null;
  }

  function artifactOutputSection(
    context, artifacts, jobID, artifactQuery, onDelete,
  ) {
    const api = window.FTJobArtifacts;
    if (!api?.artifactRows || !api.saveBlob || !artifacts.length) return null;
    const root = document.createElement("section");
    root.className = "test-run-output-artifacts";
    const heading = document.createElement("h3");
    heading.textContent = context.t("输出生成物");
    root.append(heading, api.artifactRows(
      context, artifacts,
      item => api.saveBlob(
        context,
        `/api/jobs/${encodeURIComponent(jobID)}/artifacts/${encodeURIComponent(item.name)}${artifactQuery}`,
        item.file_name || item.name,
      ),
      context.session ? {onDelete} : {},
    ));
    return root;
  }

  function render(context, state, item, rerender) {
    const root = document.createElement("div");
    root.className = "test-run-inline-results";
    if (!item.jobID) return root;
    const progress = window.FTTestRunProgress?.render(
      context, state, item, rerender,
    );
    if (progress) root.append(progress);
    if (!item.taskDetail && !item.resultLoading && !item.resultAutoRefreshStarted) {
      item.resultAutoRefreshStarted = true;
      queueMicrotask(() => refresh(context, state, item, rerender));
    }
    const toolbar = document.createElement("div");
    toolbar.className = "test-run-result-actions";
    const reload = context.button("↻", () => {
      item.progressStreamClosed = false;
      refresh(context, state, item, rerender);
    }, context.t("刷新任务结果"));
    reload.disabled = Boolean(item.resultLoading);
    toolbar.append(reload);
    const cancel = window.FTJobActions?.cancelButton?.(context, {
      job: {
        ...(item.job || {}), status: item.phase,
        cancel_requested: item.cancelRequested || item.job?.cancel_requested,
      },
      jobID: item.jobID,
      portQuery: item.portQuery || "",
      onAccepted: () => {
        item.cancelRequested = true;
        rerender?.();
      },
      onRefresh: () => refresh(context, state, item, rerender),
    });
    if (cancel) toolbar.append(cancel);
    root.append(toolbar);
    if (item.resultLoading) {
      root.append(window.FTUI.loading(context.t("正在读取任务结果…")));
      return root;
    }
    if (item.resultError) {
      const error = document.createElement("p");
      error.className = "test-run-error"; error.textContent = item.resultError;
      root.append(error); return root;
    }
    if (!item.taskDetail) {
      const hint = document.createElement("p");
      hint.className = "test-run-result-hint";
      hint.textContent = context.t("任务提交后可在此刷新并查看完整测试结果");
      root.append(hint); return root;
    }
    const descriptor = resultCode(state);
    if (descriptor && !window[descriptor.global]) {
      ensureResultCode(state, item, rerender);
      root.append(window.FTUI.loading(context.t("正在加载结果查看器…")));
      return root;
    }
    const section = resultSection(context, state, item, rerender);
    if (section) root.append(section);
    else {
      const hint = document.createElement("p");
      hint.className = "test-run-result-hint";
      hint.textContent = terminalStatuses.has(item.phase)
        ? context.t("该任务没有可展示的领域结果生成物")
        : context.t("任务尚未生成可展示结果，请稍后手动刷新");
      root.append(hint);
    }
    return root;
  }

  window.FTTestRunResults = Object.freeze({
    recordDetail, refresh, render, resultSection,
  });
})();
