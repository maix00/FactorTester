(() => {
  const authoringOnlyKinds = new Set([
    "factor_owner_selection",
    "factor_revision_selection",
    "factor_family_selection",
    "factor_parameter_values",
    "factor_candidate_list",
    "factor_selection",
    "factor_selection_list",
    "product_path_candidate_list",
    "product_path_selection",
    "product_path_selection_list",
    "category_candidate_list",
    "setting_template",
  ]);

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
      if (authoringOnlyKinds.has(serialization.kind || "")) continue;
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
      if (!factorRef) throw new Error(`因子 ${alias} 缺少稳定引用`);
      return {
        alias,
        factor_ref: factorRef,
        return_freq: String(factor.return_freq || "").trim(),
      };
    });
  }

  window.FTTestConfigurationCompiler = Object.freeze({
    authoringSettings,
    executionSettings,
    factorSubjects,
  });
})();
