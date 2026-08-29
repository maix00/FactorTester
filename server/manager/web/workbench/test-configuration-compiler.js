(() => {
  function clone(value) {
    return value === undefined ? undefined : structuredClone(value);
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

  function isVisible(key, field, values) {
    if (window.FTSettingRules?.isVisible) {
      return window.FTSettingRules.isVisible(field, values);
    }
    return conditionsMatch(field?.rules?.visible_if, values);
  }

  function displayValue(key, field, values) {
    if (window.FTSettingRules?.displayValueFor) {
      return window.FTSettingRules.displayValueFor(key, field, values);
    }
    const target = storageKey(key, field);
    const editable = conditionsMatch(field?.rules?.editable_if, values);
    if (editable) return clone(values?.[target]);
    for (const [sourceKey, mapping] of Object.entries(field?.rules?.default_if || {})) {
      const source = String(values?.[sourceKey]);
      if (Object.prototype.hasOwnProperty.call(mapping || {}, source)) {
        return clone(mapping[source]);
      }
    }
    return clone(field?.value ?? values?.[target]);
  }

  function deleteField(object, key, field) {
    if (!object || typeof object !== "object") return;
    const target = storageKey(key, field);
    delete object[key];
    if (target !== key) delete object[target];
  }

  function normalizeField(object, key, field, values, {executionOnly = false} = {}) {
    if (!object || typeof object !== "object") return;
    if (executionOnly && field?.execution_policy === "authoring_only") {
      deleteField(object, key, field);
      return;
    }
    if (!isVisible(key, field, values)) {
      deleteField(object, key, field);
      return;
    }
    const target = storageKey(key, field);
    if (!Object.prototype.hasOwnProperty.call(object, target)
      && !Object.prototype.hasOwnProperty.call(object, key)) return;
    const value = displayValue(key, field, values);
    if (value === undefined) deleteField(object, key, field);
    else {
      object[target] = clone(value);
      if (target !== key) delete object[key];
    }
  }

  function groupOnly(field) {
    return String(field?.scope_policy || "").toLowerCase() === "group_only";
  }

  function sanitizeObject(
    manifest, object, values, {localScope = false, stripRegistered = false} = {},
  ) {
    for (const [key, field] of Object.entries(manifest?.defaults || {})) {
      if (stripRegistered) {
        deleteField(object, key, field);
        continue;
      }
      if (localScope && groupOnly(field)) {
        deleteField(object, key, field);
        continue;
      }
      normalizeField(object, key, field, values, {executionOnly: true});
    }
    return object;
  }

  function effectiveGroupValues(group, parents, inherited, cache = new Map(), stack = new Set()) {
    if (!group || cache.has(group.id)) return cache.get(group?.id) || {...inherited};
    if (stack.has(group.id)) return {...inherited, ...group};
    const nextStack = new Set(stack); nextStack.add(group.id);
    const parent = group.parentId ? parents.get(group.parentId) : null;
    const base = parent
      ? effectiveGroupValues(parent, parents, inherited, cache, nextStack)
      : {...inherited};
    const result = {...base, ...group};
    if (group.id) cache.set(group.id, result);
    return result;
  }

  function sanitizeExecutionPayload(
    manifest, payload, values, {stripRootRegistered = false} = {},
  ) {
    const result = clone(payload || {}) || {};
    // The analysis root is an authoring merge of prior state and current
    // values. Registered local fields belong only in local_settings, while
    // GROUP_ONLY fields belong only on strategy groups below. Strip the
    // root copy before this object becomes the frozen RunSpec.
    sanitizeObject(manifest, result, values || {}, {
      localScope: true, stripRegistered: stripRootRegistered,
    });
    for (const key of ["settings", "local_settings"]) {
      if (result[key] && typeof result[key] === "object") {
        sanitizeObject(manifest, result[key], values || {}, {localScope: true});
      }
    }
    if (Array.isArray(result.groups)) {
      const parents = new Map(result.groups.map(group => [group.id, group]));
      const cache = new Map();
      result.groups = result.groups.map(group => {
        const next = {...group};
        const effective = effectiveGroupValues(group, parents, values || {}, cache);
        sanitizeObject(manifest, next, effective);
        return next;
      });
    }
    return result;
  }

  function authoringSettings(manifest, values) {
    const result = clone(values || {}) || {};
    for (const [key, field] of Object.entries(manifest?.defaults || {})) {
      normalizeField(result, key, field, values || {});
    }
    return result;
  }

  function executionSettings(manifest, values) {
    const result = {};
    const copied = new Set();
    for (const [key, field] of Object.entries(manifest?.defaults || {})) {
      const serialization = field?.serialization || {};
      if (field?.execution_policy === "authoring_only" || groupOnly(field)) continue;
      const target = serialization.storage_key || key;
      if (copied.has(target)
        || !Object.prototype.hasOwnProperty.call(values || {}, target)
        || !isVisible(key, field, values)) continue;
      const value = displayValue(key, field, values);
      if (value === undefined) continue;
      result[target] = clone(value);
      copied.add(target);
    }
    return result;
  }

  const DERIVED_SETTINGS_KEYS = Object.freeze(["local_settings", "settings"]);

  function authoringConfiguration(configuration, kind) {
    const result = clone(configuration || {}) || {};
    const analysis = result.analyses?.[kind];
    if (analysis && typeof analysis === "object") {
      for (const key of DERIVED_SETTINGS_KEYS) delete analysis[key];
    }
    return result;
  }

  function executableConfiguration(configuration, kind, manifest) {
    const result = clone(configuration || {}) || {};
    result.analyses = result.analyses || {};
    const analysis = result.analyses[kind] || (result.analyses[kind] = {});
    result.ui = result.ui || {};
    const ui = result.ui[kind] || (result.ui[kind] = {});
    const settings = ui.settings && typeof ui.settings === "object"
      ? ui.settings : (ui.settings = {});
    analysis.local_settings = executionSettings(manifest, settings);
    delete analysis.settings;
    return result;
  }

  function authoringMountedTabs(manifest, settings, saved) {
    const tabs = manifest?.tab_lists?.["local-settings"] || [];
    const available = new Set(tabs.map(tab => String(tab?.key || "")).filter(Boolean));
    const mounted = new Set((Array.isArray(saved)
      ? saved : manifest?.default_mounted_tabs?.["local-settings"] || []
    ).filter(key => available.has(key)));
    for (const [key, field] of Object.entries(manifest?.defaults || {})) {
      const tabKey = String(field?.tab_key || "");
      if (!available.has(tabKey)
          || !Object.prototype.hasOwnProperty.call(settings || {}, key)) continue;
      if (JSON.stringify(settings[key]) !== JSON.stringify(field?.default)) {
        mounted.add(tabKey);
      }
    }
    return tabs.map(tab => tab.key).filter(key => mounted.has(key));
  }

  function factorAlias(factor) {
    return String(factor?.alias || "").trim();
  }

  function factorReference(factor) {
    return String(factor?.ref || "").trim();
  }

  function factorSubjects(factors) {
    const result = [];
    const byRef = new Map();
    for (const factor of Array.isArray(factors) ? factors : []) {
      const alias = factorAlias(factor);
      const factorRef = factorReference(factor);
      if (!alias) throw new Error("因子缺少可执行别名");
      if (!factorRef) throw new Error(`因子 ${alias} 缺少稳定引用`);
      const record = {
        schema_version: factor.schema_version,
        ref: factorRef,
        alias,
        owner_ref: factor.owner_ref,
        identity: clone(factor.identity),
      };
      const encoded = JSON.stringify(record);
      if (byRef.has(factorRef)) {
        if (byRef.get(factorRef) !== encoded) {
          throw new Error(`因子引用对应了不同的冻结对象: ${factorRef}`);
        }
        continue;
      }
      byRef.set(factorRef, encoded);
      result.push(record);
    }
    return result;
  }

  window.FTTestConfigurationCompiler = Object.freeze({
    authoringConfiguration, authoringMountedTabs, authoringSettings,
    derivedSettingsKeys: () => [...DERIVED_SETTINGS_KEYS],
    executableConfiguration,
    executionSettings,
    factorSubjects,
    sanitizeExecutionPayload,
  });
})();
