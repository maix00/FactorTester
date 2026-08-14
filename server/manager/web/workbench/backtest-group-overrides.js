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

  function fieldsForTab(tabKey, manifest, values) {
    return Object.entries(manifest?.defaults || {})
      .filter(([key, field]) => field.tab_key === tabKey
        && isEligible(key, field, manifest)
        && FTSettingRules.isVisible(field, values))
      .sort((left, right) => Number(left[1].order || 0) - Number(right[1].order || 0));
  }

  function visibleTabs(manifest, values) {
    return (manifest?.tab_lists?.["group-settings"] || []).filter(tab => (
      fieldsForTab(tab.key, manifest, values).length
    ));
  }

  function render({context, manifest, inheritedValues = {}, overrides: initial = {}}) {
    const root = document.createElement("div");
    root.className = "backtest-group-overrides";
    let overrides = normalize(manifest, initial);
    let activeTab = "";

    const effectiveValues = () => ({...clone(inheritedValues), ...clone(overrides)});
    const has = key => Object.prototype.hasOwnProperty.call(overrides, key);
    const redraw = () => {
      const values = effectiveValues();
      const tabs = visibleTabs(manifest, values);
      if (!tabs.some(tab => tab.key === activeTab)) activeTab = tabs[0]?.key || "";
      root.replaceChildren();
      if (!tabs.length) {
        const empty = document.createElement("small");
        empty.textContent = context.t("没有可按组覆盖的设置");
        root.append(empty); return;
      }
      const tabset = FTTabChipContent.create({
        items: tabs.map(tab => ({
          key: tab.key,
          label: context.t(tab.label || tab.key),
          description: tab.help_text ? context.t(tab.help_text) : "",
          panelClass: "backtest-group-override-panel",
          render: () => settingRows(fieldsForTab(tab.key, manifest, values), values),
        })),
        activeKey: activeTab,
        barClass: "backend-settings-tab-bar backtest-group-override-tab-bar",
        hostClass: "backend-settings-host backtest-group-override-host",
        onActivate: key => { activeTab = key; },
      });
      root.append(tabset.bar, tabset.host);
    };

    const settingRows = (fields, values) => {
      const rows = document.createElement("div");
      rows.className = "backtest-group-override-rows";
      fields.forEach(([key, field]) => rows.append(settingRow(key, field, values)));
      return rows;
    };

    const settingRow = (key, field, values) => {
      const target = canonicalKey(key, field);
      const row = document.createElement("div");
      row.className = "backtest-group-override-row";
      const enabled = document.createElement("input");
      enabled.type = "checkbox"; enabled.checked = has(target);
      enabled.title = context.t("启用本组覆盖");
      const copy = document.createElement("span");
      const label = document.createElement("b"); label.textContent = field.label || key;
      const help = document.createElement("small");
      help.textContent = field.help_text || context.t("关闭时继承测试设置");
      copy.append(label, help);
      const editable = FTSettingRules.isEditable(field, values);
      const control = FTTestSettings.controlFor(
        key, field, manifest, values, context,
        {
          onCommit: ({key: changedKey, field: changedField, value}) => {
            overrides[canonicalKey(changedKey, changedField)] = clone(value);
          },
          onPatch: patch => {
            for (const [changedKey, value] of Object.entries(patch || {})) {
              const changedField = manifest?.defaults?.[changedKey];
              const changedTarget = canonicalKey(changedKey, changedField);
              if (canonicalKeys(manifest).includes(changedTarget)) {
                overrides[changedTarget] = clone(value);
              }
            }
          },
          refresh: redraw,
        },
        !enabled.checked || !editable,
      );
      enabled.addEventListener("change", () => {
        if (enabled.checked) {
          overrides[target] = clone(FTSettingRules.valueFor(key, field, values));
        } else {
          delete overrides[target];
        }
        redraw();
      });
      row.append(enabled, copy, control);
      return row;
    };

    root.value = () => normalize(manifest, overrides);
    redraw();
    return root;
  }

  window.FTBacktestGroupOverrides = Object.freeze({
    canonicalKey, canonicalKeys, normalize, render, visibleTabs,
  });
})();
