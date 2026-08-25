(() => {
  function clone(value) {
    return value === undefined ? undefined : structuredClone(value);
  }

  function canonicalKey(key, field) {
    return FTSettingRules.storageKey(key, field);
  }

  function isEligible(key, field, manifest) {
    if (field?.scope_policy !== "overridable"
      || field?.execution_policy === "authoring_only") return false;
    const target = canonicalKey(key, field);
    const targetField = manifest?.defaults?.[target];
    return !targetField || (targetField.scope_policy === "overridable"
      && targetField.execution_policy !== "authoring_only");
  }

  function canonicalKeys(manifest) {
    const result = [];
    const seen = new Set();
    for (const [key, field] of Object.entries(manifest?.defaults || {})) {
      if (!isEligible(key, field, manifest)) continue;
      const target = canonicalKey(key, field);
      if (seen.has(target)) continue;
      seen.add(target); result.push(target);
    }
    return result;
  }

  function normalize(manifest, value) {
    const allowed = new Set(canonicalKeys(manifest));
    const result = {};
    for (const [key, item] of Object.entries(value || {})) {
      const field = manifest?.defaults?.[key];
      const target = canonicalKey(key, field);
      if (!allowed.has(target)) continue;
      if (Array.isArray(result[target]) && Array.isArray(item)) {
        result[target] = [...result[target], ...clone(item)];
      } else {
        result[target] = clone(item);
      }
    }
    return result;
  }

  function fieldsForTab(tabKey, manifest, values, scopeSide = "") {
    return Object.entries(manifest?.defaults || {})
      .filter(([key, field]) => field.tab_key === tabKey
        && isEligible(key, field, manifest)
        && FTSettingRules.isVisible(field, values)
        && (!scopeSide || !window.FTStrategyEditorScope?.fieldVisible
          || FTStrategyEditorScope.fieldVisible(manifest, key, scopeSide, values))
        && (!scopeSide || !window.FTStrategyEditorScope?.fieldEditable
          || FTStrategyEditorScope.fieldEditable(manifest, key, scopeSide)))
      .sort((left, right) => Number(left[1].order || 0) - Number(right[1].order || 0));
  }

  function visibleTabs(manifest, values, scopeSide = "") {
    return (manifest?.tab_lists?.["group-settings"] || []).filter(tab => (
      fieldsForTab(tab.key, manifest, values, scopeSide).length
    ));
  }

  function render({
    context, manifest, inheritedValues = {}, overrides: initial = {},
    manageTabs = false, mountedTabs: requestedMountedTabs,
    onlyTabs: requestedOnlyTabs,
    onMountedTabsChange, onChange, scopeSide = "", contentOnly = false,
  }) {
    const root = document.createElement("div");
    root.className = "backtest-group-overrides";
    let overrides = normalize(manifest, initial);
    let activeTab = "";
    const onlyTabs = Array.isArray(requestedOnlyTabs)
      ? new Set(requestedOnlyTabs) : null;
    let mountedTabs = Array.isArray(requestedMountedTabs)
      ? [...requestedMountedTabs] : null;

    const effectiveValues = () => ({...clone(inheritedValues), ...clone(overrides)});
    const has = key => Object.prototype.hasOwnProperty.call(overrides, key);
    const notify = () => onChange?.(root.value(), [...(mountedTabs || [])]);

    const redraw = () => {
      const values = effectiveValues();
      const tabs = visibleTabs(manifest, values, scopeSide);
      const usableTabs = manageTabs
        ? tabs.filter(tab => (mountedTabs || []).includes(tab.key))
        : onlyTabs ? tabs.filter(tab => onlyTabs.has(tab.key)) : tabs;
      if (!usableTabs.some(tab => tab.key === activeTab)) {
        activeTab = usableTabs[0]?.key || (manageTabs ? "__manage__" : "");
      }
      root.replaceChildren();
      if (!usableTabs.length && !manageTabs) {
        const empty = document.createElement("small");
        empty.textContent = context.t("没有可按组覆盖的设置");
        root.append(empty); return;
      }
      if (contentOnly && usableTabs.length === 1 && !manageTabs) {
        root.append(settingRows(
          fieldsForTab(usableTabs[0].key, manifest, values, scopeSide), values,
        ));
        return;
      }
      const items = usableTabs.map(tab => ({
        key: tab.key,
        label: context.t(tab.label || tab.key),
        description: tab.help_text ? context.t(tab.help_text) : "",
        panelClass: "backtest-group-override-panel",
        render: () => settingRows(
          fieldsForTab(tab.key, manifest, values, scopeSide), values,
        ),
      }));
      if (manageTabs) {
        items.push({
          key: "__manage__",
          label: context.t("+ 设置"),
          render: () => tabManager(tabs, context),
        });
      }
      const tabset = FTTabChipContent.create({
        items,
        activeKey: activeTab,
        barClass: "backend-settings-tab-bar backtest-group-override-tab-bar",
        hostClass: "backend-settings-host backtest-group-override-host",
        onActivate: key => { activeTab = key; },
      });
      root.append(tabset.bar, tabset.host);
    };

    const tabManager = (tabs, managerContext) => {
      const panel = document.createElement("div");
      panel.className = "backtest-group-override-tab-manager";
      const note = document.createElement("small");
      note.textContent = managerContext.t("选择要挂载到本策略设置栏的覆盖设置 Tab");
      panel.append(note);
      tabs.forEach(tab => {
        const label = document.createElement("label");
        label.className = "backtest-group-override-tab-option";
        const input = document.createElement("input");
        input.type = "checkbox";
        input.checked = (mountedTabs || []).includes(tab.key);
        input.addEventListener("change", () => {
          mountedTabs = tabs.filter(item => (
            item.key === tab.key ? input.checked : (mountedTabs || []).includes(item.key)
          )).map(item => item.key);
          onMountedTabsChange?.([...mountedTabs]);
          activeTab = tab.key;
          redraw();
          notify();
        });
        label.append(input, document.createTextNode(managerContext.t(tab.label || tab.key)));
        panel.append(label);
      });
      return panel;
    };

    const settingRows = (fields, values) => {
      const rows = document.createElement("div");
      rows.className = "backtest-group-override-rows";
      fields.forEach(([key, field]) => rows.append(settingRow(key, field, values)));
      return rows;
    };

    const settingRow = (key, field, values) => {
      const target = canonicalKey(key, field);
      const editable = FTSettingRules.isEditable(field, values);
      const scopeField = scopeSide && window.FTStrategyEditorScope?.scopedField?.(
        manifest, key, scopeSide,
      );
      const directOverride = scopeField?.override_control === "direct";
      if (!editable && has(target)) delete overrides[target];
      const enabled = directOverride ? null : document.createElement("input");
      if (enabled) {
        enabled.type = "checkbox"; enabled.checked = has(target);
        enabled.title = context.t("启用本组覆盖");
      }
      const control = FTTestSettings.controlFor(
        key, field, manifest, values, context,
        {
          onCommit: ({key: changedKey, field: changedField, value}) => {
            overrides[canonicalKey(changedKey, changedField)] = clone(value);
            notify();
          },
          onPatch: patch => {
            for (const [changedKey, value] of Object.entries(patch || {})) {
              const changedField = manifest?.defaults?.[changedKey];
              const changedTarget = canonicalKey(changedKey, changedField);
              if (canonicalKeys(manifest).includes(changedTarget)) {
                overrides[changedTarget] = clone(value);
              }
            }
            notify();
          },
          refresh: redraw,
        },
        (!directOverride && !enabled?.checked) || !editable,
      );
      if (enabled) enabled.addEventListener("change", () => {
        if (enabled.checked) {
          overrides[target] = clone(FTSettingRules.valueFor(key, field, values));
        } else {
          delete overrides[target];
        }
        redraw();
        notify();
      });
      const controlHost = document.createElement("div");
      controlHost.className = "backtest-group-override-control";
      if (editable && enabled) controlHost.append(enabled);
      else if (editable && directOverride) controlHost.classList.add("is-direct-override");
      else {
        controlHost.classList.add("is-locked");
        controlHost.setAttribute("aria-disabled", "true");
      }
      controlHost.append(control);
      const rowClass = [
        "backtest-group-override-row",
        target === "factor_role_bindings" ? "factor-candidate-child-row" : "",
      ].filter(Boolean).join(" ");
      return FTTestFieldRow.create(
        field.label || key,
        controlHost,
        window.FTTestFieldHelp?.forField?.(manifest, key, context) || "",
        {className: rowClass},
      );
    };

    root.value = () => normalize(manifest, overrides);
    // Nested factor candidates can change the visibility of role bindings
    // while the override panel is already mounted.  Expose the same redraw
    // used internally instead of rebuilding the whole strategy editor tab.
    root.refresh = redraw;
    redraw();
    return root;
  }

  window.FTBacktestGroupOverrides = Object.freeze({
    canonicalKey, canonicalKeys, normalize, render, visibleTabs,
  });
})();
