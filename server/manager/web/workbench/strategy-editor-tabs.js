(() => {
  function unique(values) {
    return [...new Set((values || []).filter(Boolean))];
  }

  function defaultKeys(state) {
    return (state?.manifest?.strategy_editor?.inner_default_tabs || [])
      .map(item => item.key).filter(Boolean);
  }

  function eligibleOverrideTabs(state) {
    const outerOnly = new Set(state?.manifest?.strategy_editor?.outer_only_tabs || []);
    const registered = (state?.manifest?.tab_lists?.["group-settings"] || []).filter(tab => {
      if (outerOnly.has(tab.key)) return false;
      return Object.entries(state?.manifest?.defaults || {}).some(([key, field]) => (
        field.tab_key === tab.key
        && field.scope_policy === "overridable"
        && field.execution_policy !== "authoring_only"
        && (!window.FTSettingRules || FTSettingRules.isVisible(field, state.values || {}))
      ));
    });
    const manual = (state?.manifest?.strategy_editor?.inner_manual_tabs || []).filter(tab => (
      !outerOnly.has(tab.key) && tab.mount_policy === "manual"
    ));
    const seen = new Set(registered.map(tab => tab.key));
    return [...registered, ...manual.filter(tab => !seen.has(tab.key))];
  }

  function create(options = {}) {
    const {
      context, state, mountedTabs: requested = [], onMountedTabsChange,
      onActivate, renderStructure, renderFactor, renderProduct,
      renderProductFilter, renderOverrides, chipValues, chipSources,
    } = options;
    const root = document.createElement("section");
    root.className = "strategy-editor-tabs";
    let mounted = unique([...defaultKeys(state), ...requested]);
    let activeKey = "";
    let tabset = null;
    let chipHost = null;

    const manager = () => {
      const panel = document.createElement("div");
      panel.className = "strategy-editor-tab-manager";
      const note = document.createElement("small");
      note.textContent = context.t("默认挂载分组、因子执行和产品组；其他覆盖设置可手动挂载");
      panel.append(note);
      eligibleOverrideTabs(state).forEach(tab => {
        const row = document.createElement("label");
        row.className = "strategy-editor-tab-option";
        const checkbox = document.createElement("input");
        checkbox.type = "checkbox";
        checkbox.checked = mounted.includes(tab.key);
        checkbox.addEventListener("change", () => {
          mounted = unique([...defaultKeys(state), ...mounted.filter(key => (
            key !== tab.key
          )), ...(checkbox.checked ? [tab.key] : [])]);
          onMountedTabsChange?.([...mounted]);
          redraw(tab.key);
        });
        row.append(checkbox, document.createTextNode(context.t(tab.label || tab.key)));
        panel.append(row);
      });
      return panel;
    };

    function items() {
      const tabs = FTStrategyEditorScope.innerTabs(state, mounted);
      const result = tabs.map(tab => ({
        key: tab.key,
        label: context.t(tab.label || tab.key),
        description: tab.description ? context.t(tab.description) : "",
        render: () => {
          if (tab.key === "__strategy__") return renderStructure?.() || document.createElement("div");
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
      root.replaceChildren();
      tabset = FTTabChipContent.create({
        items: nextItems,
        activeKey,
        barClass: "backend-settings-tab-bar strategy-editor-tab-bar",
        hostClass: "backend-settings-host strategy-editor-tab-host",
        onActivate: key => { activeKey = key; onActivate?.(key); },
      });
      chipHost = renderChips();
      root.append(tabset.bar);
      if (chipHost?.children.length) root.append(chipHost);
      root.append(tabset.host);
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
        sources: typeof chipSources === "function" ? chipSources() : (chipSources || {}),
        groupBy: "tab",
        onOpen: key => {
          if (tabset?.entries.has(key)) tabset.activate(key);
        },
      });
      row.classList.add("strategy-editor-chip-row");
      return row;
    }

    function refreshChips() {
      if (!chipHost) return;
      const next = renderChips();
      if (!next) { chipHost.remove(); chipHost = null; return; }
      chipHost.replaceWith(next);
      chipHost = next;
    }

    root.value = () => ({mountedTabs: [...mounted], activeKey});
    root.refreshChips = refreshChips;
    redraw();
    return root;
  }

  window.FTStrategyEditorTabs = Object.freeze({create});
})();
