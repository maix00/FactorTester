(() => {
  const tabPayloads = Object.freeze({
    equity: "equity_curve_data",
    returns: "returns_over_time_data",
    metrics: "metrics_over_time_data",
    fees: "fee_detail_data",
    margin: "margin_detail_data",
    ratios: "ratio_detail_data",
    orders: "order_detail_data",
    fills: "fill_detail_data",
    cash: "cash_detail_data",
    positions: "position_detail_data",
    exposure: "exposure_detail_data",
    turnover: "turnover_detail_data",
    drawdowns: "drawdown_detail_data",
    period_returns: "period_returns_data",
  });
  const payloadNames = Object.freeze(Object.values(tabPayloads));
  const fallbackResultViews = Object.freeze({
    factor_series_data: {surface: "factor_series", view: "factor_series", label: "因子序列", order: 5},
    equity_curve_data: {surface: "time_series", view: "equity", label: "净值与回撤", order: 10},
    returns_over_time_data: {surface: "time_series", view: "returns", label: "收益率", order: 20},
    metrics_over_time_data: {surface: "time_series", view: "metrics", label: "滚动指标", order: 30},
    exposure_detail_data: {surface: "time_series", view: "exposure", label: "风险敞口", order: 60},
    turnover_detail_data: {surface: "time_series", view: "turnover", label: "换手率", order: 70},
    order_detail_data: {surface: "execution_account", view: "orders", label: "订单", order: 10},
    fill_detail_data: {surface: "execution_account", view: "fills", label: "成交与结算", order: 20},
    cash_detail_data: {surface: "execution_account", view: "cash", label: "现金", order: 30},
    position_detail_data: {surface: "execution_account", view: "positions", label: "持仓", order: 40},
    margin_detail_data: {surface: "execution_account", view: "margin", label: "保证金", order: 50},
    fee_detail_data: {surface: "execution_account", view: "fees", label: "手续费", order: 60},
    ratio_detail_data: {surface: "return_analysis", view: "cost_ratios", label: "收益与成本", order: 10},
    drawdown_detail_data: {surface: "return_analysis", view: "drawdown_episodes", label: "回撤区间", order: 20},
    period_returns_data: {surface: "return_analysis", view: "period_returns", label: "周期收益", order: 30},
  });

  function resultViews(declarations = []) {
    const registered = new Map();
    (Array.isArray(declarations) ? declarations : []).forEach(item => {
      const artifact = String(item?.canonical_artifact || "");
      if (!artifact || !item?.result_surface || !item?.result_view) return;
      registered.set(artifact, {
        surface: String(item.result_surface), view: String(item.result_view),
        label: String(item.label || item.result_view),
        order: Number(item.result_order || 0),
        bundle: String(item.supplemental_bundle || ""),
      });
    });
    return new Map(Object.entries(fallbackResultViews).map(([artifact, value]) => [
      artifact, {...value, ...(registered.get(artifact) || {})},
    ]));
  }

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
      strategyID: String(item?.strategy_id || item?.strategy_ref || ""),
      configurationID: String(item?.strategy_configuration_id || ""),
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
      strategyID: String(item?.strategy_id || item?.group_id || item?.key || index),
      configurationID: String(item?.strategy_configuration_id || ""),
      key: String(item?.strategy_id || item?.group_id || item?.key || item?.name || item?.metrics_key || index),
      label: String(item?.display_name || item?.name || item?.group_name || item?.strategy_id || item?.group_id || item?.key || item?.metrics_key || index),
    }));
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

  function diagnosticConfiguration(entry = {}, summary = {}) {
    const explicit = String(
      entry.configurationID || entry.strategy_configuration_id || "",
    );
    if (explicit) return {strategy_configuration_id: explicit};
    const source = {...summary, ...entry};
    const keys = [
      "strategy_configuration_id", "strategy_template_ref", "product_path_selection_id",
      "factor_ref", "factor_alias", "engine", "allocation_policy",
      "rebalance_trigger", "position_policy", "split_count", "is_ls", "ls_info",
    ];
    return Object.fromEntries(keys.flatMap(key => (
      source[key] == null || source[key] === "" ? [] : [[key, source[key]]]
    )));
  }

  function diagnosticKey(entry = {}, summary = {}) {
    return JSON.stringify(diagnosticConfiguration(entry, summary));
  }

  function relatedGroupEntries(summary = {}, entry = null) {
    if (!entry) return [];
    const key = diagnosticKey(entry, summary);
    return groupEntries(summary).filter(candidate => diagnosticKey(candidate, summary) === key);
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

  function strategies(payloads, summary = {}) {
    const result = new Map();
    const summaryEntries = groupEntries(summary);
    const labelToID = new Map(summaryEntries.map(entry => [entry.label, entry.strategyID]));
    const add = (strategyID, strategyLabel, configurationID = "") => {
      const id = String(strategyID || "").trim();
      if (!id) return;
      const previous = result.get(id) || {};
      result.set(id, {
        id,
        label: String(strategyLabel || previous.label || id),
        configurationID: String(configurationID || previous.configurationID || ""),
      });
    };
    summaryEntries.forEach(entry => add(
      entry.strategyID, entry.label, entry.configurationID,
    ));
    Object.values(payloads || {}).forEach(payload => {
      series(payload).forEach(item => add(
        item.strategyID || labelToID.get(item.label), item.label, item.configurationID,
      ));
      rows(payload).forEach(row => {
        const strategyLabel = String(
          row?.strategy_label || row?.series || row?.strategy || "",
        );
        const rawID = row?.strategy_id || row?.strategy_ref || row?.strategy;
        add(
          labelToID.get(String(rawID || "")) || labelToID.get(strategyLabel) || rawID,
          strategyLabel, row?.strategy_configuration_id,
        );
      });
    });
    return [...result.values()];
  }

  function latestMetric(metricRowsValue, strategy) {
    const selected = metricRowsValue.filter(row => (
      String(row.strategy_id || row.series || "") === strategy.id
      || String(row.series || "") === strategy.label
    ));
    return selected[selected.length - 1] || null;
  }

  function summaryRows(payloads, summary = {}) {
    const equity = series(payloads.equity_curve_data);
    const metrics = metricRows(payloads.metrics_over_time_data);
    const entries = new Map(groupEntries(summary).map(item => [item.strategyID, item]));
    return strategies(payloads, summary).map(strategy => {
      const curve = equity.find(item => (
        item.strategyID === strategy.id || item.label === strategy.label
      ));
      const latest = latestMetric(metrics, strategy) || {};
      const entry = entries.get(strategy.id) || {};
      const legacy = summary?.metrics?.[entry.metrics_key || entry.key || strategy.id]
        || summary?.metrics?.[strategy.label] || {};
      const values = (curve?.values || []).filter(value => value != null);
      const initial = values[0] ?? finite(summary?.initial_capital);
      const final = values[values.length - 1] ?? null;
      const totalReturn = initial && final != null ? final / initial - 1 : null;
      return {
        strategy_id: strategy.id,
        strategy_configuration_id: strategy.configurationID,
        series: strategy.label,
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
    const keys = new Set(entries.flatMap(item => (
      [item.key, item.label, item.metrics_key].filter(Boolean).map(String)
    )));
    for (const key of Object.keys(summary?.metrics || {})) {
      if (!keys.has(String(key))) entries.push({key, label: key, strategyID: key});
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
    return String(row?.strategy_id || row?.strategy_ref || row?.strategy || row?.series || "");
  }

  function scopedRows(payload, activeGroup) {
    const values = rows(payload);
    if (!activeGroup) return values;
    const scoped = values.filter(row => rowScope(row) === activeGroup);
    return scoped.length ? scoped : values;
  }

  function availableTabs(payloads, summary = {}, artifactNames = [], declarations = []) {
    const availableArtifacts = new Set(artifactNames.map(String));
    const hasPayload = name => Boolean(payloads[name]) || availableArtifacts.has(name);
    const result = [];
    if (summaryRows(payloads, summary).length) result.push("overview");
    if (metricMatrix(summary).entries.length) result.push("strategy_stats");
    const surfaces = new Set();
    for (const [artifact, definition] of resultViews(declarations)) {
      if (hasPayload(artifact) || (declarations || []).some(item => (
        String(item?.canonical_artifact || "") === artifact
      ))) surfaces.add(definition.surface);
    }
    ["time_series", "execution_account", "return_analysis"].forEach(surface => {
      if (surfaces.has(surface)) result.push(surface);
    });
    return result;
  }

  function build(payloads = {}, summary = {}, artifactNames = [], declarations = []) {
    const strategyLabels = groups(payloads, summary);
    const strategyEntries = strategies(payloads, summary);
    return {
      payloads, summary,
      groups: strategyLabels,
      strategies: strategyEntries,
      groupEntries: groupEntries(summary),
      metricMatrix: metricMatrix(summary),
      summaryRows: summaryRows(payloads, summary),
      resultViews: resultViews(declarations),
      tabs: availableTabs(payloads, summary, artifactNames, declarations),
    };
  }

  window.FTBacktestResultModel = Object.freeze({
    availableTabs, bestMetricIndex, build, evaluationWindow,
    diagnosticConfiguration, diagnosticKey, finite, metricValue,
    groupRequest, initialSnapshot, payloadNames, resolveGroup, rows,
    relatedGroupEntries, resultViews, strategies,
    tabPayloads,
    scopedRows, series,
  });
})();
