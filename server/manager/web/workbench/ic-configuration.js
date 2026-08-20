(() => {
  function clone(value) {
    return value === undefined ? undefined : structuredClone(value);
  }

  function tokens(value) {
    const source = Array.isArray(value)
      ? value : String(value || "").split(/[\s,，;；]+/);
    return source.map(item => String(item).trim()).filter(Boolean);
  }

  function unique(values) {
    return values.filter((value, index) => values.indexOf(value) === index);
  }

  function normalizeHorizon(value) {
    const raw = value && typeof value === "object" ? value : {};
    const sampling = String(raw.sampling || "").toLowerCase();
    if (sampling === "scale_aware" || sampling === "auto") {
      return {sampling: "scale_aware"};
    }
    const bases = unique(tokens(raw.bases || ["signal"]));
    const multipliers = unique(tokens(raw.multipliers || [1])
      .map(Number).filter(item => Number.isInteger(item) && item > 0));
    return {
      sampling: "explicit",
      bases: bases.length ? bases : ["signal"],
      multipliers: multipliers.length ? multipliers : [1],
    };
  }

  function normalizeDelays(value) {
    const delays = unique(tokens(value).map(Number)
      .filter(item => Number.isInteger(item) && item >= 0));
    return delays.length ? delays : [0];
  }

  function normalizeDecayLags(value) {
    const lags = unique(tokens(value).map(Number)
      .filter(item => Number.isInteger(item) && item > 0));
    return lags.length ? lags : [5];
  }

  function correlationMethods(value) {
    if (value === "both") return ["rank", "pearson"];
    return [value === "pearson" ? "pearson" : "rank"];
  }

  function normalizeSettings(manifest, values) {
    const result = clone(values || {});
    result.forward_return_horizons = normalizeHorizon(
      result.forward_return_horizons,
    );
    result.ic_lags = normalizeDelays(result.ic_lags);
    result.ic_decay_lags = normalizeDecayLags(result.ic_decay_lags);
    result.ic_correlation = correlationMethods(result.ic_correlation).length === 2
      ? "both" : correlationMethods(result.ic_correlation)[0];
    const compiler = typeof FTTestConfigurationCompiler !== "undefined"
      ? FTTestConfigurationCompiler : window.FTTestConfigurationCompiler;
    return compiler?.sanitizeExecutionPayload
      ? compiler.sanitizeExecutionPayload(manifest || {defaults: {}}, result, values)
      : result;
  }

  function normalizeRegisteredSettings(manifest, values) {
    for (const [key, field] of Object.entries(manifest?.defaults || {})) {
      const target = field?.serialization?.storage_key || key;
      if (!Object.prototype.hasOwnProperty.call(values || {}, target)) continue;
      const editor = field?.value_descriptor?.editor;
      if (editor === "ic_horizon_grid") {
        values[target] = normalizeHorizon(values[target]);
      } else if (editor === "ic_delay_grid") {
        values[target] = normalizeDelays(values[target]);
      } else if (editor === "ic_decay_grid") {
        values[target] = normalizeDecayLags(values[target]);
      }
    }
    return values;
  }

  function productScope(selection) {
    const value = clone(selection || {});
    const id = String(
      value.product_path_selection_id || value.selection_id || value.id || "",
    ).trim();
    if (!id) throw new Error("产品范围缺少稳定标识");
    value.product_path_selection_id = id;
    value.selected_paths = unique((value.selected_paths || value.paths || [])
      .map(item => String(item).trim()).filter(Boolean));
    delete value.paths;
    return value;
  }

  function compileAnalysis(options) {
    const {
      prior, manifest, values, factors, productSelection,
    } = options;
    const settings = normalizeSettings(
      manifest,
      FTTestConfigurationCompiler.executionSettings(manifest, values),
    );
    const selection = productScope(productSelection);
    const result = {
      ...clone(prior || {}),
      ...settings,
      product_path_selection_id: selection.product_path_selection_id,
      product_path_selection: selection,
      paths: [...selection.selected_paths],
      factors: FTTestConfigurationCompiler.factorSubjects(factors),
      settings: clone(settings),
      local_settings: clone(settings),
    };
    delete result.product_path_selections;
    delete result.factor_family_alias;
    return result;
  }

  function evaluationPlan(options) {
    const values = normalizeSettings(
      options.manifest || {defaults: {}}, options.values || {},
    );
    const horizon = values.forward_return_horizons;
    const factors = Number(options.factorCount || 0);
    const products = Number(options.productCount || 0);
    const methods = correlationMethods(values.ic_correlation);
    const horizonUpperBound = horizon.sampling === "explicit"
      ? horizon.bases.length * horizon.multipliers.length : null;
    return {
      factors,
      horizons: horizonUpperBound,
      horizonMode: horizon.sampling,
      delays: values.ic_lags.length,
      methods: methods.length,
      jobs: products,
      slicesPerJob: horizonUpperBound == null
        ? null : factors * horizonUpperBound * values.ic_lags.length * methods.length,
      exact: horizon.sampling === "explicit" && !horizon.bases.includes("signal"),
    };
  }

  window.FTICConfiguration = Object.freeze({
    compileAnalysis,
    correlationMethods,
    evaluationPlan,
    normalizeDecayLags,
    normalizeDelays,
    normalizeHorizon,
    normalizeRegisteredSettings,
    normalizeSettings,
    productScope,
    tokens,
  });
})();
