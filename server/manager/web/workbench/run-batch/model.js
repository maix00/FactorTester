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
    if (String(group?.id || "") === BACKTEST_TASK_ID) return BACKTEST_TASK_ID;
    return String(FTTestProducts.groupID(group) || "");
  }

  function groupLabel(group) {
    if (String(group?.id || "") === BACKTEST_TASK_ID) {
      return String(group.label || "回测任务");
    }
    return String(FTTestProducts.groupLabel(group) || group?.label || "");
  }

  function clone(value) {
    if (value == null) return value;
    if (typeof structuredClone === "function") return structuredClone(value);
    return JSON.parse(JSON.stringify(value));
  }

  function stableValue(value) {
    if (value == null || typeof value !== "object") return value;
    if (Array.isArray(value)) return value.map(stableValue);
    return Object.keys(value).sort().reduce((result, key) => {
      if (typeof value[key] === "function" || value[key] === undefined) return result;
      result[key] = stableValue(value[key]);
      return result;
    }, {});
  }

  function errorDetail(error) {
    const seen = new Set();
    const parts = [];
    const append = value => {
      if (value == null || value === "" || typeof value === "boolean") return;
      if (typeof value === "string" || typeof value === "number") {
        const text = String(value).trim();
        if (text && !parts.includes(text)) parts.push(text);
        return;
      }
      if (typeof value !== "object" || seen.has(value)) return;
      seen.add(value);
      if (Array.isArray(value)) return void value.forEach(append);
      const identity = [value.server_id, value.port].filter(Boolean).join(":");
      if (identity) append(identity);
      ["error", "message", "code", "detail", "details", "reason", "candidates", "failures"]
        .forEach(key => append(value[key]));
    };
    append(error?.message || error);
    append(error?.code);
    append(error?.detail);
    append(error?.details);
    append(error?.candidates);
    append(error?.payload);
    return parts.join(" · ") || "未知错误";
  }

  function groupInput(group) {
    if (!group || typeof group !== "object") return group || null;
    return {
      id: group.id || "",
      product_path_selection_id: group.product_path_selection_id || "",
      product_group_ref: group.product_group_ref || "",
      product_path_selection: group.product_path_selection || null,
      selected_paths: group.selected_paths || [],
      paths: group.paths || [],
    };
  }

  function inputFingerprint(state, group) {
    const snapshot = {
      kind: state?.kind || "",
      factorRef: state?.factorRef || "",
      groupRef: state?.groupRef || "",
      groupRefs: state?.groupRefs || [],
      values: state?.values || {},
      runValues: state?.runValues || {},
      outputRequests: state?.outputRequests || [],
      transientFactorSources: state?.transientFactorSources || [],
      transientStrategySources: state?.transientStrategySources || [],
      strategySpecs: state?.strategySpecs || [],
      settingsMountedTabs: state?.settingsMountedTabs || [],
      group: groupInput(group),
    };
    // IC and factor-evaluation analysis is rebuilt per task from the group.
    // Backtest analysis is user-authored and therefore belongs in the input
    // identity used to decide whether a preview can be reused.
    if (state?.kind === "backtest") snapshot.analysis = state.analysis || {};
    return JSON.stringify(stableValue(snapshot));
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
      const existing = prior.get(groupID);
      if (existing) {
        // Progress streams and asynchronous result reads retain this object.
        // Repainting must not replace it, otherwise terminal status and result
        // payloads are written into a detached entry and disappear on the
        // next synchronize() call.
        existing.groupLabel = groupLabel(group);
        return existing;
      }
      return {
        phase: "idle", runSpecHash: "", runSpecRecord: null,
        previewRunSpecHash: "", previewRequest: null, previewFingerprint: "",
        runID: "", jobID: "", port: 0,
        serverID: "",
        error: "", groupID,
        groupLabel: groupLabel(group),
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

  function recordPreview(item, value, request, fingerprint = "") {
    const hash = runSpecHash(value);
    if (!hash) throw new Error("运行配置预览响应缺少有效 RunSpec 哈希");
    item.phase = "frozen";
    item.runSpecHash = hash;
    item.previewRunSpecHash = hash;
    item.previewRequest = request ? clone(request) : null;
    item.previewFingerprint = fingerprint;
    // Preview endpoints deliberately do not create a durable ResearchRun.
    // Keep the returned immutable projection with this task so the overlay
    // can render it without asking the persistence endpoint for a row that
    // does not exist yet.
    item.runSpecRecord = previewRecord(value, hash);
    item.port = Number(value.port || item.port || 0);
    item.serverID = String(
      value.server_id || value.execution_server_id || item.serverID || "",
    ).trim();
    item.portQuery = routeQuery(item);
    item.error = "";
    return item;
  }

  function previewMatches(item, state, group) {
    return Boolean(
      item?.phase === "frozen"
      && item.previewRequest
      && item.previewRunSpecHash
      && item.previewFingerprint === inputFingerprint(state, group),
    );
  }

  function invalidatePreview(item) {
    if (!item) return item;
    item.previewRunSpecHash = "";
    item.previewRequest = null;
    item.previewFingerprint = "";
    item.runSpecHash = "";
    item.runSpecRecord = null;
    return item;
  }

  function runSpecHash(value) {
    const candidates = [
      value?.run_spec_hash,
      value?.run?.run_spec_hash,
      value?.run_spec?.run_spec_hash,
      value?.report_projection?.run_spec_hash,
      value?.report_projection?.run_spec?.run_spec_hash,
      value?.report_projection?.run_spec?.target_ref,
      value?.target_ref,
    ];
    for (const candidate of candidates) {
      const match = String(candidate || "").match(
        /(?:sha256:)?([a-f0-9]{64})$/i,
      );
      if (match) return match[1].toLowerCase();
    }
    return "";
  }

  function previewRecord(value, hash = runSpecHash(value)) {
    const projection = value?.report_projection?.run_spec;
    const runSpec = value?.run_spec || projection?.complete_parameters;
    if (!runSpec || typeof runSpec !== "object" || Array.isArray(runSpec)) {
      return null;
    }
    return {
      run_spec_hash: hash,
      run_spec_version: value?.run_spec_version
        ?? projection?.run_spec_version ?? runSpec.run_spec_version ?? "",
      configuration_id: value?.configuration_id
        ?? runSpec.configuration_id ?? "",
      configuration_revision: value?.configuration_revision
        ?? runSpec.configuration_revision ?? "",
      alias_zh: value?.alias_zh || projection?.alias_zh || "",
      summary_zh: value?.summary_zh || projection?.summary_zh || "",
      run_spec: runSpec,
    };
  }

  function assertPreviewMatch(item, value) {
    const expected = String(item?.previewRunSpecHash || "").toLowerCase();
    if (!expected) return runSpecHash(value);
    const actual = runSpecHash(value);
    if (!actual) {
      throw new Error("正式任务响应缺少 RunSpec 哈希，无法验证与预览一致");
    }
    if (actual !== expected) {
      throw new Error("正式任务 RunSpec 与预览不一致，请重新生成运行配置");
    }
    return actual;
  }

  function clearPreviewRequest(item) {
    item.previewRunSpecHash = "";
    item.previewRequest = null;
    item.previewFingerprint = "";
  }

  function recordSubmission(item, value) {
    const job = value.jobs?.[0];
    if (!job?.job_id) throw new Error("任务提交响应缺少 Job ID");
    const submittedHash = assertPreviewMatch(item, value);
    item.phase = "submitted";
    item.progressStreamClosed = false;
    item.jobID = String(job.job_id);
    item.runID = String(value.run?.run_id || value.run_id || job.run_id || "");
    item.runSpecHash = submittedHash || String(
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
    clearPreviewRequest(item);
    return item;
  }

  function recordLocalSubmission(item, value) {
    const runID = String(value.run_id || value.run?.run_id || "");
    if (!runID) throw new Error("本地运行响应缺少运行 ID");
    const submittedHash = assertPreviewMatch(item, value);
    item.phase = String(value.phase || "submitted");
    item.runID = runID;
    item.jobID = "";
    item.port = 0;
    item.serverID = "";
    item.portQuery = "";
    item.artifactQuery = "";
    item.resultAutoRefreshStarted = false;
    item.runSpecHash = submittedHash || String(
      value.run_spec_hash || value.run?.run_spec_hash || item.runSpecHash || "",
    ).replace(/^sha256:/, "");
    item.local = true;
    item.error = "";
    clearPreviewRequest(item);
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
    BACKTEST_TASK_ID, PHASE_LABELS, backtestStrategyGroups, groupIdentity, groupLabel,
    clone, errorDetail, inputFingerprint, itemFor, invalidatePreview, jobPath, previewMatches,
    previewRecord, recordPreview, runSpecHash,
    recordSubmission, recordLocalSubmission, routeQuery, runSpecPath, runSpecTarget,
    synchronize, taskGroups, update,
  });
})();
