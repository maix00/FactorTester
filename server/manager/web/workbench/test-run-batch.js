(() => {
  const model = () => window.FTTestRunBatchModel;

  function ensureActions(state, refresh) {
    if (window.FTTestRunBatchActions) {
      return Promise.resolve(window.FTTestRunBatchActions);
    }
    const load = window.FTTestLazyCode?.ensureRunBatchActionsCode;
    if (!load) return Promise.reject(new Error("任务提交动作加载器不可用"));
    return load(state, refresh).then(() => window.FTTestRunBatchActions);
  }

  function invokeAction(name, args) {
    return ensureActions(args[1], args[3]).then(actions => actions[name](...args));
  }

  function ensureResultCode(state, item, refresh) {
    if (window.FTTestRunResults) return Promise.resolve(true);
    if (!item.resultCodePromise) {
      item.resultCodeLoading = true;
      item.resultCodePromise = Promise.resolve(
        window.FTStaticLoader?.loadGroups?.(["workbench-run-results"]),
      )
        .then(() => {
          if (!window.FTTestRunResults) throw new Error("结果查看器不可用");
          return true;
        })
        .catch(error => {
          item.resultError = error.message || String(error);
          return false;
        })
        .finally(() => {
          item.resultCodeLoading = false;
          refresh?.();
        });
    }
    return item.resultCodePromise;
  }

  function resultPanel(context, state, item, refresh) {
    if (!window.FTTestRunResults) {
      if (item.jobID) void ensureResultCode(state, item, refresh);
      const root = document.createElement("div");
      if (!item.jobID) return root;
      root.className = "test-run-inline-results";
      root.append(item.resultError
        ? FTUI.empty(context.t("读取结果失败"), item.resultError)
        : FTUI.loading(context.t("正在读取结果查看器…")));
      return root;
    }
    return FTTestRunResults.render(context, state, item, refresh);
  }

  // Keep the public batch interface stable while deferring the execution
  // implementation.  Loading the view never loads compiler, source, or
  // submission code; these wrappers are the only action seam.
  function previewOne(...args) { return invokeAction("previewOne", args); }
  function previewAll(...args) { return invokeAction("previewAll", args); }
  function runOne(...args) { return invokeAction("runOne", args); }
  function runAll(...args) { return invokeAction("runAll", args); }
  function synchronize(...args) { return model().synchronize(...args); }
  function recordPreview(...args) { return model().recordPreview(...args); }
  function recordSubmission(...args) { return model().recordSubmission(...args); }
  function runSpecPath(...args) { return model().runSpecPath(...args); }
  function jobPath(...args) { return model().jobPath(...args); }

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
    status.textContent = context.t(model().PHASE_LABELS[item.phase] || item.phase);
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
      invokeAction("previewOne", [context, state, group, refresh])
    ));
    const submit = context.button(context.t("运行测试"), () => (
      invokeAction("runOne", [context, state, group, refresh])
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
    root.append(resultPanel(context, state, item, refresh));
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
      status.textContent = context.t(model().PHASE_LABELS[item.phase] || item.phase);
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
    const products = window.FTTestProducts;
    if (!products) return null;
    const groups = products.selectedGroups(state);
    if (!groups.length) return null;
    const items = model().synchronize(state);
    const activeIndex = Math.max(0, items.findIndex(item => (
      item.groupID === state.activeRunGroupID
    )));
    const activeItem = items[activeIndex];
    const activeGroup = groups[activeIndex];
    const root = document.createElement("section"); root.className = "test-run-batch";
    const heading = document.createElement("div"); heading.className = "section-heading";
    const copy = document.createElement("div");
    const title = document.createElement("h2"); title.textContent = context.t("产品路径任务");
    const description = document.createElement("p");
    description.textContent = context.t("每个产品组冻结独立 RunSpec，并保留对应测试任务入口");
    copy.append(title, description);
    const actions = document.createElement("div"); actions.className = "test-run-batch-actions";
    const runSpecButton = context.button(context.t("查看 RunSpec"), () => {
      const path = runSpecPath(activeItem);
      if (path) context.navigate(path);
      else void previewOne(context, state, activeGroup, refresh);
    });
    runSpecButton.title = context.t("查看当前产品组冻结的 RunSpec；尚未冻结时先生成 RunSpec");
    const runButton = context.button(context.t("运行"), () => (
      invokeAction("runOne", [context, state, activeGroup, refresh])
    ));
    runButton.title = context.t("运行当前选中的产品组任务");
    runButton.disabled = !activeGroup || ["freezing", "submitting"].includes(
      activeItem?.phase,
    );
    const previewAllButton = context.button(
      context.t("全部预览"), () => previewAll(context, state, refresh),
    );
    const runAllButton = context.button(context.t("全部运行"), () => invokeAction(
      "runAll", [context, state, refresh],
    ));
    previewAllButton.disabled = !groups.length;
    runAllButton.disabled = !groups.length;
    actions.append(runSpecButton, runButton, previewAllButton, runAllButton);
    heading.append(copy, actions); root.append(heading);
    const matrix = FTTestRunSummary?.planSummary?.(context, state);
    if (matrix) root.append(matrix);
    root.append(tabBar(context, state, items, refresh));
    root.append(panel(context, state, activeItem, activeGroup, refresh));
    return root;
  }

  window.FTTestRunBatch = Object.freeze({
    jobPath, previewAll, previewOne, recordPreview, recordSubmission, render,
    runAll, runOne, runSpecPath, synchronize,
  });
})();
