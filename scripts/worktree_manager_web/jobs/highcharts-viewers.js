(() => {
  const metricCatalog = [
    ["annual_return", "年化收益率", "percent"],
    ["sharpe_ratio", "Sharpe ratio", "number"],
    ["max_drawdown", "历史最大回撤", "percent"],
    ["drawdown", "当前回撤", "percent"],
    ["rolling_volatility_60", "滚动波动率（60期）", "percent"],
    ["rolling_sharpe_60", "滚动 Sharpe（60期）", "number"],
    ["cumulative_return", "累计收益率", "percent"],
  ];

  function number(value) {
    if (value == null || value === "" || typeof value === "boolean") return null;
    const result = Number(value);
    return Number.isFinite(result) ? result : null;
  }

  function timestamp(value, index) {
    if (typeof value === "number" && Number.isFinite(value)) {
      if (Math.abs(value) > 20_000_000_000) return value;
      if (Math.abs(value) > 1_000_000_000) return value * 1000;
      return index;
    }
    const parsed = Date.parse(String(value || ""));
    return Number.isFinite(parsed) ? parsed : index;
  }

  function points(item, field = "values") {
    const values = Array.isArray(item?.[field]) ? item[field] : [];
    const times = Array.isArray(item?.timestamps) ? item.timestamps : [];
    return values.map((value, index) => [
      timestamp(times[index], index), number(value),
    ]).filter(point => point[1] != null);
  }

  function valueFormat(kind, currency = "") {
    if (kind === "percent") return {suffix: "%", scale: 100};
    if (kind === "currency") return {suffix: currency ? ` ${currency}` : "", scale: 1};
    return {suffix: "", scale: 1};
  }

  function scaledPoints(item, kind, field = "values") {
    const format = valueFormat(kind, item?.currency || "");
    return points(item, field).map(([x, y]) => [x, y * format.scale]);
  }

  function baseOptions(title, yTitle, series, kind = "number", currency = "") {
    const format = valueFormat(kind, currency);
    return {
      chart: {backgroundColor: "transparent", panning: {enabled: true, type: "x"}, zooming: {type: "x"}},
      title: {text: title || null, align: "left", style: {fontSize: "14px"}},
      credits: {enabled: false},
      rangeSelector: {selected: 5, inputEnabled: true},
      navigator: {enabled: true},
      scrollbar: {enabled: true},
      legend: {enabled: true},
      xAxis: {type: "datetime", ordinal: false},
      yAxis: [{title: {text: yTitle}, opposite: false}],
      tooltip: {shared: true, valueDecimals: kind === "currency" ? 2 : 4, valueSuffix: format.suffix},
      plotOptions: {series: {animation: false, boostThreshold: 1000, turboThreshold: 0}},
      series,
    };
  }

  function timeSeriesOptions(viewer, payload, context) {
    const items = Array.isArray(payload?.series) ? payload.series : [];
    const artifact = String(payload?.artifact_kind || "");
    const equity = viewer === "equity_curve" || artifact === "equity_curve";
    const returns = artifact === "returns_over_time";
    const ic = artifact === "ic_series";
    const kind = equity ? "currency" : returns ? "percent" : "number";
    const currency = items.find(item => item?.currency)?.currency || "";
    const title = equity ? context.t("净值曲线与回撤")
      : returns ? context.t("收益率随时间变化")
        : ic ? context.t("IC 序列") : context.t("序列图");
    const yTitle = equity ? `${context.t("金额")}（${currency || "CNY"}）`
      : returns ? context.t("收益率（%）") : ic ? "IC" : context.t("数值");
    const series = items.map(item => ({
      id: String(item.factor_ref || item.label || ""),
      name: String(item.label || context.t("序列")),
      type: "line", data: scaledPoints(item, kind),
      tooltip: {valueSuffix: valueFormat(kind, currency).suffix},
    }));
    if (equity) items.forEach(item => {
      if (!Array.isArray(item.drawdown)) return;
      series.push({
        name: `${item.label || context.t("序列")} · ${context.t("当前回撤")}`,
        type: "line", dashStyle: "ShortDash", yAxis: 1,
        data: scaledPoints(item, "percent", "drawdown"),
        tooltip: {valueSuffix: "%"},
      });
    });
    const options = baseOptions(title, yTitle, series, kind, currency);
    if (equity && series.some(item => item.yAxis === 1)) {
      options.yAxis.push({
        title: {text: context.t("回撤（%）")}, opposite: true,
        max: 0, labels: {format: "{value}%"},
      });
    }
    if (ic) options.yAxis[0].plotLines = [{value: 0, color: "#8b95a5", width: 1, zIndex: 2}];
    return options;
  }

  function metricChoices(payload) {
    const rows = Array.isArray(payload?.rows) ? payload.rows : [];
    return metricCatalog.filter(([key]) => rows.some(row => number(row?.[key]) != null))
      .map(([key, label, kind]) => ({key, label, kind}));
  }

  function metricOptions(payload, context, selectedMetric) {
    const rows = Array.isArray(payload?.rows) ? payload.rows : [];
    const choices = metricChoices(payload);
    const metric = choices.find(item => item.key === selectedMetric) || choices[0];
    if (!metric) return baseOptions(context.t("指标随时间变化"), context.t("数值"), []);
    const labels = [...new Set(rows.map(row => String(row.series || context.t("序列"))))];
    const series = labels.map(label => {
      const selected = rows.filter(row => String(row.series || context.t("序列")) === label);
      return {
        name: `${label} · ${context.t(metric.label)}`,
        type: "line",
        data: selected.flatMap((row, index) => {
          const value = number(row[metric.key]);
          if (value == null) return [];
          return [[
            timestamp(row.timestamp, index),
            value * (metric.kind === "percent" ? 100 : 1),
          ]];
        }),
      };
    });
    const yTitle = metric.kind === "percent"
      ? `${context.t(metric.label)}（%）` : context.t(metric.label);
    return baseOptions(context.t("指标随时间变化"), yTitle, series, metric.kind);
  }

  function halfLifeOptions(payload, context) {
    const rows = Array.isArray(payload?.rows) ? payload.rows : [];
    const series = rows.map(row => ({
      name: `${row.factor_alias || context.t("因子")} · delay=${row.entry_delay_bars || 0}`,
      type: "line",
      data: (row.points || []).map(point => [
        number(point.horizon_seconds), number(point.oriented_mean_ic),
      ]).filter(point => point[0] != null && point[1] != null),
    }));
    const options = baseOptions(
      context.t("真实持有期 IC 半衰期"), context.t("方向调整后的 IC"), series,
    );
    options.xAxis = {type: "linear", title: {text: context.t("持有期（秒）")}};
    options.rangeSelector = {enabled: false};
    options.navigator = {enabled: false};
    options.scrollbar = {enabled: false};
    return options;
  }

  function optionsFor(viewer, payload, context, selectedMetric = "") {
    const artifact = String(payload?.artifact_kind || "");
    if (viewer === "metrics_chart" || artifact === "metrics_over_time") {
      return metricOptions(payload, context, selectedMetric);
    }
    if (artifact === "ic_holding_half_life") return halfLifeOptions(payload, context);
    return timeSeriesOptions(viewer, payload, context);
  }

  function supports(viewer, payload) {
    const name = String(viewer || "").toLowerCase();
    const artifact = String(payload?.artifact_kind || "").toLowerCase();
    return ["equity_curve", "line_chart", "metrics_chart"].includes(name)
      || ["equity_curve", "returns_over_time", "metrics_over_time", "ic_series", "ic_holding_half_life"].includes(artifact);
  }

  function mount(context, target, payload, viewer) {
    if (!window.Highcharts?.stockChart) throw new Error(context.t("Highcharts 组件未加载"));
    target._ftChart?.destroy?.();
    target.replaceChildren();
    target.classList.add("interactive-artifact-chart");
    const choices = viewer === "metrics_chart" ? metricChoices(payload) : [];
    const chart = document.createElement("div");
    chart.className = "interactive-artifact-chart-canvas";
    let selected = choices[0]?.key || "";
    if (choices.length > 1) {
      const controls = document.createElement("div");
      controls.className = "interactive-artifact-chart-controls";
      const label = document.createElement("label");
      label.textContent = context.t("显示指标");
      const select = document.createElement("select");
      choices.forEach(item => select.append(new Option(context.t(item.label), item.key)));
      select.addEventListener("change", () => {
        selected = select.value;
        target._ftChart?.destroy?.();
        target._ftChart = window.Highcharts.stockChart(
          chart, optionsFor(viewer, payload, context, selected),
        );
      });
      label.append(select); controls.append(label); target.append(controls);
    }
    target.append(chart);
    target._ftChart = window.Highcharts.stockChart(
      chart, optionsFor(viewer, payload, context, selected),
    );
    return target._ftChart;
  }

  window.FTJobHighcharts = Object.freeze({metricChoices, mount, optionsFor, supports});
})();
