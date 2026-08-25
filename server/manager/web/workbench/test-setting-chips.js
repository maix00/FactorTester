(() => {
  function descriptors(options) {
    const manifest = options.manifest || {};
    const context = options.context || {t: value => value};
    const onlyKeys = options.onlyKeys ? new Set(options.onlyKeys) : null;
    const declaredTabs = tabDefinitions(manifest);
    const tabs = new Set(declaredTabs.map(item => item.key));
    const mounted = new Set(options.mountedTabs || []);
    const identity = (manifest.chip_fields || []).map(chip => identityChip(
      chip, options.sources || {}, tabs, mounted, context, options,
    )).filter(Boolean);
    const settings = Object.entries(manifest.defaults || {})
      .filter(([key, field]) => matchesOnlyKey(key, field, onlyKeys))
      .filter(([, field]) => mounted.has(field.tab_key)
        && (options.includeUnregistered || field.chip_template))
      .filter(([, field]) => field.show_chip !== false)
      .filter(([, field]) => options.includeHidden || FTSettingRules.isVisible(field, options.values || {}))
      .map(([key, field]) => settingChip(
      key, field, options.values || {}, context, options,
      )).filter(Boolean);
    const fallbackTabs = options.includeTabFallbacks
      ? (options.fallbackTabs || [...mounted]).filter(tabKey => tabs.has(tabKey))
      : [];
    for (const tabKey of fallbackTabs) {
      if (identity.some(item => item.tabKey === tabKey)
        || settings.some(item => item.tabKey === tabKey)) continue;
      const tab = declaredTabs.find(item => item.key === tabKey);
      settings.push(tabFallback(tabKey, tab, context, options));
    }
    const run = options.includeRun === false ? [] : runDescriptors(options);
    return deduplicate([...identity, ...settings, ...run, ...(options.extraDescriptors || [])])
      .map((item, index) => ({...item, _descriptorOrder: index}))
      .sort((left, right) => (
        Number(left.sortOrder ?? left._descriptorOrder)
        - Number(right.sortOrder ?? right._descriptorOrder)
        || left._descriptorOrder - right._descriptorOrder
      ))
      .map(({_descriptorOrder, ...item}) => item);
  }

  function tabDefinitions(manifest) {
    const definitions = [
      ...(manifest.tab_lists?.["local-settings"] || []),
      ...(manifest.tab_lists?.["group-settings"] || []),
      // Nested strategy editors declare their structure and default tabs in
      // the backend-owned strategy_editor contract. They are not ordinary
      // local-settings tabs, but their chips still need the same target-tab
      // and fallback treatment as every other mounted tab.
      ...(manifest.strategy_editor?.inner_default_tabs || []),
      ...(manifest.strategy_editor?.inner_manual_tabs || []),
    ];
    const seen = new Set();
    return definitions.filter(item => {
      if (!item?.key || seen.has(item.key)) return false;
      seen.add(item.key);
      return true;
    });
  }

  function matchesOnlyKey(key, field, onlyKeys) {
    if (!onlyKeys) return true;
    if (onlyKeys.has(key)) return true;
    const storageKey = window.FTSettingRules?.storageKey?.(key, field);
    return Boolean(storageKey && onlyKeys.has(storageKey));
  }

  function tabFallback(tabKey, tab, context, options) {
    const value = context.t(options.emptyValueLabel || "未设置（默认）");
    return {
      key: `tab-default:${tabKey}`,
      label: context.t(options.fallbackLabel || "默认"),
      value,
      fullValue: `${context.t(tab?.label || tabKey)}: ${value}`,
      tabKey,
      category: "setting-default",
      sortOrder: 0,
    };
  }

  function runDescriptors(options) {
    const manifest = options.manifest || {};
    const tabKey = manifest.run_settings?.key || "";
    return (manifest.run_fields || [])
      .filter(item => item.placement !== "global_settings")
      .filter(item => options.includeHidden || !window.FTSettingRules
        || window.FTSettingRules.isVisible(item, options.runValues || {}))
      .map(item => runChip(item, options, tabKey))
      .filter(Boolean);
  }

  function runChip(field, options, tabKey) {
    const context = options.context || {t: value => value};
    const raw = field.placement === "outputs"
      ? (Array.isArray(options.outputRequests) ? options.outputRequests : [])
      : Object.prototype.hasOwnProperty.call(options.runValues || {}, field.key)
        ? options.runValues[field.key] : field.default;
    let value = runValue(field, raw, options, context);
    if (!hasValue(value)) value = context.t("未设置（默认）");
    return {
      key: `run:${field.key}`,
      label: context.t(field.label || field.key),
      value: compact(value, context),
      fullValue: expanded(value),
      tabKey,
      category: "run",
      sortOrder: 1000 + Number(field.order || 0),
      order: Number(field.order || 0),
    };
  }

  function runValue(field, raw, options, context) {
    if (field.placement === "outputs") {
      const names = (Array.isArray(raw) ? raw : []).map(name => {
        const definition = (options.outputCapabilities || []).find(item => item.name === name);
        return definition ? context.t(definition.label || name) : name;
      });
      return names.length ? names : context.t("未选择（使用默认输出）");
    }
    if (field.value_descriptor?.editor === "profile") {
      if (!raw) return context.t("用户本人");
      const profileID = String(raw).replace(/^profile:/, "");
      const profile = (options.profiles || []).find(item => (
        String(item.profile_id || "") === profileID
      ));
      return profile ? `${profile.display_name || profileID}（${profileID}）` : profileID;
    }
    if ((raw === "" || raw == null) && field.key === "task_name") {
      return context.t("未命名（可选）");
    }
    return optionLabel(field, raw, context);
  }

  function identityChip(chip, sources, tabs, mounted, context, options = {}) {
    if (!(chip.source_keys || []).every(key => hasValue(sources[key]))) return null;
    const tabKey = targetTab(chip, tabs);
    if (!mounted.has(tabKey)) return null;
    if (isStrategyScoped(chip) && options.includeStrategyChips !== true) return null;
    const values = {};
    for (const name of placeholders(chip.chip_template)) {
      const resolver = chip.value_resolvers?.[name];
      values[name] = resolver
        ? resolveValue(resolver, chip, sources)
        : sources[name];
    }
    const rendered = interpolate(chip.chip_template, values, context);
    const parts = splitRendered(rendered, context.t(chip.label || chip.key));
    if (!hasValue(parts.value)) return null;
    return {
      key: `identity:${chip.key}`,
      label: parts.label,
      value: compact(parts.value, context),
      fullValue: expanded(parts.value),
      tabKey,
      category: chip.category || "identity",
      clickable: chip.clickable === true,
      detailOverlay: detailOverlay(chip, sources),
    };
  }

  function detailOverlay(chip, sources) {
    const action = chip.detail_overlay;
    if (!action || typeof action !== "object") return null;
    const sourceKey = action.source_key || action.sourceKey;
    const raw = sourceKey ? sources[sourceKey] : null;
    const values = Array.isArray(raw) ? raw.filter(hasValue) : [raw].filter(hasValue);
    // A compact chip may summarize several factor candidates or product
    // groups. Do not silently open the first one; only an unambiguous chip
    // can open a detail overlay.
    if (values.length !== 1) return null;
    const value = values[0];
    const object = value && typeof value === "object" ? value : null;
    const kindSourceKey = action.kind_source_key || action.kindSourceKey;
    const kind = kindSourceKey ? sources[kindSourceKey] : action.kind;
    if (!hasValue(kind)) return null;
    const ref = object
      ? object[action.ref_key || "ref"]
        || object.ref || object.group_ref || object.product_group_ref
        || object.product_group_template_id || object.product_path_selection_id
        || object.id || object.alias || object.name
      : value;
    if (!hasValue(ref)) return null;
    return {
      ...action,
      kind: String(kind),
      target: {ref: String(ref), value},
    };
  }

  function targetTab(chip, tabs) {
    if (tabs.has(chip.target_tab)) return chip.target_tab;
    return tabs.has(chip.key) ? chip.key : "";
  }

  function isStrategyScoped(chip) {
    // display_scope is the backend-owned declaration.  Keep the adapter
    // fallback so manifests produced by older servers do not leak the
    // primary strategy into the shared summary during a rolling upgrade.
    return chip.display_scope === "strategy"
      || (!chip.display_scope && chip.source_adapter === "primary_strategy_group");
  }

  function settingChip(key, field, values, context, options = {}) {
    const visible = !FTSettingRules || typeof FTSettingRules.isVisible !== "function"
      || FTSettingRules.isVisible(field, values);
    if (options.includeHidden && !visible) {
      const notApplicable = context.t(options.notApplicableLabel || "N/A");
      const template = field.chip_template || `${field.label || key}: {value}`;
      const rendered = interpolate(template, {value: notApplicable}, context);
      const parts = splitRendered(rendered, context.t(field.label || key));
      return {
        key: `setting:${key}`,
        label: parts.label,
        value: compact(parts.value, context),
        fullValue: expanded(parts.value),
        tabKey: field.tab_key || "",
        category: "setting-not-applicable",
      };
    }
    const raw = FTSettingRules && typeof FTSettingRules.displayValueFor === "function"
      ? FTSettingRules.displayValueFor(key, field, values)
      : FTSettingRules.valueFor(key, field, values);
    const empty = !hasValue(raw);
    if (empty && !options.includeEmpty) return null;
    const value = empty
      ? context.t(options.emptyValueLabel || "未设置（默认）")
      : optionLabel(field, raw, context);
    const template = field.chip_template || `${field.label || key}: {value}`;
    const rendered = interpolate(template, {value}, context);
    const parts = splitRendered(rendered, context.t(field.label || key));
    return {
      key: `setting:${key}`,
      label: parts.label,
      value: compact(parts.value, context),
      fullValue: expanded(parts.value),
      tabKey: field.tab_key || "",
      category: "setting",
    };
  }

  function render(options) {
    // The settings manager embeds this row inside a label.  Use phrasing
    // elements there so Safari does not repair a span/div tree while laying
    // out wrapped chips; the normal chip surface keeps its block elements.
    const inline = options.inline === true;
    const root = document.createElement(inline ? "span" : "div");
    root.className = "backend-settings-chip-row";
    const all = descriptors(options);
    const groupBy = options.groupBy || "tab";
    const grouped = new Map();
    for (const descriptor of all) {
      const group = groupKey(descriptor, groupBy);
      if (!grouped.has(group)) grouped.set(group, []);
      grouped.get(group).push(descriptor);
    }
    const groups = [...grouped.entries()];
    if (groupBy === "none") {
      for (const descriptor of all) root.append(renderChip(descriptor, options));
      return root;
    }
    groups.forEach(([group, items]) => {
      const host = document.createElement(inline ? "span" : "div");
      host.className = group ? "backend-settings-chip-group" : "backend-settings-chip-group ungrouped";
      const label = groupLabel(group, items, options, groupBy);
      if (label && (groupBy === "tab" || groups.length > 1)) {
        const heading = document.createElement("small");
        heading.className = "backend-settings-chip-group-label";
        heading.textContent = label;
        host.append(heading);
      }
      for (const descriptor of items) host.append(renderChip(descriptor, options));
      root.append(host);
    });
    return root;
  }

  function groupKey(descriptor, groupBy) {
    if (groupBy === "tab") return descriptor.tabKey || "";
    if (groupBy === "descriptor") return descriptor.group || "";
    return "";
  }

  function groupLabel(group, items, options, groupBy) {
    if (!group) return "";
    const context = options.context || {t: value => value};
    if (groupBy === "tab") {
      const manifest = options.manifest || {};
      if (manifest.run_settings?.key === group) {
        return context.t(manifest.run_settings.label || group);
      }
      const tab = tabDefinitions(manifest).find(item => item.key === group);
      return context.t(tab?.label || items[0]?.tabLabel || group);
    }
    return context.t(group);
  }

  function renderChip(descriptor, options) {
    const hasOverlay = descriptor.clickable === true
      && descriptor.detailOverlay
      && typeof options.onOverlay === "function";
    const interactive = Boolean(hasOverlay
      || (descriptor.tabKey && typeof options.onOpen === "function"));
    const chip = document.createElement(interactive ? "button" : "span");
    chip.className = `backend-setting-chip ${descriptor.category}`;
    if (interactive) {
      chip.type = "button";
      chip.addEventListener("click", () => {
        if (hasOverlay) options.onOverlay?.(descriptor);
        else options.onOpen?.(descriptor.tabKey);
      });
    }
    chip.title = hasOverlay
      ? `${descriptor.fullValue} · ${options.context?.t?.("查看详情") || "查看详情"}`
      : descriptor.fullValue;
    const label = document.createElement("span");
    label.className = "backend-setting-chip-label";
    label.textContent = descriptor.label;
    const value = document.createElement("span");
    value.className = "backend-setting-chip-value";
    value.textContent = descriptor.value;
    chip.append(label);
    if (hasValue(descriptor.value)) chip.append(value);
    return chip;
  }

  function optionLabel(field, value, context) {
    if (typeof value === "boolean") return context.t(value ? "开启" : "关闭");
    if (Array.isArray(value)) return value.map(item => optionLabel(field, item, context));
    const option = (field.value_descriptor?.options || [])
      .find(item => String(item.value) === String(value));
    return option ? context.t(option.label || option.value) : value;
  }

  function resolveValue(resolver, chip, sources) {
    const source = sources[(chip.source_keys || [])[0]];
    if (resolver === "product_path_selection_label") {
      return asArray(source).map(item => (
        item?.label || item?.title_zh || item?.name || item?.product_path_selection_id || item
      ));
    }
    if (resolver === "product_mask_count") {
      return Array.isArray(source)
        ? source.length : Object.values(source || {}).filter(Boolean).length;
    }
    if (resolver === "product_mask_expand_symbol") return "›";
    return sources[resolver] ?? sources[resolver.replace(/_([a-z])/g, (_, c) => c.toUpperCase())];
  }

  function interpolate(template, values, context) {
    return String(template || "{value}").replace(/\{([^{}]+)\}/g, (_, name) => (
      compact(values[name], context)
    ));
  }

  function splitRendered(rendered, fallbackLabel) {
    const match = String(rendered).match(/^\s*([^:：]+?)\s*[:：]\s*(.+)$/s);
    return match
      ? {label: match[1].trim(), value: match[2].trim()}
      : {label: fallbackLabel, value: String(rendered).trim()};
  }

  function compact(value, context) {
    if (Array.isArray(value)) {
      const items = value.filter(hasValue).map(item => compact(item, context));
      if (items.length <= 2) return items.join("、");
      return `${items.slice(0, 2).join("、")} +${items.length - 2}`;
    }
    if (value && typeof value === "object") {
      if (value.sampling) return horizonLabel(value, context);
      return value.label || value.title_zh || value.name || `${Object.keys(value).length} ${context.t("项")}`;
    }
    return value == null ? "" : String(value);
  }

  function expanded(value) {
    if (Array.isArray(value)) return value.map(expanded).join("、");
    if (value && typeof value === "object") {
      return value.label || value.title_zh || value.name || JSON.stringify(value);
    }
    return value == null ? "" : String(value);
  }

  function horizonLabel(value, context) {
    if (value.sampling !== "explicit") return context.t("尺度自适应");
    const bases = asArray(value.bases).join("/");
    const multipliers = asArray(value.multipliers).join("/");
    return [bases, multipliers].filter(Boolean).join(" × ");
  }

  function placeholders(template) {
    return [...String(template || "").matchAll(/\{([^{}]+)\}/g)].map(match => match[1]);
  }
  function asArray(value) { return Array.isArray(value) ? value : [value]; }
  function hasValue(value) {
    if (value === null || value === undefined || value === "") return false;
    if (Array.isArray(value)) return value.length > 0;
    return true;
  }
  function deduplicate(items) {
    const seen = new Set();
    return items.filter(item => {
      // The same default text may legitimately appear once for every
      // mounted tab.  De-duplicate repeated declarations inside one tab,
      // but never collapse two tab groups into one summary chip.
      const identity = `${item.tabKey || ""}\u0000${item.label}\u0000${item.value}`;
      if (seen.has(identity)) return false;
      seen.add(identity); return true;
    });
  }

  function openDetail(context, state, descriptor) {
    const action = descriptor?.detailOverlay;
    const target = action?.target;
    if (!action || !target || !window.FTTestObjectEditorOverlay?.open) return false;
    const value = target.value && typeof target.value === "object" ? target.value : null;
    const temporary = Boolean(value?.temporary
      || value?.source_kind === "transient"
      || value?.source_origin === "test_inline");
    const snapshot = action.kind === "factor"
      && value?.schema_version === 2
      && String(value?.ref || "") === String(target.ref);
    void FTTestObjectEditorOverlay.open(context, {
      kind: action.kind,
      mode: action.mode || "view",
      ref: target.ref,
      initialValue: value,
      temporary,
      snapshot,
      testState: state,
    }).catch(error => {
      context.showNotice?.(error.message || context.t("详情读取失败"), true);
    });
    return true;
  }

  window.FTTestSettingChips = Object.freeze({descriptors, openDetail, render});
})();
