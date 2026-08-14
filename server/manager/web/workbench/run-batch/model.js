(() => {
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

  function synchronize(state) {
    const prior = new Map((state.testRunBatch || []).map(item => [item.groupID, item]));
    state.testRunBatch = FTTestProducts.selectedGroups(state).map(group => {
      const groupID = groupIdentity(group);
      return {
        phase: "idle", runSpecHash: "", runID: "", jobID: "", port: 0,
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
    item.detailPayload = null;
    item.taskDetail = null;
    item.job = null;
    item.portQuery = "";
    item.resultError = "";
    item.error = "";
    return item;
  }

  function runSpecPath(item) {
    if (!/^[a-f0-9]{64}$/i.test(item?.runSpecHash || "")) return "";
    const target = `runspec:sha256:${item.runSpecHash}`;
    if (window.FTReferencePage?.routeFor) {
      return FTReferencePage.routeFor("run-spec", target, "运行配置");
    }
    const query = new URLSearchParams({kind: "run-spec", target, label: "运行配置"});
    return `/reference?${query}`;
  }

  function jobPath(item) {
    if (!item?.jobID) return "";
    return item.port
      ? `/jobs/${item.port}/${encodeURIComponent(item.jobID)}`
      : `/jobs/${encodeURIComponent(item.jobID)}`;
  }

  function update(item, phase, refresh) {
    item.phase = phase;
    item.error = "";
    refresh?.();
  }

  window.FTTestRunBatchModel = Object.freeze({
    PHASE_LABELS, groupIdentity, itemFor, jobPath, recordPreview,
    recordSubmission, runSpecPath, synchronize, update,
  });
})();
