(() => {
  function loadGroup(group) {
    return group && window.FTStaticLoader?.loadGroups
      ? window.FTStaticLoader.loadGroups([group]) : Promise.resolve();
  }

  function ensureGroupCode(state, key, group, onReady, refresh) {
    const record = state[key] || (state[key] = {
      status: "idle", error: "", promise: null,
    });
    if (record.status === "ready") return Promise.resolve();
    if (record.status === "loading" && record.promise) return record.promise;
    if (record.status === "error") return Promise.resolve();
    record.status = "loading";
    record.error = "";
    record.promise = loadGroup(group)
      .then(() => {
        onReady?.();
        record.status = "ready";
        refresh?.();
      })
      .catch(error => {
        record.status = "error";
        record.error = error.message || String(error);
        refresh?.();
      });
    return record.promise;
  }

  function hasSelectedProductPaths(state) {
    return Boolean(
      state.groupRefs?.length || state.groupRef
      || window.FTTestProducts?.selectedGroups?.(state)?.length,
    );
  }

  function ensureRunBatchCode(state, refresh) {
    if (window.FTTestRunBatch) return Promise.resolve();
    return ensureGroupCode(state, "runBatchCode", "workbench-run-batch", null, refresh);
  }

  function ensureRunBatchActionsCode(state, refresh) {
    if (window.FTTestRunBatchActions) return Promise.resolve();
    return ensureGroupCode(
      state, "runBatchActionsCode", "workbench-run-batch-actions", null, refresh,
    ).then(() => {
      if (!window.FTTestRunBatchActions) throw new Error("任务提交动作不可用");
    });
  }

  function codeGroupForTab(tab) {
    return {
      factor_selection: "workbench-factors",
      product_path_selection: "workbench-products",
      category_selection: "workbench-products",
      test_templates: "workbench-templates",
      run_inputs: "workbench-source-inputs",
    }[String(tab?.content_adapter || "")];
  }

  function groupID(value) {
    if (typeof value === "string") return value;
    return window.FTTestProducts?.groupID?.(value)
      || value?.group_ref || value?.product_group_ref || value?.id
      || value?.product_group_template_id || value?.product_path_selection_id || "";
  }

  function fallbackGroupReferences(analysis = {}, ui = {}) {
    const groupedRefs = (analysis.configuration_groups || [])
      .map(item => item?.product_scope_ref).filter(Boolean);
    const frozenSelections = analysis.product_selections || {};
    const values = [
      ...(ui.product_group_refs || []), ...(analysis.product_path_selections || []),
      ...groupedRefs, ...Object.keys(frozenSelections), ...Object.values(frozenSelections),
      ...(analysis.execution?.settings?.product_path_selections || []),
      analysis.product_path_selection, analysis.product_path_selection_id,
      analysis.execution?.settings?.product_group_ref, ui.product_group_ref,
    ];
    return [...new Set(values.map(groupID).filter(Boolean))];
  }

  function deferredPanel(context, state, title, group, refresh) {
    const root = document.createElement("section");
    root.className = "test-code-deferred-panel";
    const heading = document.createElement("strong"); heading.textContent = context.t(title);
    const note = document.createElement("small");
    note.textContent = context.t("打开后读取此设置代码");
    const action = context.button(context.t("打开设置"), async () => {
      action.disabled = true;
      try {
        await loadGroup(group);
        window.FTBacktestGroups?.initialize?.(state);
        refresh?.();
      } catch (error) {
        action.disabled = false;
        note.textContent = error.message || String(error);
      }
    });
    root.append(heading, note, action);
    return root;
  }

  window.FTTestLazyCode = Object.freeze({
    codeGroupForTab, deferredPanel, ensureGroupCode, ensureRunBatchActionsCode,
    ensureRunBatchCode,
    fallbackGroupReferences, groupID, hasSelectedProductPaths, loadGroup,
  });
})();
