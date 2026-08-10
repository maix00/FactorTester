(() => {
  const payloadNames = Object.freeze([
    "equity_curve_data", "returns_over_time_data", "metrics_over_time_data",
    "fee_detail_data", "margin_detail_data", "ratio_detail_data",
  ]);

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

  function groups(payloads) {
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
    return [...values];
  }

  function latestMetric(metricRowsValue, label) {
    const selected = metricRowsValue.filter(row => String(row.series || "") === label);
    return selected[selected.length - 1] || null;
  }

  function summaryRows(payloads) {
    const equity = series(payloads.equity_curve_data);
    const metrics = metricRows(payloads.metrics_over_time_data);
    return groups(payloads).map(label => {
      const curve = equity.find(item => item.label === label);
      const latest = latestMetric(metrics, label) || {};
      const values = (curve?.values || []).filter(value => value != null);
      const initial = values[0] ?? null;
      const final = values[values.length - 1] ?? null;
      const totalReturn = initial && final != null ? final / initial - 1 : null;
      return {
        series: label,
        currency: curve?.currency || "CNY",
        initial_equity: initial,
        final_equity: final,
        total_return: finite(latest.cumulative_return) ?? totalReturn,
        annual_return: finite(latest.annual_return),
        sharpe_ratio: finite(latest.sharpe_ratio),
        max_drawdown: finite(latest.max_drawdown),
      };
    });
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

  function availableTabs(payloads) {
    const result = ["summary"];
    if (series(payloads.equity_curve_data).length) result.push("equity");
    if (series(payloads.returns_over_time_data).length) result.push("returns");
    if (metricRows(payloads.metrics_over_time_data).length) result.push("metrics");
    if (rows(payloads.fee_detail_data).length) result.push("fees");
    if (rows(payloads.margin_detail_data).length) result.push("margin");
    if (rows(payloads.ratio_detail_data).length) result.push("ratios");
    return result;
  }

  function build(payloads = {}) {
    return {
      payloads,
      groups: groups(payloads),
      summaryRows: summaryRows(payloads),
      tabs: availableTabs(payloads),
    };
  }

  window.FTBacktestResultModel = Object.freeze({
    availableTabs, build, finite, payloadNames, rows, scopedRows, series,
  });
})();
