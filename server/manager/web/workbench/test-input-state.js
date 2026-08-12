(() => {
  function clone(value) {
    return value === undefined ? undefined : structuredClone(value);
  }

  function initialize(state) {
    if (!Array.isArray(state.transientFactorSources)) state.transientFactorSources = [];
    if (!Array.isArray(state.transientFactorFamilies)) state.transientFactorFamilies = [];
    if (!Array.isArray(state.transientStrategySources)) state.transientStrategySources = [];
    if (!Array.isArray(state.strategySpecs)) state.strategySpecs = [];
    if (!Array.isArray(state.runInputDependencies)) state.runInputDependencies = [];
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
    return spec;
  }

  function removeStrategy(state, path) {
    initialize(state);
    state.transientStrategySources = state.transientStrategySources.filter(
      item => item.path !== path,
    );
    const source = `profile:${path}`;
    state.strategySpecs = state.strategySpecs.filter(item => item.source !== source);
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

  function requestBody(state) {
    initialize(state);
    return {
      transient_factor_sources: clone(state.transientFactorSources),
      transient_strategy_sources: clone(state.transientStrategySources),
      strategy_specs: clone(state.strategySpecs),
      run_input_dependencies: clone(state.runInputDependencies),
    };
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
    strategySource,
  });
})();
