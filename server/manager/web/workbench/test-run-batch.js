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

  function selectedTasks(state) {
    const products = window.FTTestProducts;
    if (!products?.selectedGroups) {
      return [];
    }
    const groups = products.selectedGroups(state);
    const items = model().synchronize(state);
    const byID = new Map(items.map(item => [item.groupID, item]));
    return groups.map(group => ({group, item: byID.get(model().groupIdentity(group))}))
      .filter(entry => entry.item);
  }

  function headerActions(context, state, refresh) {
    const tasks = selectedTasks(state || {});
    const hasTasks = tasks.length > 0;
    const runSpecButton = context.button(context.t("查看运行配置"), () => {
      if (!hasTasks) return;
      void openRunSpecs(context, state, refresh);
    }, context.t("查看各任务对应的冻结运行配置；尚未冻结时先生成运行配置"));
    runSpecButton.className = "test-workbench-header-action";
    runSpecButton.disabled = !hasTasks;
    runSpecButton.title = hasTasks
      ? context.t("查看各任务对应的冻结运行配置；尚未冻结时先生成运行配置")
      : context.t("请先选择产品组");

    const runButton = context.button(context.t("运行"), () => {
      if (hasTasks) void invokeAction("runAll", [context, state, refresh]);
    }, context.t("运行当前测试配置下的全部任务"));
    runButton.className = "test-workbench-header-action";
    runButton.disabled = !hasTasks || tasks.some(({item}) => (
      ["freezing", "submitting"].includes(item.phase)
    ));
    runButton.title = hasTasks
      ? context.t("运行当前测试配置下的全部任务")
      : context.t("请先选择产品组");
    return [runSpecButton, runButton];
  }

  async function openRunSpecs(context, state, refresh) {
    const tasks = selectedTasks(state);
    for (const {group, item} of tasks) {
      if (model().runSpecPath(item)) continue;
      const completed = await previewOne(context, state, group, refresh);
      if (!completed) continue;
    }
    const entries = selectedTasks(state).map(({item}, index) => {
      const target = model().runSpecTarget(item);
      if (!target) return null;
      const groupLabel = item.groupLabel || item.groupID || "";
      return {
        target,
        serverID: item.serverID || "",
        label: `${context.t("任务")} ${index + 1} · ${groupLabel}`,
        subtitle: item.jobID
          ? `${context.t("测试任务")} ${item.jobID}` : context.t("尚未提交"),
      };
    }).filter(Boolean);
    if (!entries.length) return false;
    if (!window.FTRunSpecView?.openMany) {
      await window.FTStaticLoader?.loadGroups?.(["research"]);
    }
    if (window.FTRunSpecView?.openMany) {
      window.FTRunSpecView.openMany(context, entries);
    } else if (window.FTRunSpecView?.open) {
      window.FTRunSpecView.open(context, entries[0].target, entries[0].serverID);
    } else {
      context.navigate(model().runSpecPath(selectedTasks(state)[0].item));
    }
    return true;
  }
  function jobPath(...args) { return model().jobPath(...args); }

  window.FTTestRunBatch = Object.freeze({
    headerActions, jobPath, previewAll, previewOne, recordPreview, recordSubmission,
    runAll, runOne, runSpecPath, synchronize,
  });
})();
