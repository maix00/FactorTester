(() => {
  function selectedFactor(state) {
    return FTTestFactors.selectedFactor(state);
  }

  function executionFactors(state) {
    if (state.kind !== "ic") {
      const refs = new Set((state.analysis?.groups || []).flatMap(group => (
        Array.isArray(group?.factor_candidate_refs)
          ? group.factor_candidate_refs : []
      )).filter(Boolean));
      const factors = factorCatalog(state).filter(item => refs.has(factorRef(item)));
      return factors.length ? factors : [selectedFactor(state)].filter(Boolean);
    }
    // Grouped IC owns the frozen factor reference at configuration-group level.
    // The legacy global factor selection remains authoring/catalog state only
    // and must never override the factor that identifies the selected group.
    window.FTICConfigurationGroupModel?.initialize?.(state);
    const groups = window.FTICConfigurationGroupModel?.selected?.(state)
      || (Array.isArray(state.analysis?.configuration_groups)
        ? state.analysis.configuration_groups : []);
    const refs = [...new Set(groups.map(item => String(
      item?.factor_ref || "",
    ).trim()).filter(Boolean))];
    if (refs.length) {
      const catalog = new Map(factorCatalog(state).map(item => [factorRef(item), item]));
      return refs.map(ref => {
        const factor = catalog.get(ref);
        if (!factor) throw new Error(`factor reference was not found: ${ref}`);
        return factor;
      });
    }
    // Before a group is authored, keep enough legacy behavior for workspace
    // creation and one-time flat migration; no execution task is available in
    // that state because the run-batch model requires a selected group.
    if (Object.prototype.hasOwnProperty.call(state.values || {}, "factor_selections")) {
      const selected = Array.isArray(state.values.factor_selections)
        ? state.values.factor_selections : [];
      const catalog = new Map(factorCatalog(state).map(item => [factorRef(item), item]));
      return selected.map(item => {
        if (item && typeof item === "object") return item;
        return catalog.get(String(item || ""));
      }).filter(Boolean);
    }
    const candidates = Array.isArray(state.values?.factor_candidates)
      ? state.values.factor_candidates : [];
    return candidates.length ? candidates : [selectedFactor(state)].filter(Boolean);
  }

  function factorRef(value) {
    return String(value?.ref || "").trim();
  }

  function factorCatalog(state) {
    const byRef = new Map();
    for (const item of [
      ...(state.factors || []), ...(state.savedFactors || []),
      ...(state.values?.factor_candidates || []),
    ]) {
      const ref = factorRef(item);
      if (!ref) continue;
      const previous = byRef.get(ref);
      const left = window.FTFactorModel?.frozenFactorIdentity?.(previous)?.record;
      const right = window.FTFactorModel?.frozenFactorIdentity?.(item)?.record;
      const leftFingerprint = String(
        left?.identity?.self_formula_fingerprint || "",
      );
      const rightFingerprint = String(
        right?.identity?.self_formula_fingerprint || "",
      );
      // owner_ref and alias are catalog/display provenance. Two visible
      // owners may register the same immutable formula and therefore share
      // one formula-derived factor ref. Only a disagreement in executable
      // formula identity is a real conflict; later candidate state is the
      // authoritative presentation record for the current editor.
      if (left && right && leftFingerprint !== rightFingerprint) {
        throw new Error(`factor ref is bound to conflicting records: ${ref}`);
      }
      byRef.set(ref, {...(previous || {}), ...item});
    }
    return [...byRef.values()];
  }

  function runtimeGroups(state, groups) {
    const catalog = new Map(factorCatalog(state).map(item => [factorRef(item), item]));
    return groups.map(group => {
      const refs = Array.isArray(group.factor_candidate_refs)
        ? group.factor_candidate_refs.map(String).filter(Boolean) : [];
      for (const ref of refs) {
        if (!catalog.has(ref)) throw new Error(`factor reference was not found: ${ref}`);
      }
      return group;
    });
  }

  function selectedFamily(state, factor) {
    return FTTestFactors.selectedFamily(state, factor);
  }

  function factorRecord(factor, family) {
    const frozen = window.FTFactorModel?.frozenFactorIdentity?.(factor);
    if (!frozen) throw new Error("factor must be a complete frozen v2 record");
    return {
      ...structuredClone(frozen.record),
      ...(factor.source_kind === "transient" ? {
        source_kind: "transient",
        transient_factor_id: factor.transient_factor_id || "",
        temporary: factor.temporary === true,
      } : {}),
    };
  }

  function temporaryObjects(state) {
    const temporary = item => item?.temporary === true
      || item?.source_kind === "transient"
      || item?.source_origin === "test_inline";
    const copy = value => structuredClone(value || []);
    return {
      factors: copy((state.values?.factor_candidates || []).filter(temporary)),
      factor_sets: copy((state.factorSetCatalog?.items || []).filter(temporary)),
      product_groups: copy((state.groups || []).filter(temporary)),
      categories: copy((state.values?.category_candidates || []).filter(temporary)),
      factor_sources: copy(state.transientFactorSources),
      factor_families: copy(state.transientFactorFamilies),
      strategy_sources: copy(state.transientStrategySources),
      strategy_specs: copy(state.strategySpecs),
      strategy_inspections: copy(state.strategyInspections),
      run_input_dependencies: copy(state.runInputDependencies),
    };
  }

  async function ensureWorkspace(context, state) {
    if (state.workspace) return state.workspace;
    const factors = executionFactors(state);
    const factor = factors[0] || selectedFactor(state);
    if (!factor) throw new Error(context.t("请选择因子"));
    const alias = factor.alias;
    const kindTitle = {
      ic: "IC",
      backtest: "Backtest",
      factor_evaluation: "Factor Series",
    }[state.kind] || state.kind;
    const body = {
      title: `${kindTitle} · ${alias}`,
      factors: factors.map(item => factorRecord(item, selectedFamily(state, item))),
    };
    const value = await context.api("/api/workspaces", {
      method: "POST", body: JSON.stringify(body),
    });
    state.workspace = value.workspace;
    return state.workspace;
  }

  async function save(context, state, group) {
    await ensureWorkspace(context, state);
    const factors = executionFactors(state);
    const factor = factors[0] || selectedFactor(state);
    if (!factor) throw new Error(context.t("请选择因子"));
    const isBacktest = state.kind === "backtest";
    const strategyGroups = Array.isArray(state.analysis?.groups)
      ? state.analysis.groups : [];
    const hasStrategyProductScope = isBacktest && strategyGroups.some(item => (
      item?.product_path_selection_id
      || item?.product_path_selection?.product_path_selection_id
      || item?.product_path_selection?.product_group_template_id
      || item?.product_path_selection?.group_ref
      || item?.product_path_selection?.id
      || (Array.isArray(item?.product_path_selection?.selected_paths)
        && item.product_path_selection.selected_paths.length)
      || (Array.isArray(item?.product_path_selection?.paths)
        && item.product_path_selection.paths.length)
    ));
    if (!group && !hasStrategyProductScope) {
      throw new Error(isBacktest
        ? context.t("请先在策略组设置中为策略选择产品组")
        : context.t("请选择产品组"));
    }
    // Backtest still restores the optional outer catalog selection for the
    // authoring UI; it is not used to build the task's execution scope.
    const configuration = state.workspace.configuration;
    const payload = configurationPayload(state, group);
    state.analysis = structuredClone(payload.analyses[state.kind]);
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

  function configurationPayload(state, group, options = {}) {
    let factors;
    try { factors = executionFactors(state); }
    catch (error) {
      if (!options.allowIncomplete) throw error;
      factors = [];
    }
    const factor = factors[0] || selectedFactor(state);
    if (!factor && !options.allowIncomplete) throw new Error("请选择因子");
    const isBacktest = state.kind === "backtest";
    FTTestProducts.synchronize(state);
    const payload = structuredClone(state.workspace?.configuration?.payload || {});
    payload.schema_version = 2;
    payload.shared = payload.shared || {};
    delete payload.shared.factor_families;
    payload.shared.factors = factors.map(item => (
      factorRecord(item, selectedFamily(state, item))
    ));
    payload.shared.temporary_objects = temporaryObjects(state);
    payload.analyses = payload.analyses || {};
    const analysis = factor
      ? buildAnalysis(state, factors, selectedFamily(state, factor), group)
      : {
        ...(state.analysis || {}),
        local_settings: FTTestConfigurationCompiler.executionSettings(
          state.manifest, state.values || {},
        ),
      };
    payload.analyses[state.kind] = analysis;
    payload.ui = payload.ui || {};
    const ui = {
      settings: FTTestConfigurationCompiler.authoringSettings(
        state.manifest, state.values,
      ),
      run_values: structuredClone(state.runValues || {}),
      factor_ref: state.kind === "ic" ? group?.factor_ref : state.factorRef,
      output_requests: FTTestRunFields.selection(state),
      mounted_tabs: Array.isArray(state.settingsMountedTabs)
        ? [...state.settingsMountedTabs] : [],
    };
    if (state.kind === "ic") {
      ui.selected_configuration_group_ids = group?.config_group_id
        ? [String(group.config_group_id)]
        : [...(state.selectedICConfigurationGroupIDs || [])];
      if (group?.product_scope_ref) {
        ui.product_group_ref = String(group.product_scope_ref);
        ui.product_group_refs = [String(group.product_scope_ref)];
      }
    }
    // Backtest execution is scoped by each strategy group's product
    // selection. The optional outer selection is retained only as authoring
    // state so it can continue to filter candidate choices after reload.
    const syntheticBacktestTask = isBacktest && group?.id === "__backtest__";
    if (state.kind !== "ic") {
      const authoringGroupRef = syntheticBacktestTask
        ? state.groupRef : FTTestProducts.groupID(group);
      const authoringGroupRefs = syntheticBacktestTask
        ? state.groupRefs : [authoringGroupRef];
      if (authoringGroupRef) ui.product_group_ref = authoringGroupRef;
      if (Array.isArray(authoringGroupRefs) && authoringGroupRefs.length) {
        ui.product_group_refs = [...authoringGroupRefs];
      }
    }
    payload.ui[state.kind] = ui;
    return payload;
  }

  function buildAnalysis(state, factors, familyValue, group) {
    const prior = structuredClone(state.analysis || {});
    const settings = FTTestConfigurationCompiler.executionSettings(
      state.manifest, state.values,
    );
    const factor = factors[0];
    const alias = factor.alias;
    const family = factor.identity?.family_alias
      || familyValue?.factor_family_alias || familyValue?.alias || alias;
    if (state.kind === "ic") {
      return FTICConfiguration.compileAnalysis({
        manifest: state.manifest,
        values: state.values,
        configurationGroups: group ? [group]
          : (state.analysis?.configuration_groups || []),
        productCatalog: state.groups || [],
      });
    }
    if (state.kind === "factor_evaluation") {
      const selection = FTTestProducts.projection(group);
      return FTTestConfigurationCompiler.sanitizeExecutionPayload(state.manifest, {
        ...prior, ...settings,
        product_path_selection_id: selection.product_path_selection_id,
        product_path_selection: selection,
        paths: selection.selected_paths,
        factor_family_alias: family,
        factor_alias: alias,
        factor_ref: factor.ref,
        settings,
        local_settings: settings,
      }, state.values, {stripRootRegistered: true});
    }
    let groups = Array.isArray(prior.groups) ? structuredClone(prior.groups) : [];
    if (!groups.length) groups = [{
      id: "group-1", batchId: "batch:1", name: "batch:1/group-1",
      factor_candidate_refs: [factorRef(factor)],
      splitCount: Number(state.values?.split_count || 5),
      groupIndex: Number(state.values?.group_index || 1),
      product_path_selection: FTTestProducts.projection(group),
      product_path_selection_id: FTTestProducts.groupID(group),
    }];
    groups = runtimeGroups(state, groups);
    const catalogGroups = new Map((state.groups || []).map(value => [
      String(FTTestProducts.groupID(value) || ""), value,
    ]).filter(([id]) => id));
    groups = groups.map(item => {
      const id = String(
        item.product_path_selection_id
          || FTTestProducts.groupID(item.product_path_selection) || "",
      );
      const stored = item.product_path_selection;
      const storedPaths = stored?.selected_paths || stored?.paths || [];
      const catalog = catalogGroups.get(id);
      if (!catalog || storedPaths.length) return item;
      return {
        ...item,
        product_path_selection_id: id,
        product_path_selection: FTTestProducts.projection(catalog),
      };
    });
    const productSelections = {};
    for (const item of groups.filter(value => !value.parentId)) {
      const selection = item.product_path_selection;
      const id = item.product_path_selection_id || FTTestProducts.groupID(selection);
      if (id && selection) productSelections[id] = structuredClone(selection);
    }
    return FTTestConfigurationCompiler.sanitizeExecutionPayload(state.manifest, {
      ...prior, ...settings, local_settings: settings, groups,
      ls_configs: prior.ls_configs || [], product_selections: productSelections,
    }, state.values, {stripRootRegistered: true});
  }

  window.FTTestConfiguration = Object.freeze({
    ensureWorkspace, save, buildAnalysis, configurationPayload, executionFactors,
  });
})();
