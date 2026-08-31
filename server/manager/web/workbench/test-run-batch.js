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
    return model().taskEntries(state);
  }

  function headerActions(context, state, refresh) {
    const tasks = selectedTasks(state || {});
    const hasTasks = tasks.length > 0;
    const runSpecButton = context.button(context.t("查看运行配置"), () => {
      const currentTasks = selectedTasks(state || {});
      if (!currentTasks.length) {
        showRunSpecError(context, new Error(missingScopeMessage(context, state)));
        return;
      }
      runSpecButton.disabled = true;
      runButton.disabled = true;
      // This action crosses several deferred code and API boundaries.  Do not
      // leave a rejected Promise unobserved: after the old batch panel was
      // removed there is no lower task row to display preview failures.
      void openRunSpecs(context, state, refresh).catch(error => {
        showRunSpecError(context, error);
      }).finally(() => {
        // Content refreshes may rebuild the batch while header actions remain
        // mounted. Restore both controls from the current model explicitly;
        // otherwise a successful preview can leave “运行” permanently
        // disabled until the entire page is reloaded.
        runSpecButton.disabled = false;
        const current = selectedTasks(state || {});
        runButton.disabled = !current.length || current.some(({item}) => (
          ["freezing", "submitting"].includes(item.phase)
        ));
      });
    }, context.t("查看各任务对应的冻结运行配置；尚未冻结时先生成运行配置"));
    runSpecButton.className = "test-workbench-header-action";
    // Keep this action clickable so a missing selection is explained in the
    // page notice instead of looking like a dead button.
    runSpecButton.disabled = false;
    runSpecButton.title = hasTasks
      ? context.t("查看各任务对应的冻结运行配置；尚未冻结时先生成运行配置")
      : missingScopeMessage(context, state);

    const runButton = context.button(context.t("运行"), () => {
      const currentTasks = selectedTasks(state || {});
      if (!currentTasks.length) {
        showRunError(context, new Error(missingScopeMessage(context, state)));
        return;
      }
      runButton.disabled = true;
      context.showNotice?.(context.t("正在提交测试任务…"));
      void invokeAction("runAll", [context, state, refresh])
        .then(items => {
          const failures = (Array.isArray(items) ? items : [])
            .filter(item => item.error)
            .map(item => `${item.groupLabel || item.groupID}: ${item.error}`);
          if (failures.length) showRunError(context, new Error(failures.join("；")));
          else context.showNotice?.("");
        })
        .catch(error => {
          showRunError(context, error);
        })
        .finally(() => {
          // Header controls are not recreated by every content refresh.  The
          // button therefore owns its pending lifecycle and must never stay
          // disabled after a rejected service submission (for example 507).
          runButton.disabled = selectedTasks(state || {}).some(({item}) => (
            ["freezing", "submitting"].includes(item.phase)
          ));
        });
    }, context.t("运行当前测试配置下的全部任务"));
    runButton.className = "test-workbench-header-action";
    runButton.disabled = !hasTasks || tasks.some(({item}) => (
      ["freezing", "submitting"].includes(item.phase)
    ));
    runButton.title = hasTasks
      ? context.t("运行当前测试配置下的全部任务")
      : missingScopeMessage(context, state);
    const clearButton = context.button(context.t("清空"), () => {
      void Promise.resolve(
        window.FTTests?.clearDraft?.(context, state, refresh),
      ).catch(error => {
        context.showNotice?.(`${context.t("清空测试配置失败")}: ${error.message}`, true);
      });
    }, context.t("清空当前测试配置，不删除模板、已提交任务或生成物"));
    clearButton.className = "test-workbench-header-action";
    return [runSpecButton, runButton, clearButton];
  }

  function missingScopeMessage(context, state) {
    if (state?.kind === "backtest") {
      return context.t("请先在策略组设置中为策略选择产品组");
    }
    if (state?.kind === "ic") return context.t("请先新增并填写配置组");
    return context.t("请先选择产品组");
  }

  function showRunSpecError(context, error) {
    const detail = model().errorDetail(error);
    context.showNotice?.(`${context.t("读取运行配置失败")}: ${detail}`, true);
  }

  function showRunError(context, error) {
    const detail = model().errorDetail(error);
    context.showNotice?.(`${context.t("运行测试失败")}: ${detail}`, true);
  }

  function taskError(item) {
    return item?.error ? String(item.error) : "";
  }

  async function openRunSpecs(context, state, refresh) {
    const tasks = selectedTasks(state);
    const failures = [];
    const resolved = [];
    context.showNotice?.(context.t("正在准备运行配置…"));
    for (const {group, item} of tasks) {
      if (model().previewMatches(item, state, group)) {
        resolved.push(item);
        continue;
      }
      try {
        model().invalidatePreview(item);
        const frozen = await previewOne(context, state, group, refresh);
        const current = frozen || model().itemFor(state, group) || item;
        if (model().runSpecTarget(current)) resolved.push(current);
        else failures.push({current, error: taskError(current)});
      } catch (error) {
        const current = model().itemFor(state, group) || item;
        current.phase = "failed";
        current.error = model().errorDetail(error);
        refresh?.();
        failures.push({current, error: current.error});
      }
    }
    const entries = resolved.map((item, index) => {
      const target = model().runSpecTarget(item);
      if (!target) return null;
      const groupLabel = item.groupLabel || item.groupID || "";
      return {
        target,
        serverID: item.serverID || "",
        value: item.runSpecRecord || null,
        label: `${context.t("任务")} ${index + 1} · ${groupLabel}`,
        subtitle: item.jobID
          ? `${context.t("测试任务")} ${item.jobID}` : context.t("尚未提交"),
      };
    }).filter(Boolean);
    if (!entries.length) {
      const detail = failures
        .map(({current, error}) => `${current.groupLabel || current.groupID}: ${error || context.t("未生成运行配置")}`)
        .join("；");
      showRunSpecError(context, new Error(detail || context.t("尚未生成可查看的运行配置")));
      return false;
    }
    if (!window.FTRunSpecView?.openMany) {
      await window.FTStaticLoader?.loadGroups?.(["research-reference"]);
    }
    if (window.FTRunSpecView?.openMany) {
      window.FTRunSpecView.openMany(context, entries);
    } else if (window.FTRunSpecView?.open) {
      window.FTRunSpecView.open(context, entries[0].target, entries[0].serverID);
    } else {
      context.navigate(FTReferencePage.routeFor(
        "run-spec", entries[0].target, context.t("运行配置"), entries[0].serverID,
      ));
    }
    if (failures.length) {
      const detail = failures
        .map(({current, error}) => `${current.groupLabel || current.groupID}: ${error || context.t("未生成运行配置")}`)
        .join("；");
      showRunSpecError(context, new Error(`${context.t("部分任务无法读取运行配置")}: ${detail}`));
    } else {
      context.showNotice?.("");
    }
    return true;
  }
  function jobPath(...args) { return model().jobPath(...args); }

  function ensureResultCode(state, item, refresh) {
    if (window.FTTestRunResults) return Promise.resolve(true);
    if (!item.resultBridgePromise) {
      item.resultCodeLoading = true;
      item.resultBridgePromise = Promise.resolve(
        window.FTTestLazyCode?.loadGroup?.("workbench-run-results"),
      )
        .then(() => {
          if (!window.FTTestRunResults) throw new Error("结果查看器不可用");
          return true;
        })
        .catch(error => {
          item.resultError = error.message || String(error);
          item.resultBridgePromise = null;
          return false;
        })
        .finally(() => {
          item.resultCodeLoading = false;
          refresh?.();
        });
    }
    return item.resultBridgePromise;
  }

  function resultPanel(context, state, item, refresh) {
    if (window.FTTestRunResults) {
      return window.FTTestRunResults.render(context, state, item, refresh);
    }
    const root = document.createElement("div");
    root.className = "test-run-inline-results";
    void ensureResultCode(state, item, refresh);
    root.append(item.resultError
      ? FTUI.empty(context.t("读取结果失败"), item.resultError)
      : FTUI.loading(context.t("正在读取结果查看器…")));
    return root;
  }

  function submittedItems(state) {
    return model().taskEntries(state, {submittedOnly: true})
      .map(entry => entry.item);
  }

  function renderSubmitted(context, state, refresh) {
    const entries = model().resultEntries(state);
    const selected = model().activeResultEntry(state, entries);
    if (!selected) return null;
    const items = entries.map(entry => entry.item);
    const active = selected.item;
    const root = document.createElement("section");
    root.className = "test-run-observer";
    const heading = document.createElement("div");
    heading.className = "test-run-observer-heading";
    const title = document.createElement("strong");
    title.textContent = context.t("测试任务");
    const actions = document.createElement("div");
    actions.className = "test-run-observer-actions";
    const path = jobPath(active);
    const viewJob = context.button(context.t("查看测试任务"), () => {
      if (path) context.navigate(path);
    }, context.t(path ? "查看测试任务" : "测试任务尚未生成 Job ID"));
    viewJob.disabled = !path;
    actions.append(viewJob);
    const cancel = window.FTJobActions?.cancelButton?.(context, {
      job: {
        ...(active.job || {}),
        status: ["succeeded", "failed", "cancelled"].includes(active.phase)
          ? active.phase
          : active.lifecycleStatus || active.job?.status || active.phase,
        cancel_requested: active.cancelRequested || active.job?.cancel_requested,
      },
      jobID: active.jobID,
      portQuery: active.portQuery || "",
      onAccepted: () => {
        active.cancelRequested = true;
        refresh?.();
      },
      onRefresh: () => window.FTTestRunResults?.refresh(
        context, state, active, refresh,
      ),
    });
    if (cancel) actions.append(cancel);
    heading.append(title, actions);
    root.append(heading);
    if (items.length > 1) {
      const tabs = document.createElement("div");
      tabs.className = "test-run-tabs";
      items.forEach(item => {
        const button = document.createElement("button");
        button.type = "button";
        button.classList.toggle("active", item.jobID === active.jobID);
        const name = document.createElement("span");
        name.textContent = item.groupLabel;
        const status = document.createElement("small");
        status.textContent = context.t(model().PHASE_LABELS[item.phase] || item.phase);
        button.append(name, status);
        button.addEventListener("click", () => {
          state.activeResultJobID = item.jobID;
          refresh?.();
        });
        tabs.append(button);
      });
      root.append(tabs);
    }
    if (active.error) {
      const error = document.createElement("p");
      error.className = "test-run-error";
      error.textContent = active.error;
      root.append(error);
    }
    root.append(resultPanel(context, state, active, refresh));
    return root;
  }

  window.FTTestRunBatch = Object.freeze({
    headerActions, jobPath, previewAll, previewOne, recordPreview, recordSubmission,
    renderSubmitted, runAll, runOne, runSpecPath, submittedItems, synchronize,
  });
})();
