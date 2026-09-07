(() => {
  let sequence = 0;
  const RETURN_PRICE_BASES = new Set([
    "next_open_to_open_adjusted",
    "next_close_to_close_adjusted",
  ]);

  function identifier(prefix, requested = "") {
    const stable = String(requested || "").trim();
    if (stable) return stable;
    sequence += 1;
    return `${prefix}_${Date.now().toString(36)}_${sequence.toString(36)}`;
  }

  function initialize(state) {
    state.analysis = state.analysis && typeof state.analysis === "object"
      ? state.analysis : {};
    if (!Array.isArray(state.analysis.configuration_groups)) {
      state.analysis.configuration_groups = [];
    }
    state.analysis.configuration_groups = state.analysis.configuration_groups.map(
      item => normalize(item, state.manifest),
    );
    const selectionDeclared = Array.isArray(state.selectedICConfigurationGroupIDs);
    if (!selectionDeclared) state.selectedICConfigurationGroupIDs = [];
    const available = new Set(
      state.analysis.configuration_groups.map(item => item.config_group_id),
    );
    state.selectedICConfigurationGroupIDs = state.selectedICConfigurationGroupIDs
      .map(String).filter(id => available.has(id));
    if (!selectionDeclared && state.analysis.configuration_groups.length === 1) {
      state.selectedICConfigurationGroupIDs = [
        state.analysis.configuration_groups[0].config_group_id,
      ];
    }
    return state.analysis;
  }

  function add(state, draft = {}) {
    initialize(state);
    if (state.analysis.configuration_groups.length >= 1) {
      throw new Error("IC Slice 1 supports one configuration group only");
    }
    const group = normalize({
      ...draft,
      config_group_id: identifier("icg", draft.config_group_id),
      batch_id: identifier("icb", draft.batch_id),
    }, state.manifest);
    const requestedName = String(draft.name || "").trim();
    group.name = uniqueName(
      state, requestedName || `IC 配置组 ${state.analysis.configuration_groups.length + 1}`,
    );
    state.analysis.configuration_groups.push(group);
    state.selectedICConfigurationGroupIDs = [group.config_group_id];
    return group;
  }

  function update(state, id, patch = {}) {
    initialize(state);
    const index = state.analysis.configuration_groups.findIndex(
      item => item.config_group_id === id,
    );
    if (index < 0) throw new Error("IC configuration group not found");
    const current = state.analysis.configuration_groups[index];
    const next = normalize({...current, ...structuredClone(patch)}, state.manifest);
    if (Object.prototype.hasOwnProperty.call(patch, "name")) {
      next.name = uniqueName(state, String(patch.name || "").trim(), id);
    }
    state.analysis.configuration_groups[index] = next;
    return next;
  }

  function removeSelected(state) {
    initialize(state);
    const wanted = new Set(state.selectedICConfigurationGroupIDs);
    const removed = state.analysis.configuration_groups.filter(
      item => wanted.has(item.config_group_id),
    );
    state.analysis.configuration_groups = state.analysis.configuration_groups.filter(
      item => !wanted.has(item.config_group_id),
    );
    state.selectedICConfigurationGroupIDs = [];
    return removed;
  }

  function selected(state) {
    initialize(state);
    const wanted = new Set(state.selectedICConfigurationGroupIDs);
    return state.analysis.configuration_groups.filter(
      item => wanted.has(item.config_group_id),
    );
  }

  function toggle(state, id, checked, selection = "single") {
    initialize(state);
    if (selection === "single") {
      state.selectedICConfigurationGroupIDs = checked ? [id] : [];
      return;
    }
    const values = new Set(state.selectedICConfigurationGroupIDs);
    if (checked) values.add(id); else values.delete(id);
    state.selectedICConfigurationGroupIDs = [...values];
  }

  function find(state, id) {
    initialize(state);
    return state.analysis.configuration_groups.find(
      item => item.config_group_id === id,
    ) || null;
  }

  function normalize(value = {}, manifest = null) {
    const factorRef = String(value.factor_ref || "").trim();
    if (!/^factor:v2:[A-Za-z0-9_-]{43}$/.test(factorRef)) {
      throw new Error("configuration group requires one frozen factor_ref");
    }
    const productScopeRef = String(value.product_scope_ref || "").trim();
    if (!productScopeRef) {
      throw new Error("configuration group requires one product_scope_ref");
    }
    if (Array.isArray(value.entry_delay_bars)) {
      throw new Error("configuration group requires a single non-negative Delay");
    }
    const delay = Number(value.entry_delay_bars);
    if (!Number.isInteger(delay) || delay < 0) {
      throw new Error("configuration group requires a single non-negative Delay");
    }
    const methods = unique((value.methods || []).map(item => String(item).trim()))
      .filter(item => item === "rank" || item === "pearson");
    if (!methods.length) throw new Error("configuration group requires an IC method");
    const basis = String(value.return_price_basis || "").trim();
    if (!RETURN_PRICE_BASES.has(basis)) {
      throw new Error("configuration group requires a registered return_price_basis");
    }
    return {
      config_group_id: identifier("icg", value.config_group_id),
      batch_id: identifier("icb", value.batch_id),
      name: String(value.name || "").trim(),
      factor_ref: factorRef,
      ...(Array.isArray(value.factor_source_selections)
        && value.factor_source_selections.length ? {
          factor_source_selections: structuredClone(value.factor_source_selections),
        } : {}),
      ...(Array.isArray(value.factor_set_selections)
        && value.factor_set_selections.length ? {
          factor_set_selections: structuredClone(value.factor_set_selections),
        } : {}),
      product_scope_ref: productScopeRef,
      entry_delay_bars: delay,
      horizon: normalizeHorizon(value.horizon),
      methods,
      return_price_basis: basis,
      ...(Object.prototype.hasOwnProperty.call(value, "warmup_mode")
        ? {warmup_mode: String(value.warmup_mode || "auto")} : {}),
      ...(Object.prototype.hasOwnProperty.call(value, "warmup_window")
        ? {warmup_window: structuredClone(value.warmup_window)} : {}),
      analysis_attachments: Array.isArray(value.analysis_attachments)
        ? structuredClone(value.analysis_attachments) : [],
      editor_mounted_tabs: window.FTTestConfigurationCompiler?.authoringItemMountedTabs
        ? FTTestConfigurationCompiler.authoringItemMountedTabs(
          manifest, value, value.editor_mounted_tabs,
        )
        : unique([
          "__configuration__", "factor", "product_path_selection",
          ...(Array.isArray(value.editor_mounted_tabs) ? value.editor_mounted_tabs : []),
        ]),
    };
  }

  function normalizeHorizon(value) {
    const raw = value && typeof value === "object" ? value : {};
    if (["scale_aware", "auto"].includes(String(raw.sampling || "").toLowerCase())) {
      return {sampling: "scale_aware"};
    }
    const bases = unique((raw.bases || ["signal"]).map(String).filter(Boolean));
    const multipliers = unique((raw.multipliers || [1]).map(Number)
      .filter(item => Number.isInteger(item) && item > 0));
    return {
      sampling: "explicit",
      bases: bases.length ? bases : ["signal"],
      multipliers: multipliers.length ? multipliers : [1],
    };
  }

  function unique(values) {
    return [...new Set((values || []).filter(Boolean))];
  }

  function uniqueName(state, value, exceptID = "") {
    const base = String(value || "").trim();
    if (!base) throw new Error("configuration group name is required");
    const used = new Set(state.analysis.configuration_groups
      .filter(item => item.config_group_id !== exceptID)
      .map(item => item.name));
    if (!used.has(base)) return base;
    let suffix = 2;
    while (used.has(`${base} ${suffix}`)) suffix += 1;
    return `${base} ${suffix}`;
  }

  window.FTICConfigurationGroupModel = Object.freeze({
    add, find, initialize, normalize, removeSelected, selected, toggle, update,
  });
})();
