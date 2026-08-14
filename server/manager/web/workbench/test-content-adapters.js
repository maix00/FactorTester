(() => {
  const adapters = Object.freeze({
    settings: Object.freeze({}),
    test_templates: Object.freeze({
      lazyKey: "templates",
      render: options => FTTestTemplates.panel(
        options.context,
        options.state.templates,
        options.state.kind,
        options.actions.templates,
      ),
    }),
    factor_selection: Object.freeze({
      lazyKey: "factors",
      render: options => FTTestFactors.panel(
        options.context, options.state, options.refresh,
        options.tab?.content_options || {},
      ),
    }),
    product_path_selection: Object.freeze({
      lazyKey: "products",
      render: options => FTTestProducts.panel(
        options.context, options.state, options.refresh,
      ),
    }),
    category_selection: Object.freeze({
      lazyKey: "categories",
      render: options => FTTestCategories.panel(
        options.context, options.state, options.refresh,
      ),
    }),
    run_inputs: Object.freeze({
      render: options => FTTestSourceUpload.strategyPanel(
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

  function render(tab, options) {
    const adapter = descriptor(tab);
    if (!adapter) throw new Error(`未实现的测试内容适配器: ${name(tab)}`);
    return typeof adapter.render === "function" ? adapter.render(options) : null;
  }

  function lazyKey(tab) {
    return descriptor(tab)?.lazyKey || "";
  }

  function chipSources(state, item = null) {
    const values = {};
    for (const chip of state.manifest?.chip_fields || []) {
      const source = sourceValues(chip.source_adapter, state, item);
      for (const key of chip.source_keys || []) values[key] = source[key];
    }
    return values;
  }

  function sourceValues(adapter, state, item = null) {
    if (adapter === "selected_factors") {
      if (!window.FTTestFactorSelection || !window.FTTestFactors) return {};
      const factors = item?.factorAlias || item?.factor_alias
        ? [item.factorAlias || item.factor_alias]
        : state.kind === "ic"
        ? FTTestFactorSelection.selectedFactors(state)
        : [FTTestFactors.selectedFactor(state)].filter(Boolean);
      return {factorAlias: factors.map(FTTestFactorSelection.factorAlias).filter(Boolean)};
    }
    if (adapter === "selected_product_paths") {
      if (!window.FTTestProducts) return {};
      return {product_path_selection: item?.product_path_selection
        ? [item.product_path_selection] : FTTestProducts.selectedProjections(state)};
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
      const counts = FTTestInputState.counts(state);
      const total = counts.factors + counts.strategies + counts.dependencies;
      return total ? {run_input_count: total} : {};
    }
    return {};
  }

  window.FTTestContentAdapters = Object.freeze({
    chipSources, hasContent, lazyKey, name, render,
  });
})();
