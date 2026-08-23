(() => {
  // Interactive charts are deliberately limited to these Job output IDs.
  // Do not infer interactivity from a viewer name or artifact payload: those
  // are shared by report-ready SVG outputs such as IC charts.
  const interactiveOutputs = new Set([
    "equity_curve",
    "returns_over_time",
    "metrics_over_time",
  ]);

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
    return window.FTChartTimeline.number(value);
  }

  function timestamp(value, index) {
    return window.FTChartTimeline.timestamp(value, index);
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
      time: {useUTC: false},
      title: {text: title || null, align: "left", style: {fontSize: "14px"}},
      credits: {enabled: false},
      rangeSelector: {selected: 5, inputEnabled: true},
      navigator: {enabled: true},
      scrollbar: {enabled: true},
      legend: {enabled: true},
      xAxis: {type: "datetime", ordinal: true},
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
    const kind = equity ? "currency" : returns ? "percent" : "number";
    const currency = items.find(item => item?.currency)?.currency || "";
    const title = equity ? context.t("净值曲线与回撤")
      : returns ? context.t("收益率随时间变化")
        : context.t("序列图");
    const yTitle = equity ? `${context.t("金额")}（${currency || "CNY"}）`
      : returns ? context.t("收益率（%）") : context.t("数值");
    const timeline = equity ? window.FTChartTimeline.observed(items) : [];
    const series = items.map(item => {
      const format = valueFormat(kind, item?.currency || currency);
      return {
        id: String(item.factor_ref || item.series_ref || item.label || ""),
        name: String(item.label || context.t("序列")),
        type: "line",
        data: equity
          ? window.FTChartTimeline.aligned(item, timeline, "values", format.scale)
          : scaledPoints(item, kind),
        connectNulls: true,
        custom: {seriesRef: String(item.factor_ref || item.series_ref || "")},
        tooltip: {valueSuffix: format.suffix},
      };
    });
    if (equity) items.forEach(item => {
      if (!Array.isArray(item.drawdown)) return;
      series.push({
        name: `${item.label || context.t("序列")} · ${context.t("当前回撤")}`,
        type: "area", yAxis: 2,
        data: window.FTChartTimeline.aligned(item, timeline, "drawdown", 100),
        connectNulls: true,
        custom: {seriesRef: String(item.factor_ref || item.series_ref || "")},
        tooltip: {valueSuffix: "%"},
      });
    });
    const options = baseOptions(title, yTitle, series, kind, currency);
    if (equity) {
      const initial = items.flatMap(item => item?.values || [])
        .map(number).find(value => value != null) || 1;
      options.rangeSelector = {enabled: false};
      options.yAxis = [{
        title: {text: yTitle}, opposite: false, top: "0%", height: "64%",
      }, {
        title: {text: context.t("累计收益率（%）")}, opposite: true,
        linkedTo: 0, top: "0%", height: "64%",
        labels: {formatter() { return `${(((this.value / initial) - 1) * 100).toFixed(2)}%`; }},
      }, {
        title: {text: context.t("回撤（%）")}, opposite: false,
        top: "72%", height: "28%", offset: 0, max: 0,
        labels: {format: "{value}%"},
      }];
    }
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

  function applyEvaluationWindow(options, context, displayOptions = {}) {
    const splitMs = number(displayOptions.splitMs);
    if (splitMs == null) return options;
    const showOutOfSample = displayOptions.showOutOfSample === true;
    options.xAxis.max = showOutOfSample ? null : splitMs;
    options.xAxis.plotBands = showOutOfSample ? [{
      from: splitMs,
      to: number(displayOptions.endMs) ?? Number.MAX_SAFE_INTEGER,
      color: "rgba(217, 119, 6, 0.12)",
      label: {
        text: context.t("样本外"),
        style: {color: "#92400e", fontWeight: "600"},
      },
    }] : [];
    return options;
  }

  function optionsFor(viewer, payload, context, selectedMetric = "", displayOptions = {}) {
    const artifact = String(payload?.artifact_kind || "");
    if (viewer === "metrics_chart" || artifact === "metrics_over_time") {
      return applyEvaluationWindow(
        metricOptions(payload, context, selectedMetric), context, displayOptions,
      );
    }
    return applyEvaluationWindow(
      timeSeriesOptions(viewer, payload, context), context, displayOptions,
    );
  }

  function supports(declaration) {
    const outputID = String(declaration?.name || declaration?.id || "").toLowerCase();
    return interactiveOutputs.has(outputID);
  }

  function mount(context, target, payload, viewer, displayOptions = {}) {
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
          chart, optionsFor(viewer, payload, context, selected, displayOptions),
        );
      });
      label.append(select); controls.append(label); target.append(controls);
    }
    target.append(chart);
    target._ftChart = window.Highcharts.stockChart(
      chart, optionsFor(viewer, payload, context, selected, displayOptions),
    );
    return target._ftChart;
  }

  window.FTJobHighcharts = Object.freeze({metricChoices, mount, optionsFor, supports});
})();
