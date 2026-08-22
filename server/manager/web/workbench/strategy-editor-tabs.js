(() => {
  function unique(values) {
    return [...new Set((values || []).filter(Boolean))];
  }

  function defaultKeys(state) {
    const contract = state?.manifest?.strategy_editor || {};
    return (
      contract.outer_pre_mounted_tabs
      || contract.pre_mounted_tabs
      || contract.inner_default_tabs
      || []
    )
      .map(item => item.key).filter(Boolean);
  }

  function eligibleOverrideTabs(state) {
    const contract = state?.manifest?.strategy_editor || {};
    const outerOnly = new Set(contract.outer_only_tabs || []);
    const preMounted = new Set(defaultKeys(state));
    const registered = (state?.manifest?.tab_lists?.["group-settings"] || []).filter(tab => {
      if (outerOnly.has(tab.key) || preMounted.has(tab.key)) return false;
      return Object.entries(state?.manifest?.defaults || {}).some(([key, field]) => (
        field.tab_key === tab.key
        && field.scope_policy === "overridable"
        && field.execution_policy !== "authoring_only"
        && (!window.FTSettingRules || FTSettingRules.isVisible(field, state.values || {}))
      ));
    });
    const manual = (contract.inner_manual_tabs || []).filter(tab => (
      !outerOnly.has(tab.key) && !preMounted.has(tab.key) && tab.mount_policy === "manual"
    ));
    const seen = new Set(registered.map(tab => tab.key));
    return [...registered, ...manual.filter(tab => !seen.has(tab.key))];
  }

  function create(options = {}) {
    const {
      context, state, mountedTabs: requested = [], onMountedTabsChange,
      onActivate, renderStructure, renderFactor, renderProduct,
      renderProductFilter, renderOverrides, chipValues, chipSources,
      activeKey: requestedActiveKey = "",
    } = options;
    const root = document.createElement("section");
    root.className = "backend-settings-shell test-settings-shell strategy-editor-tabs";
    let mounted = unique([...defaultKeys(state), ...requested]);
    let activeKey = requestedActiveKey;
    let tabset = null;
    let settingsShell = null;
    let chipHost = null;

    const manager = () => {
      const tabs = eligibleOverrideTabs(state);
      return FTTabChipContent.createSettingsManager({
        context,
        sections: [{
          label: "设置",
          items: tabs.map(tab => ({
            key: tab.key,
            label: tab.label || tab.key,
            description: tab.help_text || tab.description || "",
            mounted: mounted.includes(tab.key),
            onToggle: checked => {
              mounted = unique([...defaultKeys(state), ...mounted.filter(key => (
                key !== tab.key
              )), ...(checked ? [tab.key] : [])]);
              onMountedTabsChange?.([...mounted]);
              redraw(tab.key);
            },
            preview: () => window.FTTestSettingChips ? FTTestSettingChips.render({
              manifest: state.manifest,
              values: FTSettingRules.previewDefaultsForTab(
                state.manifest, state.values || {}, tab.key,
              ),
              context,
              mountedTabs: [tab.key],
              includeRun: false,
              includeEmpty: true,
              includeUnregistered: true,
              includeHidden: true,
              notApplicableLabel: "N/A",
              includeTabFallbacks: true,
              fallbackTabs: [tab.key],
              groupBy: "tab",
              sources: {},
              inline: true,
            }) : null,
          })),
        }],
      });
    };

    function items() {
      const tabs = FTStrategyEditorScope.innerTabs(state, mounted);
      const result = tabs.map(tab => ({
        key: tab.key,
        label: context.t(tab.label || tab.key),
        description: tab.description ? context.t(tab.description) : "",
        render: () => {
          if (tab.kind === "structure") {
            return renderStructure?.() || document.createElement("div");
          }
          if (tab.key === "factor") return renderFactor?.() || document.createElement("div");
          if (tab.key === "product_path_selection") {
            return renderProduct?.() || document.createElement("div");
          }
          if (tab.kind === "product_filter" || tab.key === "trading_product_filter") {
            return renderProductFilter?.() || document.createElement("div");
          }
          return renderOverrides?.({
            tab,
            mountedTabs: mounted,
            onMountedTabsChange: tabsNext => {
              mounted = unique([...defaultKeys(state), ...(tabsNext || [])]);
              onMountedTabsChange?.([...mounted]);
            },
          }) || document.createElement("div");
        },
      }));
      result.push({
        key: "__manage__",
        label: context.t("+ 设置"),
        render: manager,
      });
      return result;
    }

    function redraw(preferredKey = activeKey) {
      const nextItems = items();
      const available = new Set(nextItems.map(item => item.key));
      activeKey = available.has(preferredKey) ? preferredKey : nextItems[0]?.key || "";
      settingsShell = FTTabChipContent.createSettings({
        root,
        rootClass: "backend-settings-shell test-settings-shell strategy-editor-tabs",
        items: nextItems,
        activeKey,
        onActivate: key => { activeKey = key; onActivate?.(key); },
      });
      tabset = settingsShell.tabset;
      chipHost = renderChips();
      settingsShell.setCurrent(
        chipHost?.children.length ? chipHost : null,
        context.t("当前选择"),
      );
    }

    function renderChips() {
      if (!window.FTTestSettingChips?.render) return null;
      const values = typeof chipValues === "function"
        ? chipValues() : (chipValues || state.values || {});
      const row = FTTestSettingChips.render({
        manifest: state.manifest,
        values,
        context,
        mountedTabs: [...mounted],
        includeUnregistered: true,
        includeEmpty: true,
        includeRun: false,
        includeStrategyChips: true,
        sources: typeof chipSources === "function" ? chipSources() : (chipSources || {}),
        groupBy: "tab",
        onOpen: key => {
          if (tabset?.entries.has(key)) tabset.activate(key);
        },
      });
      return row;
    }

    function refreshChips() {
      const next = renderChips();
      chipHost = next;
      settingsShell?.setCurrent(
        next?.children.length ? next : null,
        context.t("当前选择"),
      );
    }

    root.value = () => ({mountedTabs: [...mounted], activeKey});
    root.refreshChips = refreshChips;
    redraw();
    return root;
  }

  window.FTStrategyEditorTabs = Object.freeze({create});
})();
