(() => {
  const metricCatalog = [
    {key: "mean_ic", aliases: ["mean_ic", "mean"], label: "IC Mean", direction: 1},
    {key: "std_ic", aliases: ["std_ic", "std"], label: "IC Std", direction: -1},
    {key: "icir_signal", aliases: ["icir_signal", "IR", "ir"], label: "IR", direction: 1},
    {key: "t_stat_hac", aliases: ["t_stat_hac", "t_stat", "t_stat_iid"], label: "t-stat", direction: 1},
    {key: "max_ic", aliases: ["max_ic", "max"], label: "IC Max", direction: 1},
    {key: "min_ic", aliases: ["min_ic", "min"], label: "IC Min", direction: -1},
    {key: "ic_series_acf1", aliases: ["ic_series_acf1", "ac1"], label: "IC ACF(1)", direction: 1},
    {
      key: "ic_series_acf_half_life_signals",
      aliases: ["ic_series_acf_half_life_signals", "half_life"],
      label: "Persistence Half-Life", direction: -1,
    },
  ];

  function finite(value) {
    if (value == null || value === "") return null;
    const result = Number(value);
    return Number.isFinite(result) ? result : null;
  }

  function first(row, keys) {
    for (const key of keys) {
      const value = finite(row?.[key]);
      if (value != null) return value;
    }
    return null;
  }

  function rows(payload) {
    return Array.isArray(payload?.rows) ? payload.rows : [];
  }

  function factorIdentity(item, fallback = "") {
    const factorRef = String(item?.factor_ref || item?.factorRef || "");
    const factorAlias = String(
      item?.factor_alias || item?.factorAlias || item?.label
        || item?.factor_name || fallback || factorRef,
    );
    return {
      key: factorRef || factorAlias,
      factorRef,
      factorAlias: factorAlias || "Factor",
    };
  }

  function ensureFactor(result, identity) {
    const aliasMatch = [...result.entries()].find(([, item]) => (
      item.factorAlias === identity.factorAlias
    ));
    const key = result.has(identity.key) ? identity.key : (aliasMatch?.[0] || identity.key);
    if (!result.has(key)) {
      result.set(key, {
        ...identity, key, series: [], statistics: [], resample: [],
        autocorrelation: [], rolling: [], periods: [], halfLife: [], portfolio: [],
      });
    } else if (!result.get(key).factorRef && identity.factorRef) {
      result.get(key).factorRef = identity.factorRef;
    }
    return key;
  }

  function normalizedSeries(payload) {
    return (Array.isArray(payload?.series) ? payload.series : []).map(item => {
      const identity = factorIdentity(item);
      return {
        ...identity,
        method: methodOf(item),
        horizon: String(item.horizon || item.forward_return_horizon || ""),
        delay: Number(item.entry_delay_bars || 0),
        dates: Array.isArray(item.dates) ? item.dates
          : Array.isArray(item.timestamps) ? item.timestamps : [],
        values: Array.isArray(item.values) ? item.values.map(finite) : [],
      };
    }).filter(item => item.dates.length && item.values.some(value => value != null));
  }

  function methodOf(item) {
    const value = String(item?.ic_method || item?.correlation || item?.method || "rank")
      .trim().toLowerCase();
    return value === "spearman" ? "rank" : (value || "rank");
  }

  function factorMap(payloads) {
    const result = new Map();
    const series = normalizedSeries(payloads.ic_series_data);
    const statistics = rows(payloads.ic_statistics_data);
    const resample = rows(payloads.ic_resample_stability_data);
    const autocorrelation = rows(payloads.ic_autocorrelation_data);
    const rolling = rows(payloads.ic_rolling_stability_data);
    const periods = rows(payloads.ic_period_diagnostics_data);
    const halfLife = rows(payloads.ic_holding_half_life_data);
    const portfolio = rows(payloads.ic_quantile_portfolio_statistics_data);
    for (const item of [
      ...series, ...statistics, ...resample, ...autocorrelation,
      ...rolling, ...periods, ...halfLife, ...portfolio,
    ]) {
      const identity = factorIdentity(item);
      if (!identity.key) continue;
      ensureFactor(result, identity);
    }
    for (const item of series) {
      const key = ensureFactor(result, factorIdentity(item));
      result.get(key)?.series.push(item);
    }
    for (const item of statistics) {
      const identity = factorIdentity(item);
      result.get(ensureFactor(result, identity))?.statistics.push(item);
    }
    for (const item of resample) {
      const identity = factorIdentity(item);
      result.get(ensureFactor(result, identity))?.resample.push(item);
    }
    for (const item of autocorrelation) {
      const identity = factorIdentity(item);
      result.get(ensureFactor(result, identity))?.autocorrelation.push(item);
    }
    for (const item of rolling) {
      const identity = factorIdentity(item);
      result.get(ensureFactor(result, identity))?.rolling.push(item);
    }
    for (const item of periods) {
      const identity = factorIdentity(item);
      result.get(ensureFactor(result, identity))?.periods.push(item);
    }
    for (const item of halfLife) {
      const identity = factorIdentity(item);
      result.get(ensureFactor(result, identity))?.halfLife.push(item);
    }
    for (const item of portfolio) {
      const identity = factorIdentity(item);
      result.get(ensureFactor(result, identity))?.portfolio.push(item);
    }
    return [...result.values()];
  }

  function summaryMatchesFactor(row, factor) {
    const factorRef = String(factor?.factorRef || "");
    const factorAlias = String(factor?.factorAlias || "");
    if (row?.factor_ref && String(row.factor_ref) === factorRef) return true;
    if (row?.factor_alias && String(row.factor_alias) === factorAlias) return true;
    const reference = String(row?.factor || "");
    return Boolean(
      (factorRef && reference.includes(encodeURIComponent(factorRef)))
      || (factorAlias && reference.startsWith(`[${factorAlias}](`)),
    );
  }

  function primaryDescriptor(factor, summaryRows, method = "") {
    const summary = (summaryRows || []).find(row => (
      summaryMatchesFactor(row, factor)
        && (!method || !row.ic_method || methodOf(row) === method)
    ));
    if (!summary) return null;
    return {
      horizon: String(summary.primary_forward_return_horizon || ""),
      delay: Number(summary.entry_delay_bars || 0),
    };
  }

  function horizonSeconds(value) {
    const match = String(value || "").toUpperCase().match(/^(MIN|HOUR|DAY|WEEK|MONTH)(\d+)$/);
    if (!match) return Number.MAX_SAFE_INTEGER;
    const scale = {MIN: 60, HOUR: 3600, DAY: 86400, WEEK: 604800, MONTH: 2592000};
    return scale[match[1]] * Number(match[2]);
  }

  function descriptorMatches(item, descriptor) {
    if (!descriptor) return true;
    return String(item?.forward_return_horizon || item?.horizon || "") === descriptor.horizon
      && Number(item?.entry_delay_bars || item?.delay || 0) === Number(descriptor.delay || 0);
  }

  function methodMatches(item, method) {
    return !method || methodOf(item) === method;
  }

  function descriptorsFor(factors, method = "") {
    const values = new Map();
    (factors || []).forEach(factor => {
      [...(factor.series || []), ...(factor.statistics || []), ...(factor.portfolio || [])].forEach(item => {
        if (!methodMatches(item, method)) return;
        const descriptor = {
          horizon: String(item.forward_return_horizon || item.horizon || ""),
          delay: Number(item.entry_delay_bars || item.delay || 0),
        };
        if (!descriptor.horizon) return;
        values.set(`${descriptor.horizon}\u0000${descriptor.delay}`, descriptor);
      });
    });
    return [...values.values()].sort((left, right) => (
      horizonSeconds(left.horizon) - horizonSeconds(right.horizon)
        || left.delay - right.delay
    ));
  }

  function methodsFor(factors) {
    const methods = new Set();
    (factors || []).forEach(factor => {
      [...(factor.series || []), ...(factor.statistics || []), ...(factor.portfolio || [])]
        .forEach(item => methods.add(methodOf(item)));
    });
    const order = {rank: 0, pearson: 1};
    return [...methods].sort((left, right) => (
      (order[left] ?? 100) - (order[right] ?? 100) || left.localeCompare(right)
    ));
  }

  function primaryStatistic(factor, summaryRows = [], descriptor = null, method = "") {
    if (!factor?.statistics?.length) return null;
    const declared = descriptor || primaryDescriptor(factor, summaryRows, method);
    const primary = declared || [...factor.series].filter(item => methodMatches(item, method))
      .sort((left, right) => (
      horizonSeconds(left.horizon) - horizonSeconds(right.horizon)
        || left.delay - right.delay
    ))[0];
    return factor.statistics.find(item => (
      methodMatches(item, method) && descriptorMatches(item, primary)
    )) || (!descriptor
      ? factor.statistics.find(item => methodMatches(item, method)) || factor.statistics[0]
      : null);
  }

  function statisticMatrix(factors, summaryRows = [], descriptor = null, method = "") {
    const metrics = metricCatalog.map(metric => {
      const values = factors.map(factor => first(
        primaryStatistic(factor, summaryRows, descriptor, method), metric.aliases,
      ));
      let bestIndex = null;
      values.forEach((value, index) => {
        if (value == null) return;
        const best = bestIndex == null ? null : values[bestIndex];
        if (best == null || (metric.direction > 0 ? value > best : value < best)) bestIndex = index;
      });
      return {...metric, values, bestIndex};
    }).filter(metric => metric.values.some(value => value != null));
    return {factors, metrics};
  }

  function decay(factor, method = "") {
    return (factor?.statistics || []).filter(item => methodMatches(item, method)).map(item => ({
      horizon: String(item.forward_return_horizon || item.horizon || ""),
      delay: Number(item.entry_delay_bars || 0),
      mean: first(item, ["mean_ic", "mean"]),
      ir: first(item, ["icir_signal", "IR", "ir"]),
    })).filter(item => item.mean != null || item.ir != null)
      .sort((left, right) => horizonSeconds(left.horizon) - horizonSeconds(right.horizon)
        || left.delay - right.delay);
  }

  function seriesFor(factor, descriptor, method = "") {
    return (factor?.series || []).find(item => (
      methodMatches(item, method) && descriptorMatches(item, descriptor)
    )) || null;
  }

  function portfolioRowsFor(factor, descriptor = null, method = "") {
    return (factor?.portfolio || []).filter(item => (
      methodMatches(item, method) && descriptorMatches(item, descriptor)
    ));
  }

  function primarySeries(factor, summaryRows = [], descriptor = null, method = "") {
    const declared = descriptor || primaryDescriptor(factor, summaryRows, method);
    if (declared) {
      const match = seriesFor(factor, declared, method);
      if (match) return match;
    }
    return [...(factor?.series || [])].filter(item => methodMatches(item, method))
      .sort((left, right) => (
      horizonSeconds(left.horizon) - horizonSeconds(right.horizon)
        || left.delay - right.delay
    ))[0] || null;
  }

  function autocorrelation(
    factor, maximumLag = 20, summaryRows = [], descriptor = null, method = "",
  ) {
    const persisted = (factor?.autocorrelation || []).filter(item => (
      methodMatches(item, method) && item.lag != null
    ));
    if (persisted.length) {
      return persisted
        .slice(0, maximumLag)
        .map(item => ({lag: Number(item.lag), value: finite(
          item.autocorrelation ?? item.value,
        )}))
        .filter(item => item.value != null);
    }
    const values = (primarySeries(factor, summaryRows, descriptor, method)?.values || [])
      .filter(value => value != null);
    if (values.length < 3) return [];
    const mean = values.reduce((sum, value) => sum + value, 0) / values.length;
    const denominator = values.reduce((sum, value) => sum + ((value - mean) ** 2), 0);
    if (!denominator) return [];
    const limit = Math.min(maximumLag, values.length - 2);
    return Array.from({length: limit}, (_, index) => {
      const lag = index + 1;
      let numerator = 0;
      for (let cursor = lag; cursor < values.length; cursor += 1) {
        numerator += (values[cursor] - mean) * (values[cursor - lag] - mean);
      }
      return {lag, value: numerator / denominator};
    });
  }

  function histogram(factor, summaryRows = [], descriptor = null, method = "") {
    const values = (primarySeries(factor, summaryRows, descriptor, method)?.values || [])
      .filter(value => value != null);
    if (!values.length) return [];
    const minimum = Math.min(...values); const maximum = Math.max(...values);
    if (minimum === maximum) return [{from: minimum, to: maximum, count: values.length}];
    const count = Math.max(5, Math.min(30, Math.ceil(Math.sqrt(values.length))));
    const width = (maximum - minimum) / count;
    const bins = Array.from({length: count}, (_, index) => ({
      from: minimum + (index * width), to: minimum + ((index + 1) * width), count: 0,
    }));
    values.forEach(value => {
      const index = Math.min(count - 1, Math.floor((value - minimum) / width));
      bins[index].count += 1;
    });
    return bins;
  }

  function build(payloads) {
    const factors = factorMap(payloads || {});
    const summaryRows = rows(payloads.ic_statistics_summary_data);
    const methods = methodsFor(factors);
    const method = methods[0] || "rank";
    return {
      factors,
      methods,
      descriptors: descriptorsFor(factors, method),
      matrix: statisticMatrix(factors, summaryRows, null, method),
      summaryRows,
      rollingRows: rows(payloads.ic_rolling_stability_data),
      periodRows: rows(payloads.ic_period_diagnostics_data),
      resampleRows: rows(payloads.ic_resample_stability_data),
      halfLifeRows: rows(payloads.ic_holding_half_life_data),
      portfolioRows: rows(payloads.ic_quantile_portfolio_statistics_data),
    };
  }

  window.FTICResultModel = Object.freeze({
    autocorrelation, build, decay, descriptorMatches, descriptorsFor, finite,
    histogram, horizonSeconds, methodMatches, methodOf, methodsFor, metricCatalog,
    portfolioRowsFor,
    primaryDescriptor, primarySeries, seriesFor, statisticMatrix,
  });
})();
