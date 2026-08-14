(() => {
  function loadGroup(group) {
    return group && window.FTStaticLoader?.loadGroups
      ? window.FTStaticLoader.loadGroups([group]) : Promise.resolve();
  }

  function codeGroupForTab(tab) {
    return {
      factor_selection: "workbench-factors",
      product_path_selection: "workbench-products",
      category_selection: "workbench-products",
      test_templates: "workbench-templates",
    }[String(tab?.content_adapter || "")];
  }

  function groupID(value) {
    return window.FTTestProducts?.groupID?.(value)
      || value?.group_ref || value?.product_group_ref || value?.id
      || value?.product_group_template_id || value?.product_path_selection_id || "";
  }

  function fallbackGroupReferences(analysis = {}, ui = {}) {
    const values = [
      ...(ui.product_group_refs || []), ...(analysis.product_path_selections || []),
      ...(analysis.local_settings?.product_path_selections || []),
      analysis.product_path_selection, analysis.product_path_selection_id,
      analysis.local_settings?.product_group_ref, ui.product_group_ref,
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
    codeGroupForTab, deferredPanel, fallbackGroupReferences, groupID, loadGroup,
  });
})();
