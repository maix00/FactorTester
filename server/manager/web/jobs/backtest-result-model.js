(() => {
  const payloadNames = Object.freeze([
    "equity_curve_data", "returns_over_time_data", "metrics_over_time_data",
    "fee_detail_data", "margin_detail_data", "ratio_detail_data",
    "result",
  ]);

  const metricSections = Object.freeze([
    {title: "收益", metrics: ["Total Return", "Annual Return", "Mean Return", "Win Rate"]},
    {title: "风险调整", metrics: ["Sharpe Ratio", "Calmar Ratio"]},
    {title: "风险", metrics: ["Volatility", "Max Drawdown", "Skewness", "Kurtosis"]},
    {title: "交易", metrics: ["Avg Turnover", "Avg Turnover Accel", "Avg Position Changes", "Up Ratio"]},
  ]);

  const metricDirections = Object.freeze({
    "Total Return": 1, "Annual Return": 1, "Mean Return": 1,
    "Win Rate": 1, "Sharpe Ratio": 1, "Calmar Ratio": 1,
    Volatility: -1, "Max Drawdown": -1, Skewness: 1, Kurtosis: -1,
    "Avg Turnover": -1, "Avg Turnover Accel": -1,
    "Avg Position Changes": -1, "Up Ratio": 1,
  });

  function finite(value) {
    if (value == null || value === "" || typeof value === "boolean") return null;
    const result = Number(value);
    return Number.isFinite(result) ? result : null;
  }

  function rows(payload) {
    return Array.isArray(payload?.rows) ? payload.rows : [];
  }

  function series(payload) {
    return (Array.isArray(payload?.series) ? payload.series : []).map(item => ({
      label: String(item?.label || item?.series || "Series"),
      currency: String(item?.currency || "CNY").toUpperCase(),
      timestamps: Array.isArray(item?.timestamps) ? item.timestamps : [],
      values: Array.isArray(item?.values) ? item.values.map(finite) : [],
      drawdown: Array.isArray(item?.drawdown) ? item.drawdown.map(finite) : [],
      maxDrawdown: Array.isArray(item?.max_drawdown)
        ? item.max_drawdown.map(finite) : [],
    })).filter(item => item.values.some(value => value != null));
  }

  function metricRows(payload) {
    return rows(payload).filter(row => row && typeof row === "object");
  }

  function groupEntries(summary) {
    return (Array.isArray(summary?.groups) ? summary.groups : []).map((item, index) => ({
      ...item,
      key: String(item?.strategy_id || item?.group_id || item?.key || item?.name || item?.metrics_key || index),
      label: String(item?.display_name || item?.name || item?.group_name || item?.strategy_id || item?.group_id || item?.key || item?.metrics_key || index),
    }));
  }

  function groupEquityEntries(summary) {
    return groupEntries(summary).filter(item => {
      const timestamps = Array.isArray(item.timestamps) ? item.timestamps : [];
      const values = Array.isArray(item.total_equity) ? item.total_equity : [];
      return timestamps.slice(0, values.length).some((value, index) => {
        const numericTimestamp = finite(value);
        const parsedTimestamp = numericTimestamp ?? Date.parse(String(value || ""));
        return Number.isFinite(parsedTimestamp) && finite(values[index]) != null;
      });
    });
  }

  function enrichedSummary(summary = {}, retainedResult = {}) {
    if (!Array.isArray(retainedResult?.groups) || !retainedResult.groups.length) {
      return summary;
    }
    const retainedGroups = new Map(retainedResult.groups.map((item, index) => [
      String(item?.strategy_id || item?.group_id || item?.key || item?.name || index), item,
    ]));
    const sourceGroups = Array.isArray(summary?.groups) && summary.groups.length
      ? summary.groups : retainedResult.groups;
    const groups = sourceGroups.map((item, index) => {
      const key = String(item?.strategy_id || item?.group_id || item?.key || item?.name || index);
      return {...(retainedGroups.get(key) || {}), ...item};
    });
    return {
      ...retainedResult,
      ...summary,
      groups,
      metrics: summary?.metrics || retainedResult?.metrics || {},
    };
  }

  function resolveGroup(summary, value) {
    const target = String(value || "");
    return groupEntries(summary).find(item => [
      item.key, item.label, item.group_id, item.metrics_key,
    ].some(candidate => String(candidate ?? "") === target)) || null;
  }

  function groupRequest(entry, summary = {}) {
    if (!entry) return null;
    const productPathSelectionID = String(
      entry.product_path_selection_id || summary.product_path_selection_id || "",
    );
    const groupIndex = Number(entry.group_index);
    if (!productPathSelectionID || !Number.isInteger(groupIndex)) return null;
    return {
      product_path_selection_id: productPathSelectionID,
      group_id: String(entry.strategy_id || entry.group_id || entry.key || ""),
      group_index: groupIndex,
    };
  }

  function initialSnapshot(summary = {}) {
    const entry = groupEntries(summary).find(item => (
      Array.isArray(item.timestamps) && item.timestamps.length
    ));
    if (!entry) return null;
    const request = groupRequest(entry, summary);
    const timestamp = Number(entry.timestamps[0]);
    return request && Number.isFinite(timestamp)
      ? {...request, timestamp_ms: timestamp} : null;
  }

  function groups(payloads, summary = {}) {
    const values = new Set();
    for (const item of series(payloads.equity_curve_data)) values.add(item.label);
    for (const item of metricRows(payloads.metrics_over_time_data)) {
      if (item.series) values.add(String(item.series));
    }
    for (const name of ["fee_detail_data", "margin_detail_data"]) {
      for (const item of rows(payloads[name])) {
        const label = item.strategy || item.series;
        if (label) values.add(String(label));
      }
    }
    const summaryGroups = groupEntries(summary);
    const mappedMetricKeys = new Set(summaryGroups.flatMap(item => (
      [item.key, item.label, item.metrics_key].filter(Boolean).map(String)
    )));
    for (const item of summaryGroups) values.add(item.label);
    for (const key of Object.keys(summary?.metrics || {})) {
      if (!mappedMetricKeys.has(String(key))) values.add(String(key));
    }
    return [...values];
  }

  function latestMetric(metricRowsValue, label) {
    const selected = metricRowsValue.filter(row => String(row.series || "") === label);
    return selected[selected.length - 1] || null;
  }

  function summaryRows(payloads, summary = {}) {
    const equity = series(payloads.equity_curve_data);
    const metrics = metricRows(payloads.metrics_over_time_data);
    const entries = new Map(groupEntries(summary).map(item => [item.label, item]));
    return groups(payloads, summary).map(label => {
      const curve = equity.find(item => item.label === label);
      const latest = latestMetric(metrics, label) || {};
      const entry = entries.get(label) || {};
      const legacy = summary?.metrics?.[entry.metrics_key || entry.key || label]
        || summary?.metrics?.[label] || {};
      const values = (curve?.values || []).filter(value => value != null);
      const initial = values[0] ?? finite(summary?.initial_capital);
      const final = values[values.length - 1] ?? null;
      const totalReturn = initial && final != null ? final / initial - 1 : null;
      return {
        series: label,
        currency: curve?.currency || String(summary?.base_currency || "CNY").toUpperCase(),
        initial_equity: initial,
        final_equity: final,
        total_return: finite(latest.cumulative_return) ?? totalReturn
          ?? percentFraction(legacy["Total Return"]),
        annual_return: finite(latest.annual_return)
          ?? percentFraction(legacy["Annual Return"]),
        sharpe_ratio: finite(latest.sharpe_ratio) ?? finite(legacy["Sharpe Ratio"]),
        max_drawdown: finite(latest.max_drawdown)
          ?? negativePercentFraction(legacy["Max Drawdown"]),
      };
    });
  }

  function percentFraction(value) {
    const number = finite(value);
    return number == null ? null : number / 100;
  }

  function negativePercentFraction(value) {
    const number = percentFraction(value);
    return number == null ? null : -Math.abs(number);
  }

  function settingValues(root, key, result = [], seen = new Set(), depth = 0) {
    if (!root || typeof root !== "object" || seen.has(root) || depth > 8) return result;
    seen.add(root);
    if (Object.prototype.hasOwnProperty.call(root, key) && root[key] != null
      && root[key] !== "") result.push(root[key]);
    Object.values(root).forEach(value => {
      if (value && typeof value === "object") {
        settingValues(value, key, result, seen, depth + 1);
      }
    });
    return result;
  }

  function uniqueSetting(root, key) {
    const values = [...new Set(settingValues(root, key).map(value => String(value)))];
    return values.length === 1 ? values[0] : "";
  }

  function zonedMidnight(value, timeZone) {
    const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(value || "").trim());
    if (!match) {
      const parsed = Date.parse(String(value || ""));
      return Number.isFinite(parsed) ? parsed : null;
    }
    const target = Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
    if (!timeZone || timeZone === "UTC") return target;
    try {
      const formatter = new Intl.DateTimeFormat("en-US", {
        timeZone, hourCycle: "h23", year: "numeric", month: "2-digit",
        day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit",
      });
      let guess = target;
      for (let iteration = 0; iteration < 2; iteration += 1) {
        const parts = Object.fromEntries(formatter.formatToParts(new Date(guess))
          .filter(item => item.type !== "literal").map(item => [item.type, Number(item.value)]));
        const displayed = Date.UTC(
          parts.year, parts.month - 1, parts.day, parts.hour, parts.minute, parts.second,
        );
        guess += target - displayed;
      }
      return guess;
    } catch (_error) { return target; }
  }

  function evaluationWindow(summary = {}, configuration = {}) {
    const projected = summary?.evaluation_window || {};
    const projectedSplit = finite(projected.split_ms);
    if (projectedSplit != null) {
      return {splitMs: projectedSplit, endMs: finite(projected.end_ms)};
    }
    const split = uniqueSetting(configuration, "evaluation_split");
    if (!split) return null;
    const timeZone = uniqueSetting(configuration, "timezone") || "UTC";
    const splitMs = zonedMidnight(split, timeZone);
    return splitMs == null ? null : {splitMs, endMs: null};
  }

  function metricMatrix(summary = {}) {
    const entries = groupEntries(summary);
    const keys = entries.map(item => item.key);
    for (const key of Object.keys(summary?.metrics || {})) {
      if (!keys.includes(key)) entries.push({key, label: key});
    }
    const metrics = summary?.metrics || {};
    const available = new Set(entries.flatMap(item => Object.keys(
      metrics[item.metrics_key || item.key] || metrics[item.label] || {},
    )));
    const assigned = new Set(metricSections.flatMap(item => item.metrics));
    const sections = metricSections.map(item => ({
      ...item, metrics: item.metrics.filter(metric => available.has(metric)),
    })).filter(item => item.metrics.length);
    const other = [...available].filter(metric => !assigned.has(metric)).sort();
    if (other.length) sections.push({title: "其他", metrics: other});
    return {entries, metrics, sections};
  }

  function metricValue(matrix, entry, metric) {
    return finite((matrix.metrics[entry.metrics_key || entry.key]
      || matrix.metrics[entry.label] || {})[metric]);
  }

  function bestMetricIndex(matrix, metric) {
    const direction = metricDirections[metric] || 0;
    if (!direction) return -1;
    let bestIndex = -1; let bestValue = null;
    matrix.entries.forEach((entry, index) => {
      const value = metricValue(matrix, entry, metric);
      if (value == null) return;
      if (bestIndex < 0 || (direction > 0 ? value > bestValue : value < bestValue)) {
        bestIndex = index; bestValue = value;
      }
    });
    return bestIndex;
  }

  function rowScope(row) {
    return String(row?.strategy || row?.series || "");
  }

  function scopedRows(payload, activeGroup) {
    const values = rows(payload);
    if (!activeGroup) return values;
    const scoped = values.filter(row => rowScope(row) === activeGroup);
    return scoped.length ? scoped : values;
  }

  function availableTabs(payloads, summary = {}) {
    const result = ["summary"];
    if (groupEquityEntries(summary).length) result.push("group_equity");
    if (metricMatrix(summary).entries.length) result.push("group_metrics");
    if (series(payloads.equity_curve_data).length) result.push("equity");
    if (series(payloads.returns_over_time_data).length) result.push("returns");
    if (metricRows(payloads.metrics_over_time_data).length) result.push("metrics");
    if (rows(payloads.fee_detail_data).length) result.push("fees");
    if (rows(payloads.margin_detail_data).length) result.push("margin");
    if (rows(payloads.ratio_detail_data).length) result.push("ratios");
    return result;
  }

  function build(payloads = {}, summary = {}) {
    const resolvedSummary = enrichedSummary(summary, payloads.result);
    return {
      payloads, summary: resolvedSummary,
      groups: groups(payloads, resolvedSummary),
      groupEntries: groupEntries(resolvedSummary),
      metricMatrix: metricMatrix(resolvedSummary),
      summaryRows: summaryRows(payloads, resolvedSummary),
      tabs: availableTabs(payloads, resolvedSummary),
    };
  }

  window.FTBacktestResultModel = Object.freeze({
    availableTabs, bestMetricIndex, build, enrichedSummary, evaluationWindow,
    finite, groupEquityEntries, metricValue,
    groupRequest, initialSnapshot, payloadNames, resolveGroup, rows,
    scopedRows, series,
  });
})();
