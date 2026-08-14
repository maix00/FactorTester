(() => {
  const supportedControlTemplates = Object.freeze([
    "boolean", "custom", "custom_product_overrides", "date",
    "factor_role_bindings", "ic_decay_grid", "ic_delay_grid",
    "ic_horizon_grid", "number", "select", "text", "time",
  ]);
  const supportedControlSet = new Set(supportedControlTemplates);
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
    return FTICHorizonSettings.normalizeSettingValues(
      manifest, FTSettingRules.initialValues(manifest, saved, {mountedTabs}),
    );
  }

  function render(manifest, values, context, options = {}) {
    const root = document.createElement("div");
    root.className = "backend-settings-shell test-settings-shell";
    const tabs = manifest.tab_lists?.["local-settings"] || [];
    const available = tabs.map(tab => ({
      tab, fields: visibleFields(tab, manifest, values),
      allFields: fieldsForTab(tab.key, manifest).filter(([, field]) => !field.adapter_managed),
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
        render: () => FTTestRunFields.panel(
          context, options.state, options.refresh,
        ),
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
    const activeKey = items.some(item => item.key === options.activeTab)
      ? options.activeTab : items[0]?.key;
    tabset = FTTabChipContent.create({
      items, context, activeKey,
      onActivate: key => options.onTabChange?.(key),
    });
    root.append(tabset.bar);
    const chips = FTTestSettingChips.render({
      manifest, values, context,
      mountedTabs: [...mounted],
      sources: options.chipSources || {},
      runValues: options.state?.runValues || {},
      outputRequests: options.state?.outputRequests || [],
      outputCapabilities: options.state?.outputCapabilities || [],
      profiles: options.state?.profiles || [],
      extraDescriptors: options.extraChips || [],
      onOpen: tabKey => {
        if (tabset?.entries.has(tabKey)) tabset.activate(tabKey);
        else options.onChipOpen?.(tabKey);
      },
    });
    if (chips.children.length) {
      const current = document.createElement("section");
      current.className = "test-settings-current";
      const heading = document.createElement("strong");
      heading.textContent = context.t("当前选择");
      current.append(heading, chips);
      root.append(current);
    }
    root.append(tabset.host);
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
    const adapted = FTTestContentAdapters.render(item.tab, {
      context, state: options.state, refresh: options.refresh,
      tab: item.tab,
      actions: options.actions || {},
    });
    if (adapted) panel.append(adapted);
    if (item.fields.length) {
      const rows = document.createElement("div");
      rows.className = "test-setting-rows";
      item.fields.forEach(([key, field]) => {
        rows.append(settingRow(key, field, manifest, values, context, options));
      });
      panel.append(rows);
    }
    return panel;
  }

  function settingsManager(manifest, available, mounted, values, context, options) {
    const root = document.createElement("div");
    root.className = "test-settings-manager";
    const list = document.createElement("div");
    list.className = "test-settings-manager-list";
    settingsSections(manifest, available).forEach(section => {
      const sectionHeader = document.createElement("header");
      sectionHeader.className = "test-settings-manager-section-heading";
      const title = document.createElement("b");
      title.textContent = context.t(section.label);
      sectionHeader.append(title);
      if (section.description) {
        sectionHeader.title = context.t(section.description);
      }
      list.append(sectionHeader);
      section.items.forEach(item => {
        const row = document.createElement("label");
        row.className = "test-settings-manager-row";
        const toggle = document.createElement("input");
        toggle.type = "checkbox";
        toggle.checked = mounted.has(item.tab.key);
        toggle.addEventListener("change", () => {
          if (!toggle.checked) resetTabValues(manifest, values, item.tab.key);
          const next = available.map(value => value.tab.key).filter(key => (
            key === item.tab.key ? toggle.checked : mounted.has(key)
          ));
          options.onMountedTabsChange?.(next, item.tab.key, toggle.checked);
        });
        const body = document.createElement("span");
        body.className = "test-settings-manager-row-body";
        const copy = document.createElement("span");
        const label = document.createElement("b");
        label.textContent = context.t(item.tab.label || item.tab.key);
        copy.append(label);
        if (item.tab.help_text) row.title = context.t(item.tab.help_text);
        const defaults = FTTestSettingChips.render({
          manifest,
          values: FTSettingRules.previewDefaultsForTab(manifest, values, item.tab.key),
          context,
          mountedTabs: [item.tab.key],
          includeRun: false,
          includeEmpty: true,
          includeUnregistered: true,
          includeHidden: true,
          sources: {},
        });
        defaults.className = `${defaults.className} test-settings-manager-defaults`.trim();
        body.append(copy, defaults);
        row.append(toggle, body);
        list.append(row);
      });
    });
    root.append(list);
    return root;
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

  function visibleFields(tab, manifest, values) {
    return fieldsForTab(tab.key, manifest).filter(([, field]) => {
      return !field.adapter_managed && FTSettingRules.isVisible(field, values);
    });
  }

  function fieldsForTab(tabKey, manifest) {
    return Object.entries(manifest.defaults || {})
      .filter(([, field]) => field.tab_key === tabKey)
      .sort((left, right) => Number(left[1].order || 0) - Number(right[1].order || 0));
  }

  function settingRow(key, field, manifest, values, context, options) {
    const row = document.createElement("div");
    row.className = "test-setting-row";
    const copy = document.createElement("span");
    const label = document.createElement("b");
    label.textContent = field.label || key;
    copy.append(label);
    const editable = FTSettingRules.isEditable(field, values);
    const hints = [field.help_text];
    if (!editable && Object.keys(field.editable_when || {}).length) {
      hints.push(context.t("当前模式使用自动值"));
    }
    const hint = hints.filter(Boolean).join("\n");
    if (hint) {
      row.title = hint;
      row.setAttribute("aria-label", `${label.textContent}: ${hint}`);
    }
    row.append(copy, inputFor(key, field, manifest, values, context, options, !editable));
    return row;
  }

  function commit(key, field, manifest, values, value, options) {
    if (typeof options.onCommit === "function") {
      options.onCommit({key, field, value});
    } else {
      FTSettingRules.setValue(manifest, values, key, field, value);
    }
    options.refresh?.();
  }

  function commitPatch(manifest, values, patch, options) {
    if (typeof options.onPatch === "function") {
      options.onPatch(patch);
    } else {
      FTSettingRules.patchValues(manifest, values, patch);
    }
    options.refresh?.();
  }

  function inputFor(key, field, manifest, values, context, options, disabled) {
    if (!supportedControlSet.has(field.control_template)) {
      throw new Error(`未实现的测试设置控件: ${field.control_template}`);
    }
    const value = FTSettingRules.valueFor(key, field, values);
    if (field.control_template === "ic_horizon_grid") {
      return FTICHorizonSettings.renderHorizon({
        value, context, disabled,
        onChange: next => commit(key, field, manifest, values, next, options),
      });
    }
    if (field.control_template === "ic_delay_grid") {
      return FTICHorizonSettings.renderDelays({
        value, context, disabled,
        onChange: next => commit(key, field, manifest, values, next, options),
      });
    }
    if (field.control_template === "ic_decay_grid") {
      return FTICHorizonSettings.renderDecayLags({
        value, context, disabled,
        onChange: next => commit(key, field, manifest, values, next, options),
      });
    }
    if (field.control_template === "factor_role_bindings") {
      return FTTestFactorRoles.render({
        field, values, context, disabled, value,
        onChange: next => commit(key, field, manifest, values, next, options),
      });
    }
    if (field.control_template === "custom_product_overrides") {
      return FTCustomProductOverrides.render({
        key, field, manifest, values, context, disabled,
        onPatch: patch => commitPatch(manifest, values, patch, options),
      });
    }
    let control;
    if (field.control_template === "boolean") {
      control = document.createElement("input");
      control.type = "checkbox";
      control.checked = Boolean(value);
      control.disabled = disabled;
      control.addEventListener("change", () => {
        commit(key, field, manifest, values, control.checked, options);
      });
      return control;
    }
    if (field.control_template === "select" && field.options?.length) {
      control = document.createElement("select");
      const disabledValues = FTSettingRules.disabledValues(field, values);
      for (const option of field.options) {
        const item = document.createElement("option");
        item.value = String(option.value ?? "");
        item.textContent = option.label || item.value;
        item.disabled = disabledValues.has(item.value);
        control.append(item);
      }
      control.value = String(value ?? "");
    } else if (field.control_template === "custom") {
      control = document.createElement("textarea");
      control.className = "json-code json-editor";
      control.rows = 3;
      control.value = JSON.stringify(value ?? null, null, 2);
      control.disabled = disabled;
      control.addEventListener("change", () => {
        try {
          const next = JSON.parse(control.value);
          control.setCustomValidity("");
          commit(key, field, manifest, values, next, options);
        } catch (_) {
          control.setCustomValidity(context.t("JSON 格式无效"));
          control.reportValidity?.();
        }
      });
      return control;
    } else {
      control = document.createElement("input");
      control.type = ["date", "time", "number"].includes(field.control_template)
        ? field.control_template : "text";
      control.value = value ?? "";
      if (field.minimum != null) control.min = field.minimum;
      if (field.maximum != null) control.max = field.maximum;
      if (field.step != null) control.step = field.step;
    }
    control.disabled = disabled;
    control.addEventListener("change", () => {
      const next = control.type === "number" && control.value !== ""
        ? Number(control.value) : control.value;
      commit(key, field, manifest, values, next, options);
    });
    return control;
  }

  window.FTTestSettings = Object.freeze({
    initialValues, render, controlFor: inputFor,
    initialMountedTabs, resetTabValues, supportedControlTemplates,
    supportsControl: control => supportedControlSet.has(control),
  });
})();
