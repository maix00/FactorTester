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

  const GROUP_OWNED_SETTING_KEYS = new Set([
    "forward_return_horizons", "ic_lags", "ic_correlation", "return_price_basis",
    "ic_decay_lags", "rolling_window", "rolling_step", "summary_frequency",
    "quantiles", "quantile_count",
  ]);

  function productScope(selection, requestedRef = "") {
    const value = clone(selection || {});
    const id = String(
      requestedRef || value.product_path_selection_id || value.selection_id
      || value.group_ref || value.product_group_ref || value.id || "",
    ).trim();
    if (!id) throw new Error("产品范围缺少稳定标识");
    const persisted = id.startsWith("product-group:")
      || value.origin === "catalog" || value.source_origin === "catalog";
    if (persisted) return {product_path_selection_id: id};
    const paths = unique((value.selected_paths || value.paths || [])
      .map(item => String(item).trim()).filter(Boolean));
    if (!paths.length) throw new Error(`inline 产品范围没有自包含路径: ${id}`);
    return {
      product_path_selection_id: id,
      selected_paths: paths,
      origin: String(value.origin || "inline"),
      ...(Array.isArray(value.category_ids) && value.category_ids.length
        ? {category_ids: unique(value.category_ids.map(String).filter(Boolean))} : {}),
    };
  }

  function compileAnalysis(options) {
    const {manifest, values, configurationGroups, productCatalog = []} = options;
    if (!Array.isArray(configurationGroups) || configurationGroups.length !== 1) {
      throw new Error("Slice 1 requires exactly one configuration group");
    }
    const groups = configurationGroups.map(normalizeConfigurationGroup);
    const catalog = new Map(productCatalog.map(item => [
      String(item?.product_path_selection_id || item?.group_ref
        || item?.product_group_ref || item?.id || ""), item,
    ]));
    const selections = {};
    for (const group of groups) {
      selections[group.product_scope_ref] = productScope(
        catalog.get(group.product_scope_ref), group.product_scope_ref,
      );
    }
    const settings = normalizeSettings(
      manifest,
      FTTestConfigurationCompiler.executionSettings(manifest, values),
    );
    for (const key of GROUP_OWNED_SETTING_KEYS) delete settings[key];
    return {
      schema_version: 2,
      configuration_groups: groups,
      product_selections: selections,
      local_settings: clone(settings),
    };
  }

  function normalizeConfigurationGroup(value) {
    const group = clone(value || {});
    for (const key of ["config_group_id", "batch_id", "factor_ref", "product_scope_ref"] ) {
      if (!String(group[key] || "").trim()) {
        throw new Error(`IC configuration group requires ${key}`);
      }
    }
    if (!/^factor:(?:v1:|sha256:[0-9a-f]{64}$)/.test(String(group.factor_ref))) {
      throw new Error("IC configuration group requires a frozen factor_ref");
    }
    if (Array.isArray(group.entry_delay_bars)) {
      throw new Error("IC configuration group requires one Delay");
    }
    const delay = Number(group.entry_delay_bars);
    if (!Number.isInteger(delay) || delay < 0) {
      throw new Error("IC configuration group Delay must be a non-negative integer");
    }
    const methods = unique((group.methods || []).map(String))
      .filter(item => item === "rank" || item === "pearson");
    if (!methods.length) throw new Error("IC configuration group requires a method");
    if (Array.isArray(group.analysis_attachments) && group.analysis_attachments.length) {
      throw new Error("supplemental IC analyses are disabled in Slice 1");
    }
    return {
      config_group_id: String(group.config_group_id),
      batch_id: String(group.batch_id),
      name: String(group.name || group.config_group_id),
      factor_ref: String(group.factor_ref),
      product_scope_ref: String(group.product_scope_ref),
      entry_delay_bars: delay,
      horizon: normalizeHorizon(group.horizon),
      methods,
      return_price_basis: String(
        group.return_price_basis || "next_open_to_open_adjusted",
      ),
      editor_mounted_tabs: unique([
        "__configuration__", "factor", "product_path_selection",
        ...(group.editor_mounted_tabs || []),
      ]),
    };
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
