(() => {
  function descriptors(options) {
    const manifest = options.manifest || {};
    const context = options.context || {t: value => value};
    const tabs = new Set((manifest.tab_lists?.["local-settings"] || []).map(item => item.key));
    const mounted = new Set(options.mountedTabs || []);
    const identity = (manifest.chip_fields || []).map(chip => identityChip(
      chip, options.sources || {}, tabs, context,
    )).filter(Boolean);
    const settings = Object.entries(manifest.defaults || {})
      .filter(([, field]) => mounted.has(field.tab_key)
        && (options.includeUnregistered || field.chip_template))
      .filter(([, field]) => field.show_chip !== false)
      .filter(([, field]) => options.includeHidden || FTSettingRules.isVisible(field, options.values || {}))
      .map(([key, field]) => settingChip(
        key, field, options.values || {}, context, options,
      )).filter(Boolean);
    return deduplicate([...identity, ...settings, ...(options.extraDescriptors || [])]);
  }

  function identityChip(chip, sources, tabs, context) {
    if (!(chip.source_keys || []).every(key => hasValue(sources[key]))) return null;
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
    const fallback = tabs.has(chip.key) ? chip.key : "";
    return {
      key: `identity:${chip.key}`,
      label: parts.label,
      value: compact(parts.value, context),
      fullValue: expanded(parts.value),
      tabKey: tabs.has(chip.target_tab) ? chip.target_tab : fallback,
      category: chip.category || "identity",
    };
  }

  function settingChip(key, field, values, context, options = {}) {
    const raw = FTSettingRules.valueFor(key, field, values);
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
    const root = document.createElement("div");
    root.className = "backend-settings-chip-row";
    for (const descriptor of descriptors(options)) {
      const interactive = descriptor.tabKey && typeof options.onOpen === "function";
      const chip = document.createElement(interactive ? "button" : "span");
      chip.className = `backend-setting-chip ${descriptor.category}`;
      if (interactive) {
        chip.type = "button";
        chip.addEventListener("click", () => options.onOpen?.(descriptor.tabKey));
      }
      chip.title = descriptor.fullValue;
      const label = document.createElement("span");
      label.className = "backend-setting-chip-label";
      label.textContent = descriptor.label;
      const value = document.createElement("span");
      value.className = "backend-setting-chip-value";
      value.textContent = descriptor.value;
      chip.append(label);
      if (hasValue(descriptor.value)) chip.append(value);
      root.append(chip);
    }
    return root;
  }

  function optionLabel(field, value, context) {
    if (typeof value === "boolean") return context.t(value ? "开启" : "关闭");
    if (Array.isArray(value)) return value.map(item => optionLabel(field, item, context));
    const option = (field.options || []).find(item => String(item.value) === String(value));
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
      const identity = `${item.label}\u0000${item.value}`;
      if (seen.has(identity)) return false;
      seen.add(identity); return true;
    });
  }

  window.FTTestSettingChips = Object.freeze({descriptors, render});
})();
