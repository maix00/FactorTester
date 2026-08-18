(() => {
  // Candidate scope is deliberately kept separate from the form renderer.
  // The same resolver is used by backtest groups and IC configuration so an
  // editor cannot accidentally widen a user's visible factor/product range.
  function contract(state) {
    return state?.manifest?.strategy_editor || {};
  }

  function mounted(state, tabKey) {
    return Array.isArray(state?.settingsMountedTabs)
      && state.settingsMountedTabs.includes(tabKey);
  }

  function arrayValue(value) {
    if (Array.isArray(value)) return value;
    if (value === undefined || value === null || value === "") return [];
    return [value];
  }

  function fieldValues(state, fields) {
    const values = state?.values || {};
    for (const key of fields || []) {
      const value = values[key];
      if (Array.isArray(value) && value.length) return value;
      if (value !== undefined && value !== null && value !== "") return [value];
    }
    return [];
  }

  function factorID(value) {
    if (typeof value === "string") return value;
    return value?.factor_ref || value?.target_ref || value?.factor_alias
      || value?.alias || value?.id || "";
  }

  function factorLabel(value) {
    if (typeof value === "string") return value;
    return value?.factor_alias || value?.alias || value?.name || factorID(value);
  }

  function groupID(value) {
    if (typeof value === "string") return value;
    return window.FTTestProducts?.groupID?.(value)
      || value?.group_ref || value?.product_group_ref || value?.id || "";
  }

  function groupLabel(value) {
    if (typeof value === "string") return value;
    return window.FTTestProducts?.groupLabel?.(value)
      || value?.title_zh || value?.name || value?.label || groupID(value);
  }

  function mergeByID(kind, values) {
    const result = new Map();
    for (const value of values || []) {
      const id = kind === "factor" ? factorID(value) : groupID(value);
      if (id) {
        const previous = result.get(String(id));
        result.set(String(id), previous && typeof value === "object"
          ? {...previous, ...value} : value);
      }
    }
    return [...result.values()];
  }

  function visibleCatalog(state, kind) {
    if (kind === "factor") {
      return mergeByID("factor", [
        ...(state?.factors || []),
        ...(state?.savedFactors || []),
        ...(state?.values?.factor_candidates || []),
        ...(state?.values?.factor_selections || []),
      ]);
    }
    return mergeByID("product_group", [
      ...(state?.groups || []),
      ...(state?.values?.product_path_candidates || []),
      ...(state?.values?.product_path_selections || []),
    ]);
  }

  function outerValues(state, kind) {
    const rule = contract(state).outer_scope_tabs?.[kind] || {};
    const selected = fieldValues(state, rule.selection_fields);
    const catalog = visibleCatalog(state, kind);
    const byID = new Map(catalog.map(item => [
      String(kind === "factor" ? factorID(item) : groupID(item)), item,
    ]));
    const resolved = selected.map(value => {
      const id = kind === "factor" ? factorID(value) : groupID(value);
      return byID.get(String(id)) || value;
    });
    // Candidate rows are not a selection.  If the outer tab is mounted but
    // its selected field is empty, the nested editor must stop and ask the
    // user to choose a value (or unmount the outer tab), even when the lazy
    // catalog has already loaded many candidates.
    return mergeByID(kind, resolved);
  }

  function scope(state, kind) {
    const rule = contract(state).outer_scope_tabs?.[kind] || {};
    const isOuter = mounted(state, rule.mounted_tab || kind);
    if (isOuter) {
      const items = outerValues(state, kind);
      return {
        kind, source: "outer", required: true, ready: items.length > 0,
        items, tabKey: rule.mounted_tab || kind,
      };
    }
    const items = visibleCatalog(state, kind);
    return {
      kind, source: "visible", required: false, ready: true,
      items, tabKey: rule.mounted_tab || kind,
    };
  }

  function validate(state, kinds = ["factor", "product_path_selection"]) {
    return kinds.map(kind => scope(state, kind)).filter(item => (
      item.required && !item.ready
    )).map(item => ({
      ...item,
      message: item.kind === "factor"
        ? "外层因子执行已挂载但尚未选择因子；请先设置或取消挂载"
        : "外层产品组已挂载但尚未选择产品组；请先设置或取消挂载",
    }));
  }

  function itemID(kind, value) {
    return String(kind === "factor" ? factorID(value) : groupID(value));
  }

  function itemLabel(kind, value) {
    return kind === "factor" ? factorLabel(value) : groupLabel(value);
  }

  function summary(context, state, kind) {
    const root = document.createElement("div");
    root.className = "strategy-editor-scope-summary";
    const current = scope(state, kind);
    const title = document.createElement("strong");
    title.textContent = context.t(kind === "factor" ? "因子候选范围" : "产品组候选范围");
    const note = document.createElement("small");
    note.textContent = current.required && !current.ready
      ? context.t("外层字段尚未设置")
      : `${context.t(current.source === "outer" ? "沿用外层选择" : "当前可见目录")}: ${current.items.length}`;
    root.append(title, note);
    return root;
  }

  function innerTabs(state, mountedTabs = []) {
    const config = contract(state);
    const defaults = Array.isArray(config.inner_default_tabs)
      ? config.inner_default_tabs : [];
    const outerOnly = new Set(config.outer_only_tabs || []);
    const result = [];
    const seen = new Set();
    const add = tab => {
      if (!tab?.key || seen.has(tab.key) || outerOnly.has(tab.key)) return;
      seen.add(tab.key); result.push(tab);
    };
    defaults.forEach(add);
    const values = state?.values || {};
    for (const tab of state?.manifest?.tab_lists?.["group-settings"] || []) {
      if (outerOnly.has(tab.key) || seen.has(tab.key)) continue;
      const fields = Object.entries(state?.manifest?.defaults || {})
        .filter(([key, field]) => field.tab_key === tab.key
          && field.scope_policy === "overridable"
          && field.execution_policy !== "authoring_only"
          && (!window.FTSettingRules || FTSettingRules.isVisible(field, values)));
      if (fields.length && mountedTabs.includes(tab.key)) add({
        key: tab.key, label: tab.label || tab.key, kind: "override",
      });
    }
    return result;
  }

  window.FTStrategyEditorScope = Object.freeze({
    contract, factorID, factorLabel, groupID, groupLabel, innerTabs,
    itemID, itemLabel, mounted, scope, summary, validate, visibleCatalog,
  });
})();
