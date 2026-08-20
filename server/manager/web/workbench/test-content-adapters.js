(() => {
  function moduleReady(name) {
    return Boolean(window[name] || globalThis[name]);
  }

  const adapters = Object.freeze({
    settings: Object.freeze({}),
    test_templates: Object.freeze({
      lazyKey: "templates",
      ready: () => moduleReady("FTTestTemplates"),
      render: options => FTTestTemplates.panel(
        options.context,
        options.state.templates,
        options.state.kind,
        options.actions.templates,
      ),
    }),
    factor_selection: Object.freeze({
      lazyKey: "factors",
      ready: () => moduleReady("FTTestFactors"),
      render: options => FTTestFactors.panel(
        options.context, options.state, options.refresh,
        options.tab?.content_options || {},
      ),
    }),
    product_path_selection: Object.freeze({
      lazyKey: "products",
      ready: () => moduleReady("FTTestProducts"),
      render: options => FTTestProducts.panel(
        options.context, options.state, options.refresh,
      ),
    }),
    category_selection: Object.freeze({
      lazyKey: "categories",
      ready: () => moduleReady("FTTestCategories"),
      render: options => FTTestCategories.panel(
        options.context, options.state, options.refresh,
      ),
    }),
    run_inputs: Object.freeze({
      lazyKey: "run_inputs",
      ready: () => moduleReady("FTTestSourceUpload"),
      render: options => FTTestSourceUpload.dependencyPanel(
        options.context, options.state, options.refresh,
        options.tab?.content_options || {},
      ),
    }),
  });

  function name(tab) {
    return String(tab?.content_adapter || "settings");
  }

  function descriptor(tab) {
    return adapters[name(tab)] || null;
  }

  function hasContent(tab) {
    return typeof descriptor(tab)?.render === "function";
  }

  function supports(tab) {
    return Boolean(descriptor(tab));
  }

  function render(tab, options) {
    const adapter = descriptor(tab);
    if (!adapter) throw new Error(`未实现的测试内容适配器: ${name(tab)}`);
    return typeof adapter.render === "function" ? adapter.render(options) : null;
  }

  function lazyKey(tab) {
    return descriptor(tab)?.lazyKey || "";
  }

  function isReady(tab) {
    const adapter = descriptor(tab);
    return !adapter || typeof adapter.ready !== "function" || adapter.ready();
  }

  function chipSources(state, item = null) {
    const values = {};
    for (const chip of state.manifest?.chip_fields || []) {
      const source = sourceValues(chip.source_adapter, state, item);
      for (const key of chip.source_keys || []) values[key] = source[key];
      const detailSource = chip.detail_overlay?.source_key
        || chip.detail_overlay?.sourceKey;
      if (detailSource && Object.prototype.hasOwnProperty.call(source, detailSource)) {
        values[detailSource] = source[detailSource];
      }
    }
    return values;
  }

  function sourceValues(adapter, state, item = null) {
    if (adapter === "selected_factor_candidates") {
      const itemRefs = Array.isArray(item?.factor_candidate_refs)
        ? item.factor_candidate_refs.map(String).filter(Boolean) : [];
      const factors = itemRefs.length
        ? factorObjects(state, itemRefs)
        : factorCandidateObjects(state);
      const references = factors.map(factorReference).filter(Boolean);
      if (!references.length) return {};
      const candidateSet = {
        target_ref: `factor-candidates:${references.join("|")}`,
        title_zh: `因子候选（${references.length}）`,
        related_references: factors.map(factor => ({
          target_ref: factorReference(factor),
          label: factorLabel(factor),
        })),
        temporary: true,
        source_origin: "test_inline",
      };
      return {
        factorCandidateCount: references.length,
        factor_candidates: [candidateSet],
      };
    }
    if (adapter === "selected_factors") {
      const itemRefs = Array.isArray(item?.factor_candidate_refs)
        ? item.factor_candidate_refs.map(String).filter(Boolean) : [];
      const factors = itemRefs.length
        ? factorObjects(state, itemRefs)
        : selectedFactorObjects(state);
      return {
        factorRef: factors.map(factorReference).filter(Boolean),
        factorLabel: factors.map(factorLabel).filter(Boolean),
        factor: factors,
      };
    }
    if (adapter === "selected_product_paths") {
      const itemSelection = itemProductSelection(item);
      const projections = itemSelection
        ? [itemSelection]
        : window.FTTestProducts?.selectedProjections?.(state) || [];
      return {
        product_path_selection: projections,
        product_group: productObjects(state, item, projections),
      };
    }
    if (adapter === "primary_strategy_group") {
      const group = item || state.analysis?.groups?.[0] || {};
      return {
        n_groups: group.splitCount,
        group_index: group.groupIndex,
        productMask: group.productMask || [],
      };
    }
    if (adapter === "run_inputs") {
      // The source-state module is intentionally deferred until the input
      // tab or a submission path is used.  Chips can still render a cheap
      // count from the lightweight state shape during route bootstrap.
      const counts = window.FTTestInputState?.counts?.(state) || {
        factors: (state.transientFactorSources || []).length,
        strategies: (state.transientStrategySources || []).length,
        dependencies: (state.runInputDependencies || []).length,
      };
      return counts.dependencies ? {run_input_count: counts.dependencies} : {};
    }
    return {};
  }

  function selectedFactorObjects(state) {
    if (!window.FTTestFactorSelection || !window.FTTestFactors) return [];
    return state.kind === "ic"
      ? FTTestFactorSelection.selectedFactors(state)
      : [FTTestFactors.selectedFactor(state)].filter(Boolean);
  }

  function factorCandidateObjects(state) {
    if (!window.FTTestFactorSelection) return [];
    return FTTestFactorSelection.candidates(state);
  }

  function factorReference(value) {
    if (typeof value === "string") return value;
    return String(value?.factor_ref || value?.target_ref || "").trim();
  }

  function factorLabel(value) {
    if (typeof value === "string") return value;
    return String(value?.factor_alias || value?.alias || value?.name
      || factorReference(value)).trim();
  }

  function factorObjects(state, refs) {
    const wanted = new Set(refs || []);
    const candidates = window.FTTestFactorSelection?.candidates?.(state) || [];
    const matched = new Map(candidates
      .filter(item => wanted.has(factorReference(item)))
      .map(item => [factorReference(item), item]));
    // Strategy rows are rendered before the catalog is necessarily loaded.
    // Preserve their stable factor reference/alias so the detail overlay stays
    // clickable; the catalog detail view resolves the full object lazily.
    return [...wanted].map(ref => matched.get(ref) || {factor_ref: ref});
  }

  function itemProductSelection(item) {
    if (!item) return null;
    return item.product_path_selection
      || item.product_group
      || item.productGroup
      || item.product_path_selection_id
      || item.product_group_ref
      || null;
  }

  function productObjects(state, item, projections) {
    const explicit = [
      item?.product_group,
      item?.productGroup,
      item?.product_path_selection_id,
      item?.product_group_ref,
    ].filter(Boolean);
    const catalog = Array.isArray(state.groups) ? state.groups : [];
    const values = [...explicit];
    for (const projection of projections || []) {
      const ref = productGroupID(projection);
      const match = catalog.find(group => productGroupID(group) === ref);
      if (match) values.push(match);
      else if (ref) values.push(projection);
    }
    const seen = new Set();
    return values.map(value => {
      const ref = productGroupID(value);
      return catalog.find(group => productGroupID(group) === ref) || value;
    }).filter(value => {
      const ref = productGroupID(value);
      if (!ref || seen.has(ref)) return false;
      seen.add(ref);
      return true;
    });
  }

  function productGroupID(value) {
    return typeof value === "string"
      ? value
      : value?.group_ref || value?.product_group_ref || value?.id
        || value?.product_group_template_id || value?.product_path_selection_id || "";
  }

  window.FTTestContentAdapters = Object.freeze({
    chipSources, hasContent, isReady, lazyKey, name, render, supports,
  });
})();
