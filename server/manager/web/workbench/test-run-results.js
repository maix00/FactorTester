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
    if (!item.resultCodePromise) {
      item.resultCodeLoading = true;
      item.resultCodePromise = Promise.resolve(
        window.FTStaticLoader?.loadGroups?.([descriptor.group]),
      )
        .then(() => {
          if (!window[descriptor.global]) {
            throw new Error("结果查看器不可用");
          }
        })
        .catch(error => {
          item.resultError = error.message || String(error);
          throw error;
        })
        .finally(() => {
          item.resultCodeLoading = false;
          rerender?.();
        });
    }
    try {
      await item.resultCodePromise;
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

  function resultSection(context, state, item) {
    const task = item.taskDetail || {};
    const payload = item.detailPayload || {};
    const artifacts = (task.artifacts || []).filter(entry => entry.state === "active");
    const options = {
      artifacts, jobID: item.jobID,
      portQuery: item.portQuery || "",
      artifactQuery: item.artifactQuery || "",
      configuration: task.configuration || {}, productGroupRef: item.groupID || "",
    };
    if (state.kind === "ic") return window.FTICResults?.section(context, options);
    if (state.kind === "backtest") {
      return window.FTBacktestResults?.section(context, {
        ...options,
        configuration: task.configuration || {},
        resultSummary: payload.result_summary || task.results?.summary || {},
        job: item.job || {},
      });
    }
    return null;
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
    const reload = context.button("↻", () => refresh(context, state, item, rerender), context.t("刷新任务结果"));
    reload.disabled = Boolean(item.resultLoading);
    toolbar.append(reload);
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
    const section = resultSection(context, state, item);
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
