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
      time: window.FTChartTimeline.timeOptions(),
      title: {text: title || null, align: "left", style: {fontSize: "14px"}},
      credits: {enabled: false},
      rangeSelector: {selected: 5, inputEnabled: true},
      navigator: {enabled: true, adaptToUpdatedData: false},
      scrollbar: {enabled: true},
      legend: {enabled: true},
      xAxis: window.FTChartTimeline.observedTimeAxis(),
      yAxis: [{title: {text: yTitle}, opposite: false}],
      tooltip: {shared: true, valueDecimals: kind === "currency" ? 2 : 4, valueSuffix: format.suffix},
      plotOptions: {series: {
        animation: false, boostThreshold: 1000, turboThreshold: 0,
        marker: {enabled: false}, dataGrouping: {enabled: false},
      }},
      series,
    };
  }

  function attachInteractions(options, displayOptions = {}) {
    const range = displayOptions.chartRange;
    if (range && Number.isFinite(range.min) && Number.isFinite(range.max)) {
      options.xAxis = {...(options.xAxis || {}), min: range.min, max: range.max};
    }
    if (typeof displayOptions.onRangeChange === "function") {
      options.xAxis = options.xAxis || {};
      const previous = options.xAxis.events?.setExtremes;
      options.xAxis.events = {...(options.xAxis.events || {}), setExtremes(event) {
        previous?.call(this, event);
        if (event?.trigger !== "ft-sync") {
          displayOptions.onRangeChange(event.min, event.max, this.chart);
        }
      }};
    }
    if (typeof displayOptions.loadRange === "function"
        && typeof displayOptions.rangeOptions === "function") {
      options.xAxis = options.xAxis || {};
      const previous = options.xAxis.events?.afterSetExtremes;
      options.xAxis.events = {...(options.xAxis.events || {}), afterSetExtremes(event) {
        previous?.call(this, event);
        if (event?.trigger === "ft-data-refresh"
            || !Number.isFinite(Number(event?.min))
            || !Number.isFinite(Number(event?.max))) return;
        const chart = this.chart;
        clearTimeout(chart._ftRangeLoadTimer);
        const generation = (chart._ftRangeLoadGeneration || 0) + 1;
        chart._ftRangeLoadGeneration = generation;
        chart._ftRangeLoadTimer = setTimeout(async () => {
          chart.showLoading?.(displayOptions.loadingText || "Loading…");
          try {
            const payload = await displayOptions.loadRange(
              Number(event.min), Number(event.max), {
                maxPoints: Math.max(200, Math.ceil(Number(chart.plotWidth || 600) * 1.5)),
              },
            );
            if (!payload || chart._ftRangeLoadGeneration !== generation) return;
            replaceVisibleSeries(
              chart, displayOptions.rangeOptions(payload),
              Number(event.min), Number(event.max),
            );
          } catch (error) {
            if (error?.name !== "AbortError") {
              displayOptions.onRangeError?.(error);
            }
          } finally {
            if (chart._ftRangeLoadGeneration === generation) chart.hideLoading?.();
          }
        }, Math.max(0, Number(displayOptions.rangeDebounceMs) || 120));
      }};
    }
    if (typeof displayOptions.onPointClick !== "function") return options;
    options.plotOptions = options.plotOptions || {};
    options.plotOptions.series = {
      ...(options.plotOptions.series || {}),
      cursor: "pointer",
      point: {events: {click() {
        displayOptions.onPointClick(this.x, this.series?.userOptions?.custom || {});
      }}},
    };
    return options;
  }

  function replaceVisibleSeries(chart, nextOptions, minimum, maximum) {
    const definitions = Array.isArray(nextOptions?.series) ? nextOptions.series : [];
    const visible = chart.series.filter(series => !series.options?.isInternal);
    const remaining = new Set(visible);
    definitions.forEach(definition => {
      const identity = String(definition.id || definition.name || "");
      const current = visible.find(series => (
        remaining.has(series)
        && String(series.options?.id || series.name || "") === identity
      ));
      if (!current) {
        chart.addSeries(definition, false);
        return;
      }
      remaining.delete(current);
      const {data, ...presentation} = definition;
      current.update(presentation, false);
      current.setData(definition.data || [], false, false, false);
    });
    remaining.forEach(series => series.remove(false));
    chart.xAxis[0]?.setExtremes(
      minimum, maximum, false, false, {trigger: "ft-data-refresh"},
    );
    chart.redraw(false);
  }

  function timeSeriesOptions(viewer, payload, context) {
    const items = Array.isArray(payload?.series) ? payload.series : [];
    const artifact = String(payload?.artifact_kind || "");
    const drawdown = viewer === "drawdown_curve";
    const equity = !drawdown && (viewer === "equity_curve" || artifact === "equity_curve");
    const returns = artifact === "returns_over_time";
    const kind = equity ? "currency" : drawdown || returns ? "percent" : "number";
    const currency = items.find(item => item?.currency)?.currency || "";
    const title = equity ? context.t("净值曲线")
      : drawdown ? context.t("回撤曲线")
      : returns ? context.t("收益率随时间变化")
        : context.t("序列图");
    const yTitle = equity ? `${context.t("金额")}（${currency || "CNY"}）`
      : drawdown ? context.t("回撤（%）")
        : returns ? context.t("收益率（%）") : context.t("数值");
    const timeline = equity || drawdown ? window.FTChartTimeline.observed(items) : [];
    const series = items.map(item => {
      const format = valueFormat(kind, item?.currency || currency);
      return {
        id: String(item.factor_ref || item.series_ref || item.label || ""),
        name: drawdown
          ? `${item.label || context.t("序列")} · ${context.t("当前回撤")}`
          : String(item.label || context.t("序列")),
        type: drawdown ? "area" : "line",
        data: equity || drawdown
          ? window.FTChartTimeline.aligned(
            item, timeline, drawdown ? "drawdown" : "values", drawdown ? 100 : format.scale,
          )
          : scaledPoints(item, kind),
        connectNulls: true,
        custom: {seriesRef: String(item.factor_ref || item.series_ref || "")},
        tooltip: {valueSuffix: drawdown ? "%" : format.suffix},
      };
    }).filter(item => !drawdown || item.data.some(([, value]) => value != null));
    const options = baseOptions(title, yTitle, series, kind, currency);
    if (equity) {
      const initial = items.flatMap(item => item?.values || [])
        .map(number).find(value => value != null) || 1;
      options.rangeSelector = {enabled: false};
      options.yAxis = [{title: {text: yTitle}, opposite: false}, {
        title: {text: context.t("累计收益率（%）")}, opposite: true,
        linkedTo: 0,
        labels: {formatter() { return `${(((this.value / initial) - 1) * 100).toFixed(2)}%`; }},
      }];
    } else if (drawdown) {
      options.yAxis = [{
        title: {text: yTitle}, opposite: false, max: 0,
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
      const options = attachInteractions(applyEvaluationWindow(
        metricOptions(payload, context, selectedMetric), context, displayOptions,
      ), displayOptions);
      if (displayOptions.hideTitle) options.title.text = null;
      return options;
    }
    const options = attachInteractions(applyEvaluationWindow(
      timeSeriesOptions(viewer, payload, context), context, displayOptions,
    ), displayOptions);
    if (displayOptions.hideTitle) options.title.text = null;
    return options;
  }

  function rowSeriesOptions(payload, context, definition = {}, displayOptions = {}) {
    let rows = Array.isArray(payload?.rows) ? payload.rows : [];
    if (definition.aggregate === "strategy_margin_equity_ratio") {
      const grouped = new Map();
      rows.forEach(row => {
        const strategy = String(row?.strategy_id || row?.strategy || row?.series || "");
        const key = `${strategy}\u0000${String(row?.timestamp ?? "")}`;
        const group = grouped.get(key) || [];
        group.push(row); grouped.set(key, group);
      });
      rows = [...grouped.values()].map(group => {
        const total = group.find(row => String(row?.product || "") === "__total__");
        if (total) return total;
        const margin = group.reduce((sum, row) => sum + (number(row?.margin) || 0), 0);
        const equity = number(group.find(row => number(row?.equity) != null)?.equity);
        return {
          ...group[0], margin, equity,
          margin_utilization: equity ? margin / equity : group.reduce(
            (sum, row) => sum + (number(row?.margin_utilization) || 0), 0,
          ),
        };
      });
    }
    const fields = Array.isArray(definition.fields) ? definition.fields : [];
    const labels = definition.labels || {};
    const grouped = new Map();
    rows.forEach((row, index) => {
      const time = timestamp(row?.timestamp, index);
      if (!Number.isFinite(time)) return;
      const strategy = String(row?.strategy_id || row?.strategy || row?.series || context.t("序列"));
      fields.forEach(field => {
        const value = number(row?.[field]);
        if (value == null) return;
        const key = `${strategy}\u0000${field}`;
        if (!grouped.has(key)) grouped.set(key, {strategy, field, data: []});
        grouped.get(key).data.push([time, value * (definition.percentFields?.includes(field) ? 100 : 1)]);
      });
    });
    const series = [...grouped.values()].map(item => ({
      name: `${item.strategy} · ${context.t(labels[item.field] || item.field)}`,
      type: "line", data: item.data,
      custom: {field: item.field, seriesRef: item.strategy},
      tooltip: {valueSuffix: definition.percentFields?.includes(item.field) ? "%" : ""},
    }));
    const options = baseOptions(
      context.t(definition.label || "时变指标"), context.t(definition.yTitle || "数值"), series,
    );
    if (displayOptions.hideTitle) options.title.text = null;
    return attachInteractions(applyEvaluationWindow(options, context, displayOptions), displayOptions);
  }

  function mountRows(context, target, payload, definition, displayOptions = {}) {
    if (!window.Highcharts?.stockChart) throw new Error(context.t("Highcharts 组件未加载"));
    target._ftChart?.destroy?.();
    target.replaceChildren();
    target.classList.add("interactive-artifact-chart");
    const chart = document.createElement("div");
    chart.className = "interactive-artifact-chart-canvas";
    target.append(chart);
    const options = {
      ...displayOptions,
      rangeOptions: incoming => rowSeriesOptions(
        incoming, context, definition, {...displayOptions, loadRange: null},
      ),
    };
    target._ftChart = window.Highcharts.stockChart(
      chart, rowSeriesOptions(payload, context, definition, options),
    );
    return target._ftChart;
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
    let selected = choices.some(item => item.key === displayOptions.selectedMetric)
      ? displayOptions.selectedMetric : choices[0]?.key || "";
    const chartOptions = incoming => optionsFor(
      viewer, incoming, context, selected, {
        ...displayOptions,
        rangeOptions: next => optionsFor(
          viewer, next, context, selected, {...displayOptions, loadRange: null},
        ),
      },
    );
    if (choices.length > 1 && !displayOptions.hideMetricControl) {
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
          chart, chartOptions(payload),
        );
      });
      label.append(select); controls.append(label); target.append(controls);
    }
    target.append(chart);
    target._ftChart = window.Highcharts.stockChart(
      chart, chartOptions(payload),
    );
    return target._ftChart;
  }

  function mountOptions(context, target, options, stock = false, displayOptions = {}) {
    const factory = stock ? window.Highcharts?.stockChart : window.Highcharts?.chart;
    if (!factory) throw new Error(context.t("Highcharts 组件未加载"));
    target._ftChart?.destroy?.();
    target.replaceChildren();
    target.classList.add("interactive-artifact-chart");
    const chart = document.createElement("div");
    chart.className = "interactive-artifact-chart-canvas";
    target.append(chart);
    target._ftChart = factory.call(
      window.Highcharts, chart, attachInteractions(options, displayOptions),
    );
    return target._ftChart;
  }

  window.FTJobHighcharts = Object.freeze({
    metricChoices, mount, mountOptions, mountRows, optionsFor, rowSeriesOptions, supports,
  });
})();
