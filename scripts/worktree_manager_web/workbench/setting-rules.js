(() => {
  const metadata = new WeakMap();

  function clone(value) {
    if (value === undefined) return undefined;
    return structuredClone(value);
  }

  function storageKey(key, field) {
    return field?.serialization?.storage_key || key;
  }

  function conditionsMatch(conditions, values) {
    return Object.entries(conditions || {}).every(([key, allowed]) => {
      const choices = Array.isArray(allowed) ? allowed : [allowed];
      return choices.some(value => String(value) === String(values?.[key]));
    });
  }

  function isVisible(field, values) {
    return conditionsMatch(field?.visible_when, values);
  }

  function isEditable(field, values) {
    return conditionsMatch(field?.editable_when, values);
  }

  function engineValue(values) {
    return String(values?.engine ?? values?.engine_mode ?? "");
  }

  function conditionalDefault(field, values) {
    for (const [sourceKey, mapping] of Object.entries(field?.default_when || {})) {
      const source = String(values?.[sourceKey]);
      if (Object.prototype.hasOwnProperty.call(mapping || {}, source)) {
        return {found: true, value: clone(mapping[source])};
      }
    }
    const byEngine = field?.engine_defaults || {};
    const engine = engineValue(values);
    if (engine && Object.prototype.hasOwnProperty.call(byEngine, engine)) {
      return {found: true, value: clone(byEngine[engine])};
    }
    return {found: false, value: undefined};
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

  function initialValues(manifest, saved = {}) {
    const values = {};
    const manual = new Set();
    for (const [key, field] of Object.entries(manifest?.defaults || {})) {
      const target = storageKey(key, field);
      if (Object.prototype.hasOwnProperty.call(saved, target)) {
        values[target] = clone(saved[target]);
        manual.add(target);
      } else if (Object.prototype.hasOwnProperty.call(saved, key)) {
        values[target] = clone(saved[key]);
        manual.add(target);
      } else if (!Object.prototype.hasOwnProperty.call(values, target)) {
        values[target] = clone(field.value);
      }
    }
    metadata.set(values, {manual});
    return applyAutomaticDefaults(manifest, values);
  }

  function setValue(manifest, values, key, field, value) {
    const target = storageKey(key, field);
    const state = metadata.get(values) || {manual: new Set()};
    state.manual.add(target);
    metadata.set(values, state);
    values[target] = value;
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
    const choices = field?.disabled_values_by_engine?.[engine] || [];
    return new Set(choices.map(String));
  }

  window.FTSettingRules = Object.freeze({
    initialValues, setValue, patchValues, valueFor, storageKey,
    conditionsMatch, isVisible, isEditable, disabledValues,
    applyAutomaticDefaults,
  });
})();
