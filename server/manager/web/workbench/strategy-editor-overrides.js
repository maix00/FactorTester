(() => {
  function clone(value) {
    return value === undefined ? undefined : structuredClone(value);
  }

  function fieldsForTab(manifest, tabKey) {
    return Object.entries(manifest?.defaults || {})
      .filter(([, field]) => field?.tab_key === tabKey);
  }

  function clearTab(values, manifest, tabKey) {
    for (const [key, field] of fieldsForTab(manifest, tabKey)) {
      const target = window.FTBacktestGroupOverrides?.canonicalKey
        ? FTBacktestGroupOverrides.canonicalKey(key, field) : key;
      delete values[target];
    }
  }

  function create({context, state, initial = {}, mountedTabs = [], onChange}) {
    let values = clone(initial) || {};
    let mounted = [...new Set(mountedTabs || [])];
    const panels = new Map();

    const panel = tab => {
      if (!tab?.key) return document.createElement("div");
      if (panels.has(tab.key)) return panels.get(tab.key);
      const root = FTBacktestGroupOverrides.render({
        context,
        manifest: state.manifest,
        inheritedValues: state.values,
        overrides: values,
        onlyTabs: [tab.key],
        onChange: next => {
          values = clone(next) || {};
          onChange?.(values);
        },
      });
      panels.set(tab.key, root);
      return root;
    };

    const setMountedTabs = nextTabs => {
      const next = [...new Set(nextTabs || [])];
      const nextSet = new Set(next);
      for (const tabKey of mounted) {
        if (nextSet.has(tabKey)) continue;
        if (tabKey !== "__strategy__" && tabKey !== "factor"
          && tabKey !== "product_path_selection") {
          clearTab(values, state.manifest, tabKey);
        }
      }
      mounted = next;
      onChange?.(values);
    };

    return {
      panel,
      setMountedTabs,
      value: () => clone(values) || {},
    };
  }

  window.FTStrategyEditorOverrides = Object.freeze({create});
})();
