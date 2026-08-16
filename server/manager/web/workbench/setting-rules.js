(() => {
  const metadata = new WeakMap();

  function clone(value) {
    if (value === undefined) return undefined;
    return structuredClone(value);
  }

  function storageKey(key, field) {
    return field?.serialization?.storage_key || key;
  }

  function rulesFor(field) {
    return field?.rules || {};
  }

  function conditionsMatch(conditions, values) {
    return Object.entries(conditions || {}).every(([key, allowed]) => {
      const choices = Array.isArray(allowed) ? allowed : [allowed];
      return choices.some(value => String(value) === String(values?.[key]));
    });
  }

  function isVisible(field, values) {
    return conditionsMatch(rulesFor(field).visible_if, values);
  }

  function isEditable(field, values) {
    return conditionsMatch(rulesFor(field).editable_if, values);
  }

  function engineValue(values) {
    return String(values?.engine ?? values?.engine_mode ?? "");
  }

  function conditionalDefault(field, values) {
    const rules = rulesFor(field);
    for (const [sourceKey, mapping] of Object.entries(rules.default_if || {})) {
      const source = String(values?.[sourceKey]);
      if (Object.prototype.hasOwnProperty.call(mapping || {}, source)) {
        return {found: true, value: clone(mapping[source])};
      }
    }
    const byEngine = rules.engine_defaults || {};
    const engine = engineValue(values);
    if (engine && Object.prototype.hasOwnProperty.call(byEngine, engine)) {
      return {found: true, value: clone(byEngine[engine])};
    }
    return {found: false, value: undefined};
  }

  // Chip previews and editors use the same effective value semantics.  When
  // a visible field is locked by a condition, its declared/conditional
  // default is the value users should see; a stale manual value must not leak
  // into the preview.
  function displayValueFor(key, field, values) {
    const raw = valueFor(key, field, values);
    if (isEditable(field, values)) return raw;
    const next = conditionalDefault(field, values);
    return next.found ? next.value : clone(field?.value);
  }

  function applyAutomaticDefaults(manifest, values) {
    const state = metadata.get(values) || {manual: new Set()};
    metadata.set(values, state);
    const fields = Object.entries(manifest?.defaults || {});
    for (let pass = 0; pass < fields.length; pass += 1) {
      let changed = false;
      for (const [key, field] of fields) {
        const target = storageKey(key, field);
        if (state.manual.has(target)) continue;
        const next = conditionalDefault(field, values);
        if (!next.found || Object.is(values[target], next.value)) continue;
        values[target] = next.value;
        changed = true;
      }
      if (!changed) break;
    }
    return values;
  }

  function initialValues(manifest, saved = {}, options = {}) {
    const values = {};
    const manual = new Set();
    const mounted = Array.isArray(options.mountedTabs)
      ? new Set(options.mountedTabs) : null;
    const savedTargets = new Set();
    if (mounted) {
      for (const [key, field] of Object.entries(manifest?.defaults || {})) {
        if (mounted.has(field?.tab_key)) savedTargets.add(storageKey(key, field));
      }
    }
    for (const [key, field] of Object.entries(manifest?.defaults || {})) {
      const target = storageKey(key, field);
      const canRestore = !mounted || mounted.has(field?.tab_key) || savedTargets.has(target);
      if (canRestore && Object.prototype.hasOwnProperty.call(saved, target)) {
        values[target] = clone(saved[target]);
        manual.add(target);
      } else if (canRestore && Object.prototype.hasOwnProperty.call(saved, key)) {
        values[target] = clone(saved[key]);
        manual.add(target);
      } else if (!Object.prototype.hasOwnProperty.call(values, target)) {
        values[target] = clone(field.value);
      }
    }
    metadata.set(values, {manual});
    return applyAutomaticDefaults(manifest, values);
  }

  function previewDefaultsForTab(manifest, values, tabKey) {
    const preview = clone(values || {}) || {};
    const manual = new Set();
    for (const [key, field] of Object.entries(manifest?.defaults || {})) {
      const target = storageKey(key, field);
      if (field?.tab_key !== tabKey) {
        manual.add(target);
        continue;
      }
      const serialization = field?.serialization || {};
      if (serialization.kind === "custom_product_overrides") {
        const moduleName = String(serialization.module_filter || "");
        const scopedFields = new Set((serialization.fields || [])
          .filter(item => !moduleName || String(item.module || "") === moduleName)
          .map(item => String(item.value)));
        preview[target] = (Array.isArray(preview[target]) ? preview[target] : [])
          .filter(row => !scopedFields.has(String(row?.field || "")));
      } else {
        preview[target] = clone(field.value);
      }
    }
    metadata.set(preview, {manual});
    return applyAutomaticDefaults(manifest, preview);
  }

  function setValue(manifest, values, key, field, value) {
    const target = storageKey(key, field);
    const state = metadata.get(values) || {manual: new Set()};
    state.manual.add(target);
    metadata.set(values, state);
    values[target] = value;
    return applyAutomaticDefaults(manifest, values);
  }

  function resetValue(manifest, values, key, field, options = {}) {
    const target = storageKey(key, field);
    const state = metadata.get(values) || {manual: new Set()};
    const hasOverride = Object.prototype.hasOwnProperty.call(options, "value");
    const value = hasOverride ? options.value : field?.value;
    if (options.keepManual) state.manual.add(target);
    else state.manual.delete(target);
    metadata.set(values, state);
    values[target] = clone(value);
    return applyAutomaticDefaults(manifest, values);
  }

  function patchValues(manifest, values, patch) {
    const fields = manifest?.defaults || {};
    for (const [key, value] of Object.entries(patch || {})) {
      setValue(manifest, values, key, fields[key], value);
    }
    return values;
  }

  function valueFor(key, field, values) {
    return values?.[storageKey(key, field)];
  }

  function disabledValues(field, values) {
    const engine = engineValue(values);
    const choices = rulesFor(field).disabled_values?.[engine] || [];
    return new Set(choices.map(String));
  }

  window.FTSettingRules = Object.freeze({
    initialValues, previewDefaultsForTab, setValue, resetValue, patchValues, valueFor, storageKey,
    rulesFor, conditionsMatch, isVisible, isEditable, displayValueFor, disabledValues,
    applyAutomaticDefaults,
  });
})();
