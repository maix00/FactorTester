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
    const factorRef = String(item?.factor_ref || "");
    const factorAlias = String(
      item?.factor_alias || item?.label || item?.factor_name || fallback || factorRef,
    );
    return {
      key: factorRef || factorAlias,
      factorRef,
      factorAlias: factorAlias || "Factor",
    };
  }

  function normalizedSeries(payload) {
    return (Array.isArray(payload?.series) ? payload.series : []).map(item => {
      const identity = factorIdentity(item);
      return {
        ...identity,
        horizon: String(item.horizon || item.forward_return_horizon || ""),
        delay: Number(item.entry_delay_bars || 0),
        dates: Array.isArray(item.dates) ? item.dates
          : Array.isArray(item.timestamps) ? item.timestamps : [],
        values: Array.isArray(item.values) ? item.values.map(finite) : [],
      };
    }).filter(item => item.dates.length && item.values.some(value => value != null));
  }

  function factorMap(payloads) {
    const result = new Map();
    const series = normalizedSeries(payloads.ic_series_data);
    const statistics = rows(payloads.ic_statistics_data);
    for (const item of [...series, ...statistics]) {
      const identity = factorIdentity(item);
      if (!identity.key) continue;
      if (!result.has(identity.key)) result.set(identity.key, {
        ...identity, series: [], statistics: [],
      });
    }
    for (const item of series) result.get(item.key)?.series.push(item);
    for (const item of statistics) {
      const identity = factorIdentity(item);
      result.get(identity.key)?.statistics.push(item);
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

  function primaryDescriptor(factor, summaryRows) {
    const summary = (summaryRows || []).find(row => summaryMatchesFactor(row, factor));
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

  function primaryStatistic(factor, summaryRows = []) {
    if (!factor?.statistics?.length) return null;
    const declared = primaryDescriptor(factor, summaryRows);
    const primary = declared || [...factor.series].sort((left, right) => (
      horizonSeconds(left.horizon) - horizonSeconds(right.horizon)
        || left.delay - right.delay
    ))[0];
    return factor.statistics.find(item => (
      String(item.forward_return_horizon || item.horizon || "") === primary?.horizon
        && Number(item.entry_delay_bars || 0) === Number(primary?.delay || 0)
    )) || factor.statistics[0];
  }

  function statisticMatrix(factors, summaryRows = []) {
    const metrics = metricCatalog.map(metric => {
      const values = factors.map(factor => first(
        primaryStatistic(factor, summaryRows), metric.aliases,
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

  function decay(factor) {
    return (factor?.statistics || []).map(item => ({
      horizon: String(item.forward_return_horizon || item.horizon || ""),
      delay: Number(item.entry_delay_bars || 0),
      mean: first(item, ["mean_ic", "mean"]),
      ir: first(item, ["icir_signal", "IR", "ir"]),
    })).filter(item => item.mean != null || item.ir != null)
      .sort((left, right) => horizonSeconds(left.horizon) - horizonSeconds(right.horizon)
        || left.delay - right.delay);
  }

  function primarySeries(factor, summaryRows = []) {
    const declared = primaryDescriptor(factor, summaryRows);
    if (declared) {
      const match = (factor?.series || []).find(item => (
        item.horizon === declared.horizon && item.delay === declared.delay
      ));
      if (match) return match;
    }
    return [...(factor?.series || [])].sort((left, right) => (
      horizonSeconds(left.horizon) - horizonSeconds(right.horizon)
        || left.delay - right.delay
    ))[0] || null;
  }

  function autocorrelation(factor, maximumLag = 20, summaryRows = []) {
    const values = (primarySeries(factor, summaryRows)?.values || [])
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

  function histogram(factor, summaryRows = []) {
    const values = (primarySeries(factor, summaryRows)?.values || [])
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
    return {
      factors,
      matrix: statisticMatrix(factors, summaryRows),
      summaryRows,
      rollingRows: rows(payloads.ic_rolling_stability_data),
      periodRows: rows(payloads.ic_period_diagnostics_data),
      halfLifeRows: rows(payloads.ic_holding_half_life_data),
    };
  }

  window.FTICResultModel = Object.freeze({
    autocorrelation, build, decay, finite, histogram, horizonSeconds,
    metricCatalog, primaryDescriptor, primarySeries, statisticMatrix,
  });
})();
