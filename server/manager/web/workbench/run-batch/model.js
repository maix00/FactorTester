(() => {
  const BACKTEST_TASK_ID = "__backtest__";
  const PHASE_LABELS = {
    idle: "尚未提交",
    freezing: "正在冻结配置",
    frozen: "配置已冻结",
    submitting: "正在提交",
    submitted: "已提交",
    planning: "规划中",
    awaiting_confirmation: "等待确认",
    queued: "排队中",
    running: "运行中",
    paused: "已暂停",
    succeeded: "成功",
    cancelled: "已取消",
    failed: "失败",
  };

  function groupIdentity(group) {
    return String(FTTestProducts.groupID(group) || "");
  }

  function hasProductSelection(group) {
    const selection = group?.product_path_selection;
    return Boolean(
      group?.product_path_selection_id
      || group?.product_group_ref
      || selection?.product_path_selection_id
      || selection?.product_group_template_id
      || selection?.group_ref
      || selection?.id
      || (Array.isArray(selection?.selected_paths) && selection.selected_paths.length)
      || (Array.isArray(selection?.paths) && selection.paths.length),
    );
  }

  function backtestStrategyGroups(state) {
    return (Array.isArray(state?.analysis?.groups) ? state.analysis.groups : [])
      .filter(hasProductSelection);
  }

  function taskGroups(state) {
    if (state?.kind === "backtest") {
      // A backtest is one task/RunSpec. Its execution scope is owned by the
      // individual strategy groups in analysis.groups; this synthetic handle
      // is only for the task matrix and is never persisted as a product group.
      return backtestStrategyGroups(state).length
        ? [{id: BACKTEST_TASK_ID, label: "回测任务"}] : [];
    }
    const products = window.FTTestProducts;
    products?.synchronize?.(state);
    return products?.selectedGroups?.(state) || [];
  }

  function synchronize(state) {
    const prior = new Map((state.testRunBatch || []).map(item => [item.groupID, item]));
    state.testRunBatch = taskGroups(state).map(group => {
      const groupID = groupIdentity(group);
      return {
        phase: "idle", runSpecHash: "", runID: "", jobID: "", port: 0,
        serverID: "",
        error: "", ...prior.get(groupID), groupID,
        groupLabel: FTTestProducts.groupLabel(group),
      };
    });
    if (!state.testRunBatch.some(item => item.groupID === state.activeRunGroupID)) {
      state.activeRunGroupID = state.testRunBatch[0]?.groupID || "";
    }
    return state.testRunBatch;
  }

  function itemFor(state, group) {
    const groupID = groupIdentity(group);
    return synchronize(state).find(item => item.groupID === groupID);
  }

  function recordPreview(item, value) {
    item.phase = "frozen";
    item.runSpecHash = String(value.run_spec_hash || "").replace(/^sha256:/, "");
    item.port = Number(value.port || item.port || 0);
    item.serverID = String(
      value.server_id || value.execution_server_id || item.serverID || "",
    ).trim();
    item.portQuery = routeQuery(item);
    item.error = "";
    return item;
  }

  function recordSubmission(item, value) {
    const job = value.jobs?.[0];
    if (!job?.job_id) throw new Error("任务提交响应缺少 Job ID");
    item.phase = "submitted";
    item.jobID = String(job.job_id);
    item.runID = String(value.run?.run_id || value.run_id || job.run_id || "");
    item.runSpecHash = String(
      value.run?.run_spec_hash || job.run_spec_hash || item.runSpecHash || "",
    ).replace(/^sha256:/, "");
    item.port = Number(value.port || job.server_context?.port || job.port || 0);
    item.serverID = String(
      value.server_id || value.execution_server_id
        || job.server_id || job.execution_server_id
        || job.server_context?.server_id || "",
    ).trim();
    item.portQuery = routeQuery(item);
    item.detailPayload = null;
    item.taskDetail = null;
    item.job = null;
    item.artifactQuery = "";
    item.resultError = "";
    item.resultAutoRefreshStarted = false;
    item.error = "";
    return item;
  }

  function recordLocalSubmission(item, value) {
    const runID = String(value.run_id || value.run?.run_id || "");
    if (!runID) throw new Error("本地运行响应缺少运行 ID");
    item.phase = String(value.phase || "submitted");
    item.runID = runID;
    item.jobID = "";
    item.port = 0;
    item.serverID = "";
    item.portQuery = "";
    item.artifactQuery = "";
    item.resultAutoRefreshStarted = false;
    item.runSpecHash = String(
      value.run_spec_hash || value.run?.run_spec_hash || item.runSpecHash || "",
    ).replace(/^sha256:/, "");
    item.local = true;
    item.error = "";
    return item;
  }

  function runSpecTarget(item) {
    if (!/^[a-f0-9]{64}$/i.test(item?.runSpecHash || "")) return "";
    return `runspec:sha256:${item.runSpecHash}`;
  }

  function runSpecPath(item) {
    const target = runSpecTarget(item);
    if (!target) return "";
    if (window.FTReferencePage?.routeFor) {
      return FTReferencePage.routeFor(
        "run-spec", target, "运行配置", item.serverID || "",
      );
    }
    const query = new URLSearchParams({kind: "run-spec", target, label: "运行配置"});
    if (item.serverID) query.set("server_id", item.serverID);
    return `/reference?${query}`;
  }

  function routeQuery(item) {
    const params = new URLSearchParams();
    if (item?.port) params.set("port", String(item.port));
    if (item?.serverID) params.set("server_id", String(item.serverID));
    const value = params.toString();
    return value ? `?${value}` : "";
  }

  function jobPath(item) {
    if (!item?.jobID) return "";
    const path = item.port
      ? `/jobs/${item.port}/${encodeURIComponent(item.jobID)}`
      : `/jobs/${encodeURIComponent(item.jobID)}`;
    return item.serverID
      ? `${path}?server_id=${encodeURIComponent(item.serverID)}`
      : path;
  }

  function update(item, phase, refresh) {
    item.phase = phase;
    item.error = "";
    refresh?.();
  }

  window.FTTestRunBatchModel = Object.freeze({
    BACKTEST_TASK_ID, PHASE_LABELS, backtestStrategyGroups, groupIdentity, itemFor,
    jobPath, recordPreview,
    recordSubmission, recordLocalSubmission, routeQuery, runSpecPath, runSpecTarget,
    synchronize, taskGroups, update,
  });
})();
