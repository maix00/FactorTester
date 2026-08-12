(() => {
  function clone(value) {
    return value === undefined ? undefined : structuredClone(value);
  }

  function authoringSettings(_manifest, values) {
    return clone(values || {});
  }

  function executionSettings(manifest, values) {
    const result = {};
    const copied = new Set();
    for (const [key, field] of Object.entries(manifest?.defaults || {})) {
      const serialization = field?.serialization || {};
      if (field?.execution_policy === "authoring_only") continue;
      const target = serialization.storage_key || key;
      if (copied.has(target)
        || !Object.prototype.hasOwnProperty.call(values || {}, target)) continue;
      result[target] = clone(values[target]);
      copied.add(target);
    }
    return result;
  }

  function factorAlias(factor) {
    return String(factor?.factor_alias || factor?.alias || factor?.name || "").trim();
  }

  function factorReference(factor) {
    return String(factor?.factor_ref || factor?.target_ref || "").trim();
  }

  function factorSubjects(factors) {
    return (Array.isArray(factors) ? factors : []).map(factor => {
      const alias = factorAlias(factor);
      const factorRef = factorReference(factor);
      if (!alias) throw new Error("因子缺少可执行别名");
      if (factor?.source_kind === "transient" && factor?.transient_factor_id) {
        return {alias};
      }
      if (!factorRef) throw new Error(`因子 ${alias} 缺少稳定引用`);
      return {
        alias,
        factor_ref: factorRef,
      };
    });
  }

  window.FTTestConfigurationCompiler = Object.freeze({
    authoringSettings,
    executionSettings,
    factorSubjects,
  });
})();
