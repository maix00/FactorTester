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
    delete result.local_settings;
    delete result.settings;
    // The analysis root is an authoring merge of prior state and current
    // values. Registered outer fields belong only in execution.settings, while
    // GROUP_ONLY fields belong only on strategy groups below. Strip the
    // root copy before this object becomes the frozen RunSpec.
    sanitizeObject(manifest, result, values || {}, {
      localScope: true, stripRegistered: stripRootRegistered,
    });
    const executionSettings = result.execution?.settings;
    if (executionSettings && typeof executionSettings === "object") {
      sanitizeObject(manifest, executionSettings, values || {}, {localScope: true});
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

  const DERIVED_SETTINGS_KEYS = Object.freeze(["execution", "local_settings", "settings"]);

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
    analysis.execution = {
      ...(analysis.execution || {}),
      settings: executionSettings(manifest, settings),
    };
    delete analysis.local_settings;
    delete analysis.settings;
    return result;
  }

  function authoringMountedTabs(manifest, settings, explicit) {
    const tabs = manifest?.tab_lists?.["local-settings"] || [];
    const available = new Set(tabs.map(tab => String(tab?.key || "")).filter(Boolean));
    // Assistance documents can inherit a previously polluted mounted_tabs
    // list. Rebuild the canonical list from registered defaults and actual
    // non-default field values instead of treating that serialized list as
    // semantic configuration.
    const mounted = new Set((manifest?.default_mounted_tabs?.["local-settings"] || [])
      .filter(key => available.has(key)));
    for (const key of Array.isArray(explicit) ? explicit : []) {
      if (available.has(key)) mounted.add(key);
    }
    for (const [key, field] of Object.entries(manifest?.defaults || {})) {
      const tabKey = String(field?.tab_key || "");
      if (!available.has(tabKey)
          || !Object.prototype.hasOwnProperty.call(settings || {}, key)) continue;
      const registeredDefault = Object.prototype.hasOwnProperty.call(field || {}, "default")
        ? field.default : field?.value;
      if (!sameRegisteredValue(settings[key], registeredDefault)) {
        mounted.add(tabKey);
      }
    }
    return tabs.map(tab => tab.key).filter(key => mounted.has(key));
  }

  function authoringItemMountedTabs(manifest, item, explicit) {
    const editor = manifest?.strategy_editor || {};
    const defaults = Array.isArray(editor.inner_default_tabs)
      ? editor.inner_default_tabs : [];
    const manual = Array.isArray(editor.inner_manual_tabs)
      ? editor.inner_manual_tabs : [];
    const ordered = [...defaults, ...manual];
    const available = new Set(ordered.map(tab => String(tab?.key || "")).filter(Boolean));
    const mounted = new Set(defaults.map(tab => tab.key).filter(Boolean));
    for (const key of Array.isArray(explicit) ? explicit : []) {
      if (available.has(key)) mounted.add(key);
    }
    for (const [key, field] of Object.entries(manifest?.defaults || {})) {
      const tabKey = String(field?.tab_key || "");
      if (!available.has(tabKey)
          || !Object.prototype.hasOwnProperty.call(item || {}, key)) continue;
      const registeredDefault = Object.prototype.hasOwnProperty.call(field || {}, "default")
        ? field.default : field?.value;
      if (!sameRegisteredValue(item[key], registeredDefault)) mounted.add(tabKey);
    }
    for (const tab of manual) {
      const field = String(tab?.item_field || "");
      if (!field || !Object.prototype.hasOwnProperty.call(item || {}, field)) continue;
      if (!sameRegisteredValue(item[field], tab.item_default)) mounted.add(tab.key);
    }
    return ordered.map(tab => tab.key).filter(key => mounted.has(key));
  }

  function sameRegisteredValue(left, right) {
    const canonical = value => {
      if (Array.isArray(value)) return value.map(canonical);
      if (!value || typeof value !== "object") return value;
      return Object.fromEntries(Object.keys(value).sort().map(key => [
        key, canonical(value[key]),
      ]));
    };
    return JSON.stringify(canonical(left)) === JSON.stringify(canonical(right));
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
    const provenanceKeys = [
      "temporary", "source_kind", "source_origin",
      "transient_factor_id", "source_code",
    ];
    const canonical = value => {
      if (Array.isArray(value)) return value.map(canonical);
      if (!value || typeof value !== "object") return value;
      return Object.fromEntries(Object.keys(value).sort().map(key => [
        key, canonical(value[key]),
      ]));
    };
    const visit = factor => {
      for (const dependency of factor?.factor_dependencies || []) visit(dependency);
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
      // Keep the execution evidence needed by configuration-local factors.
      // The dependency links themselves are flattened into sibling records;
      // identity.params still points at each sibling's immutable ref.
      for (const key of provenanceKeys) {
        if (factor[key] !== undefined) record[key] = clone(factor[key]);
      }
      const encoded = JSON.stringify(canonical(record));
      if (byRef.has(factorRef)) {
        if (byRef.get(factorRef) !== encoded) {
          throw new Error(`因子引用对应了不同的冻结对象: ${factorRef}`);
        }
        return;
      }
      byRef.set(factorRef, encoded);
      result.push(record);
    };
    for (const factor of Array.isArray(factors) ? factors : []) visit(factor);
    return result;
  }

  window.FTTestConfigurationCompiler = Object.freeze({
    authoringConfiguration, authoringItemMountedTabs, authoringMountedTabs, authoringSettings,
    derivedSettingsKeys: () => [...DERIVED_SETTINGS_KEYS],
    executableConfiguration,
    executionSettings,
    factorSubjects,
    sanitizeExecutionPayload,
  });
})();
