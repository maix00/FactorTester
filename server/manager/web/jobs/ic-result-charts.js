(() => {
  function timestamp(value, index) {
    return window.FTChartTimeline.timestamp(value, index);
  }

  function lineOptions(title, yTitle, series) {
    return {
      chart: {
        backgroundColor: "transparent", panning: {enabled: true, type: "x"},
        zooming: {type: "x"},
      },
      time: window.FTChartTimeline.timeOptions(),
      title: {text: title, align: "left", style: {fontSize: "14px"}},
      credits: {enabled: false},
      rangeSelector: {selected: 5, inputEnabled: true},
      navigator: {enabled: true}, scrollbar: {enabled: true},
      legend: {enabled: true},
      xAxis: window.FTChartTimeline.observedTimeAxis(),
      yAxis: [{title: {text: yTitle}, opposite: false, plotLines: [{
        value: 0, width: 1, color: "#94a3b8", dashStyle: "ShortDash",
      }]}],
      tooltip: {shared: true, valueDecimals: 5},
      plotOptions: {series: {animation: false, boostThreshold: 1000, turboThreshold: 0}},
      series,
    };
  }

  function seriesOptions(factor, context, descriptor = null, method = "") {
    const series = (factor?.series || []).filter(item => (
      window.FTICResultModel.methodMatches(item, method)
        && window.FTICResultModel.descriptorMatches(item, descriptor)
    )).map(item => ({
      name: `${item.horizon || context.t("默认周期")} · d${item.delay || 0}`,
      type: "line",
      data: item.values.flatMap((value, index) => (
        value == null ? [] : [[timestamp(item.dates[index], index), value]]
      )),
      dataGrouping: {enabled: false}, marker: {enabled: false},
    }));
    return lineOptions(context.t("IC 序列"), "IC", series);
  }

  function decayOptions(factor, context, method = "") {
    const values = window.FTICResultModel.decay(factor, method);
    const categories = values.map(item => `${item.horizon || "—"} · d${item.delay}`);
    return {
      chart: {backgroundColor: "transparent", zooming: {type: "x"}},
      title: {text: context.t("IC 衰减分析"), align: "left", style: {fontSize: "14px"}},
      credits: {enabled: false}, legend: {enabled: true},
      xAxis: {categories, title: {text: context.t("预测周期与延迟")}, crosshair: true},
      yAxis: [
        {title: {text: "IC Mean"}, labels: {format: "{value:.4f}"}},
        {title: {text: "IR"}, opposite: true, labels: {format: "{value:.2f}"}},
      ],
      tooltip: {shared: true},
      plotOptions: {series: {animation: false}, column: {borderWidth: 0}},
      series: [
        {name: "IC Mean", type: "column", data: values.map(item => item.mean), yAxis: 0},
        {name: "IR", type: "spline", data: values.map(item => item.ir), yAxis: 1},
      ],
    };
  }

  function durationLabel(seconds) {
    const value = Number(seconds);
    if (!Number.isFinite(value)) return "—";
    if (value < 3600) return `${Number((value / 60).toPrecision(4))}m`;
    if (value < 86400) return `${Number((value / 3600).toPrecision(4))}h`;
    return `${Number((value / 86400).toPrecision(4))}d`;
  }

  function fittedDecayData(row, points) {
    if (!points.length) return [];
    const minimum = points[0][0];
    const maximum = points[points.length - 1][0];
    const grid = Array.from({length: 201}, (_, index) => (
      minimum + ((maximum - minimum) * index / 200)
    ));
    const smooth = row.smooth_fit;
    if (smooth && typeof smooth === "object") {
      const amplitude = Number(smooth.amplitude || 0);
      const decay = Number(smooth.decay_per_day || 0);
      const frequency = Number(smooth.frequency_per_day || 0);
      const phase = Number(smooth.phase || 0);
      const offset = Number(smooth.offset || 0);
      return grid.map(seconds => [seconds, (
        amplitude * Math.exp(-decay * ((seconds - minimum) / 86400))
        * Math.cos(frequency * ((seconds - minimum) / 86400) + phase) + offset
      )]);
    }
    const slope = Number(row.exponential_log_decay_slope_per_second);
    const intercept = Number(row.exponential_log_decay_intercept);
    if (!Number.isFinite(slope) || !Number.isFinite(intercept) || slope >= 0) return [];
    // The payload's points and both fit parameter sets are direction-aligned.
    // Keep the fitted line on that same axis even when the raw baseline IC is
    // negative; applying the original sign again would mirror only the fit.
    return grid.map(seconds => [seconds, Math.exp(intercept + slope * seconds)]);
  }

  function holdingDecayOptions(rows, context) {
    const series = [];
    rows.forEach(row => {
      const label = `${row.factor_alias || context.t("因子")} · d${row.entry_delay_bars || 0}`;
      const direction = Number(row.display_direction || 1);
      const points = (row.points || []).map(item => [
        Number(item.horizon_seconds),
        Number.isFinite(Number(item.oriented_mean_ic))
          ? Number(item.oriented_mean_ic)
          : direction * Number(item.mean_ic),
      ]).filter(item => Number.isFinite(item[0]) && Number.isFinite(item[1]))
        .sort((left, right) => left[0] - right[0]);
      if (!points.length) return;
      series.push({
        name: `${label} · ${context.t("观测值")}`,
        type: "scatter", data: points, marker: {enabled: true, radius: 4},
      });
      const fitted = fittedDecayData(row, points);
      if (fitted.length) series.push({
        name: `${label} · ${context.t("拟合曲线")}`,
        type: "spline", data: fitted, marker: {enabled: false}, dashStyle: "ShortDash",
      });
    });
    return {
      chart: {backgroundColor: "transparent", zooming: {type: "x"}},
      title: {text: context.t("按真实时间间隔的 IC 衰减与半衰期拟合"), align: "left",
        style: {fontSize: "14px"}},
      subtitle: {text: rows.map(row => {
        const seconds = Number(row.exponential_half_life_seconds);
        return Number.isFinite(seconds)
          ? `${row.factor_alias || context.t("因子")} · d${row.entry_delay_bars || 0}: ${context.t("半衰期")} ${durationLabel(seconds)}`
          : "";
      }).filter(Boolean).join(" | ")},
      credits: {enabled: false}, legend: {enabled: true},
      xAxis: {
        type: "linear", title: {text: context.t("真实预测时间间隔")},
        labels: {formatter() { return durationLabel(this.value); }}, crosshair: true,
      },
      yAxis: {title: {text: context.t("方向对齐 IC Mean")},
        plotLines: [{value: 0, width: 1, color: "#94a3b8", dashStyle: "ShortDash"}]},
      tooltip: {shared: true, formatter() {
        const lines = [`<b>${durationLabel(this.x)}</b>`];
        (this.points || []).forEach(point => lines.push(`${point.series.name}: ${point.y.toFixed(5)}`));
        return lines.join("<br>");
      }},
      plotOptions: {series: {animation: false, turboThreshold: 0}}, series,
    };
  }

  function autocorrelationOptions(
    factor, context, summaryRows = [], descriptor = null, method = "",
  ) {
    const values = window.FTICResultModel.autocorrelation(
      factor, 20, summaryRows, descriptor, method,
    );
    return {
      chart: {type: "column", backgroundColor: "transparent", zooming: {type: "x"}},
      title: {text: context.t("IC 自相关衰减"), align: "left", style: {fontSize: "14px"}},
      credits: {enabled: false}, legend: {enabled: false},
      xAxis: {categories: values.map(item => `Lag ${item.lag}`), crosshair: true},
      yAxis: {
        title: {text: context.t("自相关系数")}, min: -1, max: 1,
        plotLines: [{value: 0.5, color: "#ef4444", dashStyle: "Dash", width: 1,
          label: {text: context.t("半衰线 0.5")}}],
      },
      tooltip: {pointFormat: "<b>{point.category}</b>: {point.y:.4f}"},
      plotOptions: {series: {animation: false}, column: {borderWidth: 0}},
      series: [{name: context.t("自相关"), data: values.map(item => item.value), negativeColor: "#ef4444"}],
    };
  }

  function histogramOptions(
    factor, context, summaryRows = [], descriptor = null, method = "",
  ) {
    const bins = window.FTICResultModel.histogram(
      factor, summaryRows, descriptor, method,
    );
    return {
      chart: {type: "column", backgroundColor: "transparent", zooming: {type: "x"}},
      title: {text: context.t("IC 分布"), align: "left", style: {fontSize: "14px"}},
      credits: {enabled: false}, legend: {enabled: false},
      xAxis: {
        categories: bins.map(item => `${item.from.toFixed(3)}…${item.to.toFixed(3)}`),
        title: {text: "IC"}, labels: {rotation: -35},
      },
      yAxis: {title: {text: context.t("观测数")}, allowDecimals: false},
      plotOptions: {series: {animation: false}, column: {borderWidth: 0, groupPadding: 0.02}},
      series: [{name: context.t("观测数"), data: bins.map(item => item.count)}],
    };
  }

  function rollingOptions(rows, context) {
    const supported = [
      ["rolling_mean_ic_p50", "Rolling IC Mean p50"],
      ["rolling_icir_signal_p50", "Rolling ICIR p50"],
      ["rolling_positive_ic_rate_p50", "Positive IC Rate p50"],
    ].filter(([key]) => rows.some(row => window.FTICResultModel.finite(row[key]) != null));
    const categories = rows.map(row => [
      row.forward_return_horizon || row.horizon || "—",
      `d${row.entry_delay_bars || 0}`,
      row.window_key || row.window_label || "",
    ].filter(Boolean).join(" · "));
    return {
      chart: {backgroundColor: "transparent", zooming: {type: "x"}},
      title: {text: context.t("滚动 IC 稳定性"), align: "left", style: {fontSize: "14px"}},
      credits: {enabled: false}, legend: {enabled: true},
      xAxis: {categories, crosshair: true},
      yAxis: {title: {text: context.t("统计值")}}, tooltip: {shared: true},
      plotOptions: {series: {animation: false, connectNulls: false}},
      series: supported.map(([key, label]) => ({
        name: label, type: "line",
        data: rows.map(row => window.FTICResultModel.finite(row[key])),
      })),
    };
  }

  function mount(target, options, stock = false) {
    if (!window.Highcharts) throw new Error("Highcharts is unavailable");
    target._ftChart?.destroy?.();
    target.replaceChildren();
    const canvas = document.createElement("div");
    canvas.className = "ic-domain-chart-canvas";
    target.append(canvas);
    target._ftChart = stock && window.Highcharts.stockChart
      ? window.Highcharts.stockChart(canvas, options)
      : window.Highcharts.chart(canvas, options);
    return target._ftChart;
  }

  window.FTICResultCharts = Object.freeze({
    autocorrelationOptions, decayOptions, holdingDecayOptions, histogramOptions, mount,
    rollingOptions, seriesOptions,
  });
})();
