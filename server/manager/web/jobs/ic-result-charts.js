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
      legend: {enabled: true}, xAxis: {type: "datetime", ordinal: false},
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
    autocorrelationOptions, decayOptions, histogramOptions, mount,
    rollingOptions, seriesOptions,
  });
})();
