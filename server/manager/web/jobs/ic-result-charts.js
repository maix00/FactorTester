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
      rangeSelector: {selected: 5, inputEnabled: true, allButtonsEnabled: true},
      navigator: {enabled: true, adaptToUpdatedData: false}, scrollbar: {enabled: true},
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

  function matchesChoice(value, selected) {
    const values = Array.isArray(selected) ? selected : [selected];
    return !values.filter(Boolean).length || values.map(String).includes(String(value));
  }

  function seriesOptions(factor, context, descriptors = null, methods = "") {
    const selectedDescriptors = Array.isArray(descriptors) ? descriptors : [descriptors];
    const selectedMethods = (Array.isArray(methods) ? methods : [methods]).filter(Boolean);
    const series = (factor?.series || []).filter(item => (
      matchesChoice(window.FTICResultModel.methodOf(item), methods)
        && selectedDescriptors.some(descriptor => (
          !descriptor || window.FTICResultModel.descriptorMatches(item, descriptor)
        ))
    )).map(item => ({
      name: [selectedMethods.length > 1 ? window.FTICResultModel.methodOf(item) : "",
        item.horizon || context.t("默认周期"), `d${item.delay || 0}`]
        .filter(Boolean).join(" · "),
      type: "line",
      data: item.values.flatMap((value, index) => (
        value == null ? [] : [[timestamp(item.dates[index], index), value]]
      )),
      dataGrouping: {enabled: false}, marker: {enabled: false},
    }));
    return lineOptions(context.t("IC 序列"), "IC", series);
  }

  function decayOptions(factor, context, methods = "", delays = []) {
    const selectedMethods = Array.isArray(methods) ? methods : [methods];
    const selectedDelays = (Array.isArray(delays) ? delays : [delays]).map(Number);
    const values = (factor?.statistics || []).filter(item => (
      matchesChoice(window.FTICResultModel.methodOf(item), selectedMethods)
        && (!selectedDelays.length || selectedDelays.includes(Number(item.entry_delay_bars || 0)))
    )).map(item => ({
      method: window.FTICResultModel.methodOf(item),
      horizon: String(item.forward_return_horizon || item.horizon || ""),
      delay: Number(item.entry_delay_bars || 0),
      mean: window.FTICResultModel.finite(item.mean_ic ?? item.mean),
      ir: window.FTICResultModel.finite(item.icir_signal ?? item.IR ?? item.ir),
    })).filter(item => item.mean != null || item.ir != null)
      .sort((left, right) => window.FTICResultModel.horizonSeconds(left.horizon)
        - window.FTICResultModel.horizonSeconds(right.horizon) || left.delay - right.delay);
    const categories = values.map(item => [
      selectedMethods.filter(Boolean).length > 1 ? item.method : "",
      item.horizon || "—", `d${item.delay}`,
    ].filter(Boolean).join(" · "));
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
      const fitted = fitPoints(row, points).map(item => [
        Number(item.horizon_seconds), Number(item.oriented_mean_ic),
      ]).filter(item => Number.isFinite(item[0]) && Number.isFinite(item[1]));
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

  function fitPoints(row, observed) {
    if (Array.isArray(row.fit_points) && row.fit_points.length) return row.fit_points;
    if (observed.length < 2) return [];
    const start = observed[0][0];
    const stop = observed.at(-1)[0];
    const count = 201;
    const selected = String(row.selected_model || "");
    const slope = Number(row.exponential_log_decay_slope_per_second);
    const intercept = Number(row.exponential_log_decay_intercept);
    const smooth = row.smooth_fit;
    return Array.from({length: count}, (_, index) => {
      const seconds = start + ((stop - start) * index) / (count - 1);
      let value = NaN;
      if ((selected === "exponential" || !selected)
        && Number.isFinite(slope) && slope < 0 && Number.isFinite(intercept)) {
        value = Math.exp(intercept + slope * seconds);
      } else if (selected === "damped_oscillatory_exponential" && smooth) {
        const amplitude = Number(smooth.amplitude);
        const decay = Number(smooth.decay_per_day);
        const frequency = Number(smooth.frequency_per_day);
        const phase = Number(smooth.phase);
        const offset = Number(smooth.offset);
        if ([amplitude, decay, frequency, phase, offset].every(Number.isFinite)) {
          const days = (seconds - start) / 86400;
          value = amplitude * Math.exp(-decay * days)
            * Math.cos(frequency * days + phase) + offset;
        }
      }
      return {horizon_seconds: seconds, oriented_mean_ic: value};
    }).filter(item => Number.isFinite(item.oriented_mean_ic));
  }

  function autocorrelationOptions(
    factor, context, summaryRows = [], descriptors = null, methods = "",
  ) {
    const selectedDescriptors = Array.isArray(descriptors) ? descriptors : [descriptors];
    const selectedMethods = (Array.isArray(methods) ? methods : [methods]).filter(Boolean);
    const combinations = (selectedMethods.length ? selectedMethods : [""]).flatMap(method => (
      selectedDescriptors.map(descriptor => ({method, descriptor}))
    ));
    const rows = combinations.map(({method, descriptor}) => ({
      method, descriptor,
      values: window.FTICResultModel.autocorrelation(
        factor, 20, summaryRows, descriptor, method,
      ),
    })).filter(item => item.values.length);
    const lags = [...new Set(rows.flatMap(item => item.values.map(value => value.lag)))]
      .sort((left, right) => left - right);
    return {
      chart: {type: "column", backgroundColor: "transparent", zooming: {type: "x"}},
      title: {text: context.t("IC 自相关衰减"), align: "left", style: {fontSize: "14px"}},
      credits: {enabled: false}, legend: {enabled: rows.length > 1},
      xAxis: {categories: lags.map(item => `Lag ${item}`), crosshair: true},
      yAxis: {
        title: {text: context.t("自相关系数")}, min: -1, max: 1,
        plotLines: [{value: 0.5, color: "#ef4444", dashStyle: "Dash", width: 1,
          label: {text: context.t("半衰线 0.5")}}],
      },
      tooltip: {pointFormat: "<b>{point.category}</b>: {point.y:.4f}"},
      plotOptions: {series: {animation: false}, column: {borderWidth: 0}},
      series: rows.map(item => ({
        name: [item.method, item.descriptor?.horizon,
          item.descriptor ? `d${item.descriptor.delay || 0}` : ""].filter(Boolean).join(" · ")
          || context.t("自相关"),
        data: lags.map(lag => item.values.find(value => value.lag === lag)?.value ?? null),
        negativeColor: "#ef4444",
      })),
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

  window.FTICResultCharts = Object.freeze({
    autocorrelationOptions, decayOptions, holdingDecayOptions, histogramOptions,
    rollingOptions, seriesOptions,
  });
})();
