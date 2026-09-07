(() => {
  // Candidate scope is deliberately kept separate from the form renderer.
  // The same resolver is used by backtest groups and IC configuration so an
  // editor cannot accidentally widen a user's visible factor/product range.
  function contract(state) {
    return state?.manifest?.strategy_editor || state?.strategy_editor || {};
  }

  function scopedField(stateOrManifest, key, side = "inner") {
    const entry = contract(stateOrManifest).scoped_fields?.[key];
    if (!entry?.[side]) return null;
    const {outer: _outer, inner: _inner, ...base} = entry;
    return {...base, ...entry[side], key};
  }

  function scopedFields(stateOrManifest, side = "inner") {
    const fields = contract(stateOrManifest).scoped_fields || {};
    return Object.fromEntries(Object.entries(fields).map(([key, value]) => [
      key, value?.[side] || {},
    ]));
  }

  function itemCount(value) {
    if (Array.isArray(value)) return value.length;
    if (value && typeof value === "object") return Object.keys(value).length;
    return value === undefined || value === null || value === "" ? 0 : 1;
  }

  function scopeConditionsMatch(conditions, values) {
    const fields = conditions?.field_values || {};
    if (!Object.entries(fields).every(([key, allowed]) => {
      const choices = Array.isArray(allowed) ? allowed : [allowed];
      return choices.some(value => String(value) === String(values?.[key]));
    })) return false;
    return Object.entries(conditions?.min_items || {}).every(([key, minimum]) => (
      itemCount(values?.[key]) >= Number(minimum || 0)
    ));
  }

  function fieldVisible(stateOrManifest, key, side, values = {}) {
    const descriptor = scopedField(stateOrManifest, key, side);
    return !descriptor || scopeConditionsMatch(descriptor.visible_when, values);
  }

  function fieldRequired(stateOrManifest, key, side, values = {}) {
    const descriptor = scopedField(stateOrManifest, key, side);
    if (!descriptor) return null;
    return scopeConditionsMatch(descriptor.required_when, values);
  }

  function fieldEditable(stateOrManifest, key, side) {
    const descriptor = scopedField(stateOrManifest, key, side);
    return !descriptor || descriptor.editable !== false;
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

  function sourceIDs(value) {
    if (Array.isArray(value)) return value.map(sourceID).filter(Boolean);
    if (value === undefined || value === null || value === "") return [];
    if (typeof value === "object") return [sourceID(value)].filter(Boolean);
    return String(value).split(",").map(item => item.trim()).filter(Boolean);
  }

  function sourceID(value) {
    if (value === undefined || value === null) return "";
    if (typeof value !== "object") return String(value).trim();
    return String(
      value.source_id || value.data_source_id || value.ref
      || value.id || value.value || "",
    ).trim();
  }

  function selectedSourceIDs(state) {
    const rule = contract(state).candidate_constraints?.product_path_candidates
      || contract(state).candidate_constraints?.category_candidates || {};
    return sourceIDs(state?.values?.[rule.source_field || "data_source"]);
  }

  function candidateSourceIDs(value) {
    return sourceIDs(value?.source_ids || value?.data_source_ids || value?.data_sources);
  }

  function candidateCompatible(state, fieldKey, candidate) {
    const rule = contract(state).candidate_constraints?.[fieldKey];
    if (!rule) return true;
    const values = state?.values || {};
    const selected = new Set(sourceIDs(values[rule.source_field]));
    const mode = String(values[rule.mode_field] || (selected.size ? "list" : rule.automatic_mode));
    if (mode === String(rule.automatic_mode || "auto")) return true;
    if (!selected.size) return false;
    const overlaps = value => {
      const ids = candidateSourceIDs(value);
      return ids.length > 0 && ids.some(id => selected.has(id));
    };
    const firstPopulated = values => values.find(value => Array.isArray(value) && value.length) || [];
    const pathSources = candidate?.path_sources || [];
    const members = rule.coverage === "complete_product_coverage"
      ? firstPopulated([candidate?.products, candidate?.product_records, pathSources])
      : firstPopulated([candidate?.path_sources, candidate?.items]);
    const comparable = members.filter(value => candidateSourceIDs(value).length > 0);
    if (members.length && comparable.length !== members.length) return false;
    return members.length ? members.every(overlaps) : overlaps(candidate);
  }

  function constrainedCandidates(state, fieldKey, values) {
    return (values || []).filter(value => candidateCompatible(state, fieldKey, value));
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
    return value?.ref || "";
  }

  function factorLabel(value) {
    if (typeof value === "string") return value;
    return value?.alias || factorID(value);
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

  function categoryID(value) {
    if (typeof value === "string") return value;
    return value?.id || value?.name || value?.label || "";
  }

  function categoryLabel(value) {
    if (typeof value === "string") return value;
    return value?.title_zh || value?.alias || value?.name
      || value?.label || categoryID(value);
  }

  function identity(kind, value) {
    if (kind === "factor") return factorID(value);
    if (kind === "category") return categoryID(value);
    return groupID(value);
  }

  function mergeByID(kind, values) {
    const result = new Map();
    for (const value of values || []) {
      const id = identity(kind, value);
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
      ]);
    }
    if (kind === "category") {
      return constrainedCandidates(state, "category_candidates", mergeByID("category", [
        ...(state?.categoryCatalog || []),
      ]));
    }
    return constrainedCandidates(state, "product_path_candidates", mergeByID("product_group", [
      ...(state?.groups || []),
    ]));
  }

  function inlineCreateAllowed(state, fieldKey, currentScope) {
    const descriptor = scopedField(state, fieldKey, "inner") || {};
    return currentScope?.source === "outer"
      ? descriptor.allow_inline_create_when_outer_mounted === true
      : descriptor.allow_inline_create_when_outer_unmounted !== false;
  }

  function outerValues(state, kind) {
    const rule = contract(state).outer_scope_tabs?.[kind] || {};
    // The outer picker may expose a full candidate catalog and a smaller
    // selected set. Nested editors inherit the selected set. Candidate fields
    // are only a compatibility fallback for contracts without selection fields
    // (factor candidates historically use the same field for both roles).
    const selectionFields = rule.selection_fields || [];
    const sourceFields = selectionFields.length
      ? selectionFields : (rule.scope_fields || rule.candidate_fields);
    const selected = fieldValues(state, sourceFields);
    const catalog = mergeByID(kind, [
      ...visibleCatalog(state, kind),
      ...fieldValues(state, rule.scope_fields || rule.candidate_fields),
    ]);
    const byID = new Map(catalog.map(item => [
      String(identity(kind, item)), item,
    ]));
    const resolved = selected.map(value => {
      const id = identity(kind, value);
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
        : item.kind === "category"
          ? "外层产品分类已挂载但没有可用分类；请先设置数据源或取消挂载"
          : "外层产品组已挂载但尚未选择产品组；请先设置或取消挂载",
    }));
  }

  function itemID(kind, value) {
    return String(identity(kind, value));
  }

  function itemLabel(kind, value) {
    return kind === "factor" ? factorLabel(value)
      : kind === "category" ? categoryLabel(value) : groupLabel(value);
  }

  function summary(context, state, kind) {
    const root = document.createElement("div");
    root.className = "strategy-editor-scope-summary";
    const current = scope(state, kind);
    const title = document.createElement("strong");
    title.textContent = context.t(kind === "factor" ? "因子候选范围"
      : kind === "category" ? "产品分类候选范围" : "产品组候选范围");
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
    for (const tab of config.inner_manual_tabs || []) {
      if (mountedTabs.includes(tab.key)) add(tab);
    }
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
    contract, factorID, factorLabel, groupID, groupLabel,
    categoryID, categoryLabel, innerTabs,
    candidateCompatible, constrainedCandidates,
    inlineCreateAllowed,
    itemID, itemLabel, mounted, scope, scopedField, scopedFields,
    selectedSourceIDs,
    fieldVisible, fieldRequired, fieldEditable, summary, validate, visibleCatalog,
  });
})();
