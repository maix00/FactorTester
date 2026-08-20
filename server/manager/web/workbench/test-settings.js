(() => {
  const fields = () => window.FTTestSettingFields;

  // The settings shell is intentionally usable before the field-control
  // module arrives.  This keeps the tab bar, chips and manager responsive;
  // the active panel asks for the control implementation only when it needs
  // to materialize an editable row.
  function declaredFieldsForTab(tabKey, manifest) {
    return Object.entries(manifest?.defaults || {})
      .filter(([, field]) => field?.tab_key === tabKey)
      .sort((left, right) => Number(left[1]?.order || 0) - Number(right[1]?.order || 0));
  }

  function fieldsForTab(tabKey, manifest) {
    return fields()?.fieldsForTab(tabKey, manifest)
      || declaredFieldsForTab(tabKey, manifest);
  }

  function visibleFields(tab, manifest, values) {
    return fields()?.visibleFields(tab, manifest, values)
      || fieldsForTab(tab.key, manifest).filter(([, field]) => (
        !field.adapter_managed && FTSettingRules.isVisible(field, values)
      ));
  }
  function initialMountedTabs(manifest, saved) {
    const tabs = manifest?.tab_lists?.["local-settings"] || [];
    const available = new Set(tabs.filter(tab => (
      FTTestContentAdapters.hasContent(tab)
      || visibleFields(tab, manifest, {}).length
    )).map(tab => tab.key));
    if (Array.isArray(saved)) return saved.filter(key => available.has(key));
    const mounted = new Set((manifest?.default_mounted_tabs?.["local-settings"] || [])
      .filter(key => available.has(key)));
    return tabs.map(tab => tab.key).filter(key => mounted.has(key));
  }

  function initialValues(manifest, saved = {}, mountedTabs) {
    const values = FTSettingRules.initialValues(manifest, saved, {mountedTabs});
    return window.FTICHorizonSettings?.normalizeSettingValues
      ? FTICHorizonSettings.normalizeSettingValues(manifest, values) : values;
  }

  function render(manifest, values, context, options = {}) {
    const root = document.createElement("div");
    root.className = "backend-settings-shell test-settings-shell";
    const tabs = manifest.tab_lists?.["local-settings"] || [];
    const available = tabs.map(tab => ({
      tab, fields: visibleFields(tab, manifest, values),
      allFields: fieldsForTab(tab.key, manifest)
        .filter(([, field]) => !field.adapter_managed),
    })).filter(item => item.allFields.length || FTTestContentAdapters.hasContent(item.tab));
    const mounted = new Set(options.mountedTabs || initialMountedTabs(manifest));
    const visible = available.filter(item => mounted.has(item.tab.key));
    let tabset = null;
    const items = [];
    const runTab = manifest?.run_settings;
    if (runTab?.key && options.state) {
      items.push({
        key: runTab.key,
        label: context.t(runTab.label || runTab.key),
        panelClass: "run-settings-tab-panel",
        render: () => {
          if (!window.FTTestRunFields) {
            options.ensureRunCode?.();
            return FTUI.loading(context.t("正在读取运行配置…"));
          }
          return FTTestRunFields.panel(context, options.state, options.refresh);
        },
      });
    }
    items.push(...visible.map(item => ({
      key: item.tab.key,
      label: context.t(item.tab.label || item.tab.key),
      render: () => tabPanel(item, manifest, values, context, options),
    })));
    if (!items.length) return root;
    items.push({
      key: "__manage__",
      label: context.t("+ 设置"),
      render: () => settingsManager(manifest, available, mounted, values, context, options),
    });
    const activeKey = options.activeTab === null
      ? null
      : (items.some(item => item.key === options.activeTab)
        ? options.activeTab : items[0]?.key);
    const settingsShell = FTTabChipContent.createSettings({
      root,
      items, context, activeKey,
      onActivate: key => options.onTabChange?.(key),
    });
    tabset = settingsShell.tabset;
    if (window.FTTestSettingChips) {
      const chips = FTTestSettingChips.render({
        manifest, values, context,
        mountedTabs: [...mounted],
        includeUnregistered: true,
        includeStrategyChips: false,
        sources: options.chipSources || {},
        runValues: options.state?.runValues || {},
        outputRequests: options.state?.outputRequests || [],
        outputCapabilities: options.state?.outputCapabilities || [],
        profiles: options.state?.profiles || [],
        extraDescriptors: options.extraChips || [],
        groupBy: "tab",
        onOpen: tabKey => {
          if (tabset?.entries.has(tabKey)) tabset.toggle(tabKey);
          else options.onChipOpen?.(tabKey);
        },
      });
      if (chips.children.length) {
        settingsShell.setCurrent(chips, context.t("当前选择"));
      }
    }
    root.activate = tabKey => {
      if (!tabset.entries.has(tabKey)) return false;
      tabset.activate(tabKey);
      return true;
    };
    return root;
  }

  function settingsSections(manifest, available) {
    const declared = Array.isArray(manifest?.settings_sections)
      ? [...manifest.settings_sections].sort((left, right) => (
        Number(left.order || 0) - Number(right.order || 0)
      )) : [];
    const byKey = new Map(declared.map(section => [section.key, {
      ...section, items: [],
    }]));
    const fallback = {
      key: "general", label: "设置", description: "", order: 999, items: [],
    };
    available.forEach(item => {
      const key = String(item.tab.section_key || "general");
      const section = byKey.get(key) || fallback;
      section.items.push(item);
    });
    if (fallback.items.length) byKey.set(fallback.key, fallback);
    return [...byKey.values()]
      .filter(section => section.items.length)
      .sort((left, right) => Number(left.order || 0) - Number(right.order || 0));
  }

  function tabPanel(item, manifest, values, context, options) {
    const panel = document.createElement("div");
    panel.className = "test-settings-tab-content";
    const lazyKey = FTTestContentAdapters.lazyKey(item.tab);
    const lazyState = lazyKey ? options.lazyState?.(lazyKey) : null;
    if (!fields()) {
      const load = options.settingsFieldsLoadState?.();
      panel.append(load?.status === "error"
        ? FTUI.empty(
          context.t("读取设置控件失败"),
          load.error || context.t("请重试"),
        )
        : FTUI.loading(context.t("正在读取设置控件…")));
      if (load?.status !== "error") options.ensureSettingsFieldsCode?.();
      if (lazyKey && lazyState?.status !== "ready") options.ensureTab?.(item.tab);
      return panel;
    }
    if (item.fields.length && options.ensureSettingsTab
      && !options.settingsTabReady?.(item.tab.key)) {
      // The summary already contains the registered field descriptors needed
      // for the first paint.  The tab endpoint only fills in heavyweight
      // metadata (help/ranges), so it must not be a rendering barrier.
      options.ensureSettingsTab(item.tab.key);
    }

    // Registered rows are the stable shell of every settings tab.  Draw them
    // before asking a content adapter to fetch any catalog candidates.
    if (item.fields.length) {
      const rows = document.createElement("div");
      rows.className = "test-setting-rows";
      item.fields.forEach(([key, field]) => {
        rows.append(fields().settingRow(key, field, manifest, values, context, options));
      });
      panel.append(rows);
    }

    const adapterReady = FTTestContentAdapters.isReady?.(item.tab) !== false;
    if (adapterReady && FTTestContentAdapters.hasContent(item.tab)) {
      const adapted = FTTestContentAdapters.render(item.tab, {
        context, state: options.state, refresh: options.refresh,
        tab: item.tab,
        actions: options.actions || {},
      });
      if (adapted) panel.append(adapted);
    } else if (FTTestContentAdapters.hasContent(item.tab)) {
      // This is only a code-loading fallback.  Catalog values are loaded by
      // the adapter after its shell is present, rather than hiding the rows.
      panel.append(FTUI.loading(context.t("正在读取设置控件…")));
    }

    if (lazyKey && lazyState?.status !== "ready" && lazyState?.status !== "error") {
      options.ensureTab?.(item.tab);
    }
    return panel;
  }

  function settingsManager(manifest, available, mounted, values, context, options) {
    return FTTabChipContent.createSettingsManager({
      context,
      sections: settingsSections(manifest, available).map(section => ({
        label: section.label,
        description: section.description,
        items: section.items.map(item => ({
          key: item.tab.key,
          label: item.tab.label || item.tab.key,
          description: item.tab.help_text || "",
          mounted: mounted.has(item.tab.key),
          onToggle: checked => {
            if (!checked) resetTabValues(manifest, values, item.tab.key);
            const next = available.map(value => value.tab.key).filter(key => (
              key === item.tab.key ? checked : mounted.has(key)
            ));
            options.onMountedTabsChange?.(next, item.tab.key, checked);
          },
          preview: () => window.FTTestSettingChips ? FTTestSettingChips.render({
            manifest,
            values: FTSettingRules.previewDefaultsForTab(manifest, values, item.tab.key),
            context,
            mountedTabs: [item.tab.key],
            includeRun: false,
            includeEmpty: true,
            includeUnregistered: true,
            includeHidden: true,
            notApplicableLabel: "N/A",
            includeTabFallbacks: true,
            fallbackTabs: [item.tab.key],
            groupBy: "tab",
            sources: {},
            inline: true,
          }) : null,
        })),
      })),
    });
  }

  function resetTabValues(manifest, values, tabKey) {
    for (const [key, field] of fieldsForTab(tabKey, manifest)) {
      const serialization = field?.serialization || {};
      const target = serialization.storage_key || key;
      if (serialization.kind !== "custom_product_overrides") {
        FTSettingRules.resetValue(manifest, values, key, field);
        continue;
      }
      const moduleName = String(serialization.module_filter || "");
      const scopedFields = new Set((serialization.fields || [])
        .filter(item => !moduleName || String(item.module || "") === moduleName)
        .map(item => String(item.value)));
      const retained = (Array.isArray(values[target]) ? values[target] : [])
        .filter(row => !scopedFields.has(String(row?.field || "")));
      FTSettingRules.resetValue(manifest, values, key, field, {
        value: retained, keepManual: retained.length > 0,
      });
    }
  }

  window.FTTestSettings = Object.freeze({
    initialValues, render,
    controlFor: (...args) => {
      if (!fields()) throw new Error("设置控件代码尚未加载");
      return fields().inputFor(...args);
    },
    initialMountedTabs, resetTabValues,
    get supportedEditors() {
      return fields()?.supportedEditors || [];
    },
    supportsEditor: editor => Boolean(fields()?.supportsEditor(editor)),
  });
})();
