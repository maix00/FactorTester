(() => {
  const adapters = Object.freeze({
    settings: Object.freeze({}),
    test_templates: Object.freeze({
      render: options => FTTestTemplates.panel(
        options.context,
        options.state.templates,
        options.state.kind,
        options.actions.templates,
      ),
    }),
    factor_selection: Object.freeze({
      render: options => FTTestFactors.panel(
        options.context, options.state, options.refresh,
      ),
    }),
    product_path_selection: Object.freeze({
      render: options => FTTestProducts.panel(
        options.context, options.state, options.refresh,
      ),
    }),
    category_selection: Object.freeze({
      render: options => FTTestCategories.panel(
        options.context, options.state, options.refresh,
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

  function chipSources(state) {
    const values = {};
    for (const chip of state.manifest?.chip_fields || []) {
      const source = sourceValues(chip.source_adapter, state);
      for (const key of chip.source_keys || []) values[key] = source[key];
    }
    return values;
  }

  function sourceValues(adapter, state) {
    if (adapter === "selected_factors") {
      const factors = state.kind === "ic"
        ? FTTestFactorSelection.selectedFactors(state)
        : [FTTestFactors.selectedFactor(state)].filter(Boolean);
      return {factorAlias: factors.map(FTTestFactorSelection.factorAlias).filter(Boolean)};
    }
    if (adapter === "selected_product_paths") {
      return {product_path_selection: FTTestProducts.selectedProjections(state)};
    }
    if (adapter === "primary_strategy_group") {
      const group = state.analysis?.groups?.[0] || {};
      return {
        n_groups: group.splitCount,
        group_index: group.groupIndex,
        productMask: group.productMask || [],
      };
    }
    return {};
  }

  window.FTTestContentAdapters = Object.freeze({
    chipSources, hasContent, name, render,
  });
})();
