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
    if (adapter === "selected_factors") {
      const itemFactors = Array.isArray(item?.factorAliases)
        ? item.factorAliases
        : [item?.factorAlias || item?.factor_alias].filter(Boolean);
      const aliases = itemFactors.length
        ? itemFactors.map(value => String(value).trim()).filter(Boolean)
        : selectedFactorAliases(state);
      return {
        factorAlias: aliases,
        factor: factorObjects(state, aliases),
      };
    }
    if (adapter === "selected_product_paths") {
      const projections = item?.product_path_selection
        ? [item.product_path_selection]
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

  function selectedFactorAliases(state) {
    if (!window.FTTestFactorSelection || !window.FTTestFactors) return [];
    const factors = state.kind === "ic"
      ? FTTestFactorSelection.selectedFactors(state)
      : [FTTestFactors.selectedFactor(state)].filter(Boolean);
    return factors.map(FTTestFactorSelection.factorAlias).filter(Boolean);
  }

  function factorObjects(state, aliases) {
    const wanted = new Set(aliases || []);
    const candidates = window.FTTestFactorSelection?.candidates?.(state) || [];
    return candidates.filter(item => wanted.has(FTTestFactorSelection.factorAlias(item)));
  }

  function productObjects(state, item, projections) {
    const explicit = [item?.product_group, item?.productGroup].filter(Boolean);
    const catalog = Array.isArray(state.groups) ? state.groups : [];
    const values = [...explicit];
    for (const projection of projections || []) {
      const ref = productGroupID(projection);
      const match = catalog.find(group => productGroupID(group) === ref);
      if (match) values.push(match);
      else if (ref) values.push(projection);
    }
    const seen = new Set();
    return values.filter(value => {
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
