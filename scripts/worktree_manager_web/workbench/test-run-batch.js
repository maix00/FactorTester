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

  function runRequest(state) {
    return {
      workspace_id: state.workspace.workspace_id,
      configuration_revision: state.workspace.configuration?.revision,
      analyses: [state.kind],
      ...FTTestRunFields.requestBody(state),
      ...FTTestInputState.requestBody(state),
    };
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
    return FTReferencePage.routeFor(
      "run-spec", `runspec:sha256:${item.runSpecHash}`, "运行配置",
    );
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

  async function previewOne(context, state, group, refresh) {
    const item = itemFor(state, group);
    update(item, "freezing", refresh);
    try {
      const configuration = await FTTestConfiguration.save(context, state, group);
      const value = await context.api(context.servicePath("/api/runs/preview"), {
        method: "POST",
        body: JSON.stringify({...runRequest(state), configuration_revision: configuration.revision}),
      });
      recordPreview(item, value);
      refresh?.();
      return true;
    } catch (error) {
      item.phase = "failed";
      item.error = error.message || String(error);
      refresh?.();
      return false;
    }
  }

  async function runOne(context, state, group, refresh) {
    const item = itemFor(state, group);
    state.activeRunGroupID = item.groupID;
    update(item, "submitting", refresh);
    try {
      const configuration = await FTTestConfiguration.save(context, state, group);
      const value = await context.api(context.servicePath("/api/runs"), {
        method: "POST",
        body: JSON.stringify({...runRequest(state), configuration_revision: configuration.revision}),
      });
      recordSubmission(item, value);
      refresh?.();
      return true;
    } catch (error) {
      item.phase = "failed";
      item.error = error.message || String(error);
      refresh?.();
      return false;
    }
  }

  async function previewAll(context, state, refresh) {
    for (const group of FTTestProducts.selectedGroups(state)) {
      await previewOne(context, state, group, refresh);
    }
    return synchronize(state);
  }

  async function runAll(context, state, refresh) {
    for (const group of FTTestProducts.selectedGroups(state)) {
      await runOne(context, state, group, refresh);
    }
    return synchronize(state);
  }

  function link(context, label, path) {
    if (!path) return document.createTextNode("—");
    const anchor = document.createElement("a");
    anchor.href = path;
    anchor.textContent = context.t(label);
    anchor.addEventListener("click", event => {
      event.preventDefault();
      context.navigate(path);
    });
    return anchor;
  }

  function panel(context, state, item, group, refresh) {
    const root = document.createElement("article");
    root.className = "test-run-panel";
    const heading = document.createElement("header");
    const title = document.createElement("div");
    const name = document.createElement("strong"); name.textContent = item.groupLabel;
    const identity = document.createElement("small"); identity.textContent = item.groupID;
    title.append(name, identity);
    const status = document.createElement("span");
    status.className = `test-run-status ${item.phase}`;
    status.textContent = context.t(PHASE_LABELS[item.phase] || item.phase);
    heading.append(title, status);

    const details = document.createElement("dl");
    const values = [
      [context.t("运行配置"), link(context, "查看运行配置", runSpecPath(item))],
      [context.t("测试任务"), link(context, "查看测试任务", jobPath(item))],
    ];
    values.forEach(([label, value]) => {
      const term = document.createElement("dt"); term.textContent = label;
      const definition = document.createElement("dd"); definition.append(value);
      details.append(term, definition);
    });
    if (item.runSpecHash) details.title = item.runSpecHash;

    const actions = document.createElement("div"); actions.className = "test-run-card-actions";
    const preview = context.button(context.t("预览冻结配置"), () => (
      previewOne(context, state, group, refresh)
    ));
    const submit = context.button(context.t("运行测试"), () => (
      runOne(context, state, group, refresh)
    ));
    const busy = ["freezing", "submitting"].includes(item.phase);
    preview.disabled = busy; submit.disabled = busy;
    actions.append(preview, submit);
    root.append(heading, details, actions);
    if (item.error) {
      const error = document.createElement("p");
      error.className = "test-run-error"; error.textContent = item.error;
      root.append(error);
    }
    root.append(FTTestRunResults.render(context, state, item, refresh));
    return root;
  }

  function tabBar(context, state, items, refresh) {
    const root = document.createElement("div");
    root.className = "test-run-tabs";
    items.forEach(item => {
      const button = document.createElement("button");
      button.type = "button";
      button.classList.toggle("active", item.groupID === state.activeRunGroupID);
      const name = document.createElement("span"); name.textContent = item.groupLabel;
      const status = document.createElement("small");
      status.textContent = context.t(PHASE_LABELS[item.phase] || item.phase);
      button.append(name, status);
      button.addEventListener("click", () => {
        state.activeRunGroupID = item.groupID;
        refresh?.();
      });
      root.append(button);
    });
    return root;
  }

  function render(context, state, refresh) {
    const groups = FTTestProducts.selectedGroups(state);
    const items = synchronize(state);
    const root = document.createElement("section"); root.className = "test-run-batch";
    const heading = document.createElement("div"); heading.className = "section-heading";
    const copy = document.createElement("div");
    const title = document.createElement("h2"); title.textContent = context.t("产品路径任务");
    const description = document.createElement("p");
    description.textContent = context.t("每个产品组冻结独立 RunSpec，并保留对应测试任务入口");
    copy.append(title, description);
    const actions = document.createElement("div"); actions.className = "test-run-batch-actions";
    actions.append(
      context.button(context.t("全部预览"), () => previewAll(context, state, refresh)),
      context.button(context.t("全部运行"), () => runAll(context, state, refresh)),
    );
    heading.append(copy, actions); root.append(heading);
    const matrix = FTTestRunResults.planSummary(context, state);
    if (matrix) root.append(matrix);
    if (!groups.length) {
      root.append(FTUI.empty(context.t("尚未选择产品组"), context.t("请先在测试对象中选择产品组")));
      return root;
    }
    root.append(tabBar(context, state, items, refresh));
    const activeIndex = Math.max(0, items.findIndex(item => (
      item.groupID === state.activeRunGroupID
    )));
    root.append(panel(context, state, items[activeIndex], groups[activeIndex], refresh));
    return root;
  }

  window.FTTestRunBatch = Object.freeze({
    jobPath, previewAll, previewOne, recordPreview, recordSubmission, render,
    runAll, runOne, runSpecPath, synchronize,
  });
})();
