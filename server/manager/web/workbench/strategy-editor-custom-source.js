(() => {
  function overridePanel(context, state, tab, refresh) {
    if (!window.FTBacktestGroupOverrides?.render) return document.createElement("div");
    return FTBacktestGroupOverrides.render({
      context,
      manifest: state.manifest,
      inheritedValues: state.values,
      overrides: state.customStrategyOverrides || {},
      onlyTabs: [tab.key],
      onChange: values => {
        state.customStrategyOverrides = values;
        refresh?.();
      },
    });
  }

  function create(context, state, sourceMount, refresh) {
    if (!sourceMount || !window.FTStrategyEditorTabs?.create
      || !window.FTBacktestGroupOverrides?.render
      || !window.FTStrategyEditorScope?.summary) return sourceMount;
    const editor = FTStrategyEditorTabs.create({
      context,
      state,
      mountedTabs: state.customStrategyMountedTabs || [],
      onMountedTabsChange: tabs => { state.customStrategyMountedTabs = tabs; },
      onActivate: key => { state.customStrategyActiveTab = key; },
      renderStructure: () => sourceMount,
      renderFactor: () => FTStrategyEditorScope.summary(context, state, "factor"),
      renderProduct: () => FTStrategyEditorScope.summary(
        context, state, "product_path_selection",
      ),
      renderProductFilter: () => window.FTStrategyEditorProductFilter?.render(
        context,
        state,
        state.customStrategyProductMask || [],
        values => {
          state.customStrategyProductMask = [...new Set(
            (values || []).map(String).map(value => value.trim()).filter(Boolean),
          )];
          refresh?.();
        },
      ) || document.createElement("div"),
      renderOverrides: ({tab}) => overridePanel(context, state, tab, refresh),
    });
    return editor;
  }

  window.FTCustomStrategyEditor = Object.freeze({create});
})();
