(() => {
  function clone(value) {
    return value === undefined ? undefined : structuredClone(value);
  }

  function initialize(state) {
    if (!Array.isArray(state.transientFactorSources)) state.transientFactorSources = [];
    if (!Array.isArray(state.transientFactorFamilies)) state.transientFactorFamilies = [];
    if (!Array.isArray(state.transientStrategySources)) state.transientStrategySources = [];
    if (!Array.isArray(state.strategySpecs)) state.strategySpecs = [];
    if (!Array.isArray(state.strategyInspections)) state.strategyInspections = [];
    if (!Array.isArray(state.temporaryStrategies)) state.temporaryStrategies = [];
    if (!Array.isArray(state.strategyBindings)) state.strategyBindings = [];
    if (!Array.isArray(state.runInputDependencies)) state.runInputDependencies = [];
    if (!state.customStrategyOverrides || typeof state.customStrategyOverrides !== "object") {
      state.customStrategyOverrides = {};
    }
    if (!Array.isArray(state.customStrategyMountedTabs)) state.customStrategyMountedTabs = [];
    if (!Array.isArray(state.customStrategyProductMask)) state.customStrategyProductMask = [];
    state.runInputStatus = state.runInputStatus || {busy: false, error: ""};
    return state;
  }

  function replaceBy(items, predicate, value) {
    const index = items.findIndex(predicate);
    if (index >= 0) items[index] = value;
    else items.push(value);
  }

  function putFactor(state, source, metadata) {
    initialize(state);
    const factorID = String(source?.factor_id || metadata?.factor_name || "").trim();
    if (!factorID) throw new Error("临时因子缺少类名");
    const prior = state.transientFactorSources.find(item => item.factor_id === factorID);
    const sourceCode = String(source?.source_code || "");
    const origin = String(source?.source_origin || "upload");
    if (prior && prior.source_code !== sourceCode && (
      prior.source_origin === "factor_set" || origin === "factor_set"
    )) throw new Error(`同名因子源码冲突: ${factorID}`);
    const normalizedSource = {
      factor_id: factorID,
      path: String(source?.path || "").replaceAll("\\", "/").trim(),
      source_code: sourceCode,
      source_origin: prior?.source_origin === "upload" || origin === "upload"
        ? "upload" : "factor_set",
      factor_set_refs: [...new Set([
        ...(prior?.factor_set_refs || []), ...(source?.factor_set_refs || []),
      ])],
    };
    if (!normalizedSource.path) throw new Error("临时因子缺少源码路径");
    replaceBy(
      state.transientFactorSources,
      item => item.factor_id === factorID,
      normalizedSource,
    );
    const family = {
      key: `transient:${factorID}`,
      sourceKind: "transient",
      sourceID: factorID,
      family: factorID,
      title: factorID,
      description: metadata?.desc || metadata?.description || "",
      params: clone(metadata?.params || []),
      math_expr: String(metadata?.math_expr || ""),
      familyMetadata: {
        family: factorID,
        factor_family_alias: factorID,
        params: clone(metadata?.params || []),
        math_expr: String(metadata?.math_expr || ""),
        desc: metadata?.desc || metadata?.description || "",
      },
    };
    replaceBy(
      state.transientFactorFamilies,
      item => item.sourceID === factorID,
      family,
    );
    return family;
  }

  function detachFactorSet(state, targetRef) {
    initialize(state);
    const detached = new Set();
    state.transientFactorSources = state.transientFactorSources.flatMap(source => {
      const refs = (source.factor_set_refs || []).filter(ref => ref !== targetRef);
      if (refs.length || source.source_origin !== "factor_set") {
        return [{...source, factor_set_refs: refs}];
      }
      detached.add(source.factor_id);
      return [];
    });
    for (const factorID of detached) {
      state.transientFactorFamilies = state.transientFactorFamilies.filter(
        item => item.sourceID !== factorID,
      );
    }
  }

  function removeFactor(state, factorID) {
    initialize(state);
    state.transientFactorSources = state.transientFactorSources.filter(
      item => item.factor_id !== factorID,
    );
    state.transientFactorFamilies = state.transientFactorFamilies.filter(
      item => item.sourceID !== factorID,
    );
    const belongs = item => item?.transient_factor_id === factorID;
    if (state.values) {
      state.values.factor_candidates = (state.values.factor_candidates || []).filter(
        item => !belongs(item),
      );
      state.values.factor_selections = (state.values.factor_selections || []).filter(
        item => !belongs(item),
      );
    }
  }

  function putStrategy(state, source, inspection) {
    initialize(state);
    const path = String(source?.path || "").replaceAll("\\", "/").trim();
    if (!path) throw new Error("临时策略源码缺少路径");
    replaceBy(
      state.transientStrategySources,
      item => item.path === path,
      {path, source_code: String(source?.source_code || "")},
    );
    const spec = clone(inspection?.strategy_spec || {});
    replaceBy(
      state.strategySpecs,
      item => item.source === spec.source || item.strategy_id === spec.strategy_id,
      spec,
    );
    replaceBy(
      state.strategyInspections,
      item => item.path === path,
      {
        path,
        entrypoint: String(inspection?.entrypoint || spec.entrypoint || ""),
        callbacks: [...new Set((inspection?.callbacks || []).map(String))].sort(),
        requirements: clone(inspection?.requirements || spec.requirements || {}),
      },
    );
    return spec;
  }

  function putInlineStrategy(state, strategy, binding) {
    initialize(state);
    const normalized = clone(strategy || {});
    const bindingValue = clone(binding || {});
    if (!normalized.temp_ref || !bindingValue.binding_id) {
      throw new Error("临时策略或策略绑定缺少标识");
    }
    replaceBy(state.temporaryStrategies, item => item.temp_ref === normalized.temp_ref, normalized);
    replaceBy(state.strategyBindings, item => item.binding_id === bindingValue.binding_id, bindingValue);
    return normalized;
  }

  function putStrategyBinding(state, binding) {
    initialize(state);
    const value = clone(binding || {});
    if (!value.binding_id || !value.target_strategy_id || !value.source) {
      throw new Error("策略绑定字段不完整");
    }
    replaceBy(state.strategyBindings, item => item.target_strategy_id === value.target_strategy_id,
      value);
    return value;
  }

  function removeStrategyBinding(state, bindingID) {
    initialize(state);
    const selected = state.strategyBindings.find(item => item.binding_id === bindingID);
    state.strategyBindings = state.strategyBindings.filter(item => item.binding_id !== bindingID);
    if (selected?.source?.kind === "inline") {
      const ref = selected.source.temp_ref;
      if (!state.strategyBindings.some(item => item.source?.temp_ref === ref)) {
        state.temporaryStrategies = state.temporaryStrategies.filter(item => item.temp_ref !== ref);
      }
    }
    return selected || null;
  }

  function removeStrategy(state, path) {
    initialize(state);
    state.transientStrategySources = state.transientStrategySources.filter(
      item => item.path !== path,
    );
    const source = `profile:${path}`;
    state.strategySpecs = state.strategySpecs.filter(item => item.source !== source);
    state.strategyInspections = state.strategyInspections.filter(
      item => item.path !== path,
    );
  }

  function putDependency(state, dependency) {
    initialize(state);
    const path = String(dependency?.path || "").replaceAll("\\", "/").trim();
    if (!path) throw new Error("任务输入依赖缺少路径");
    replaceBy(
      state.runInputDependencies,
      item => item.path === path,
      {...clone(dependency), path},
    );
  }

  function removeDependency(state, path) {
    initialize(state);
    state.runInputDependencies = state.runInputDependencies.filter(
      item => item.path !== path,
    );
  }

  function factorSource(state, factorID) {
    initialize(state);
    return state.transientFactorSources.find(item => item.factor_id === factorID) || null;
  }

  function strategySource(state, path) {
    initialize(state);
    return state.transientStrategySources.find(item => item.path === path) || null;
  }

  function strategyInspection(state, path) {
    initialize(state);
    return state.strategyInspections.find(item => item.path === path) || null;
  }

  function requestBody(state) {
    initialize(state);
    const result = {
      transient_factor_sources: clone(state.transientFactorSources),
      transient_strategy_sources: clone(state.transientStrategySources),
      strategy_specs: clone(state.strategySpecs),
      strategies: clone(state.temporaryStrategies),
      strategy_bindings: clone(state.strategyBindings),
      run_input_dependencies: clone(state.runInputDependencies),
    };
    if (Object.keys(state.customStrategyOverrides).length) {
      result.custom_strategy_overrides = clone(state.customStrategyOverrides);
    }
    if (state.customStrategyMountedTabs.length) {
      result.custom_strategy_mounted_tabs = [...state.customStrategyMountedTabs];
    }
    if (state.customStrategyProductMask.length) {
      result.custom_strategy_product_mask = [...state.customStrategyProductMask];
    }
    return result;
  }

  function counts(state) {
    initialize(state);
    return {
      factors: state.transientFactorSources.length,
      strategies: state.transientStrategySources.length,
      dependencies: state.runInputDependencies.length,
    };
  }

  window.FTTestInputState = Object.freeze({
    counts,
    detachFactorSet,
    factorSource,
    initialize,
    putFactor,
    putDependency,
    putStrategy,
    removeDependency,
    removeFactor,
    removeStrategy,
    requestBody,
    strategyInspection,
    strategySource,
    putInlineStrategy,
    putStrategyBinding,
    removeStrategyBinding,
  });
})();
