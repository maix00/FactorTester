(() => {
  function selectedFactor(state) {
    return FTTestFactors.selectedFactor(state);
  }

  function selectedFactors(state) {
    if (state.kind !== "ic") {
      const aliases = new Set((state.analysis?.groups || []).map(group => (
        group?.factorAlias
      )).filter(Boolean));
      const factors = (state.factors || []).filter(item => aliases.has(
        item.factor_alias || item.alias || item.name,
      ));
      return factors.length ? factors : [selectedFactor(state)].filter(Boolean);
    }
    const selected = Array.isArray(state.values.factor_selections)
      ? state.values.factor_selections : [];
    return selected.length ? selected : [selectedFactor(state)].filter(Boolean);
  }

  function selectedFamily(state, factor) {
    return FTTestFactors.selectedFamily(state, factor);
  }

  function uniqueFamilies(state, factors) {
    const seen = new Set();
    const result = [];
    for (const factor of factors) {
      const family = selectedFamily(state, factor);
      const key = family?.family_ref || factor.family_ref
        || family?.family || factor.family || factor.factor_family_alias;
      if (!key || seen.has(key)) continue;
      seen.add(key);
      result.push({family, factor});
    }
    return result;
  }

  function familyRecord(family, factor) {
    return {
      alias: family?.factor_family_alias || family?.alias || family?.family
        || factor.factor_family_alias || factor.family_alias
        || factor.factor_alias || factor.alias,
      family_ref: family?.family_ref || factor.family_ref
        || factor.factor_family_ref || "",
    };
  }

  function factorRecord(factor, family) {
    return {
      alias: factor.factor_alias || factor.alias || factor.name,
      factor_family_alias: family?.factor_family_alias || family?.alias || family?.family
        || factor.factor_family_alias || factor.family_alias
        || factor.factor_alias || factor.alias,
      factor_ref: factor.factor_ref || factor.target_ref || "",
      family_ref: factor.family_ref || factor.factor_family_ref
        || family?.family_ref || "",
      owner_ref: factor.owner_ref || "",
      git_commit: factor.git_commit || "",
      git_blob: factor.git_blob || "",
      params: factor.params || {},
    };
  }

  async function ensureWorkspace(context, state) {
    if (state.workspace) return state.workspace;
    const factor = selectedFactor(state);
    if (!factor) throw new Error(context.t("请选择因子"));
    const factors = selectedFactors(state);
    const families = uniqueFamilies(state, factors);
    const alias = factor.factor_alias || factor.alias || factor.name || factor.factor_ref;
    const kindTitle = {
      ic: "IC",
      backtest: "Backtest",
      factor_evaluation: "Factor Series",
    }[state.kind] || state.kind;
    const body = {
      title: `${kindTitle} · ${alias}`,
      factor_families: families.map(item => familyRecord(item.family, item.factor)),
      factors: factors.map(item => factorRecord(item, selectedFamily(state, item))),
    };
    const value = await context.api("/api/workspaces", {
      method: "POST", body: JSON.stringify(body),
    });
    state.workspace = value.workspace;
    localStorage.setItem(`ft-${state.kind}-workspace`, state.workspace.workspace_id);
    return state.workspace;
  }

  async function save(context, state, group) {
    await ensureWorkspace(context, state);
    const factor = selectedFactor(state);
    if (!factor) throw new Error(context.t("请选择因子"));
    if (!group) throw new Error(context.t("请选择产品组"));
    FTTestProducts.synchronize(state);
    const factors = selectedFactors(state);
    const families = uniqueFamilies(state, factors);
    const configuration = state.workspace.configuration;
    const payload = structuredClone(configuration.payload || {});
    payload.schema_version = 1;
    payload.shared = payload.shared || {};
    payload.shared.factor_families = families.map(item => (
      familyRecord(item.family, item.factor)
    ));
    payload.shared.factors = factors.map(item => (
      factorRecord(item, selectedFamily(state, item))
    ));
    payload.analyses = payload.analyses || {};
    state.analysis = buildAnalysis(state, factors, selectedFamily(state, factor), group);
    payload.analyses[state.kind] = state.analysis;
    payload.ui = payload.ui || {};
    payload.ui[state.kind] = {
      settings: FTTestConfigurationCompiler.authoringSettings(
        state.manifest, state.values,
      ),
      factor_ref: state.factorRef,
      product_group_ref: FTTestProducts.groupID(group),
      product_group_refs: state.groupRefs,
      output_requests: FTTestOutputs.selection(state),
      mounted_tabs: Array.isArray(state.settingsMountedTabs)
        ? [...state.settingsMountedTabs] : [],
    };
    const value = await context.api(
      `/api/workspaces/${encodeURIComponent(state.workspace.workspace_id)}/configuration`,
      {
        method: "PUT",
        body: JSON.stringify({expected_revision: configuration.revision, payload}),
      },
    );
    state.workspace.configuration = value.configuration;
    return value.configuration;
  }

  function buildAnalysis(state, factors, familyValue, group) {
    const prior = structuredClone(state.analysis || {});
    const settings = FTTestConfigurationCompiler.executionSettings(
      state.manifest, state.values,
    );
    const factor = factors[0];
    const alias = factor.factor_alias || factor.alias || factor.name;
    const family = familyValue?.factor_family_alias || familyValue?.alias
      || factor.factor_family_alias || factor.family_alias || alias;
    if (state.kind === "ic") {
      const selection = FTTestProducts.projection(group);
      return {
        ...prior, ...settings,
        product_path_selection_id: selection.product_path_selection_id,
        product_path_selection: selection,
        product_path_selections: FTTestProducts.selectedProjections(state),
        paths: selection.selected_paths,
        factor_family_alias: family,
        factors: FTTestConfigurationCompiler.factorSubjects(factors),
        settings,
        local_settings: settings,
      };
    }
    if (state.kind === "factor_evaluation") {
      const selection = FTTestProducts.projection(group);
      return {
        ...prior, ...settings,
        product_path_selection_id: selection.product_path_selection_id,
        product_path_selection: selection,
        paths: selection.selected_paths,
        factor_family_alias: family,
        factor_alias: alias,
        factor_ref: factor.factor_ref || factor.target_ref || "",
        settings,
        local_settings: settings,
      };
    }
    let groups = Array.isArray(prior.groups) ? structuredClone(prior.groups) : [];
    if (!groups.length) groups = [{
      id: "group-1", name: "默认分组", shortAlias: "A1", factorAlias: alias,
      splitCount: Number(settings.split_count || 5),
      groupIndex: Number(settings.group_index || 1),
      product_path_selection: FTTestProducts.projection(group),
      product_path_selection_id: FTTestProducts.groupID(group),
    }];
    const productSelections = {};
    for (const item of groups.filter(value => !value.parentId)) {
      const selection = item.product_path_selection;
      const id = item.product_path_selection_id || FTTestProducts.groupID(selection);
      if (id && selection) productSelections[id] = structuredClone(selection);
    }
    return {
      ...prior, ...settings, local_settings: settings, groups,
      ls_configs: prior.ls_configs || [], product_selections: productSelections,
      factor_family_alias: family,
    };
  }

  window.FTTestConfiguration = Object.freeze({ensureWorkspace, save, buildAnalysis});
})();
