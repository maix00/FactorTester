(() => {
  const palette = {
    priceDown: "#e14d5b", priceUp: "#18a572", factor: "#9b35d1",
    volume: "#8aa4c8", openInterest: "#d97706",
  };

  function mount(context, target, options, displayOptions = {}) {
    if (!window.Highcharts?.stockChart) {
      throw new Error(context.t("Highcharts 组件未加载"));
    }
    const bars = window.FTPriceChart.barsOf(options.price || {});
    const factorPoints = window.FTFactorSeriesModel.points(options.factorSeries);
    if (!bars.length && !factorPoints.length) {
      throw new Error(context.t("没有可绘制的价格或因子序列"));
    }
    dispose(target);
    target.replaceChildren();
    target.classList.add("factor-series-chart");
    const chart = window.FTJobHighcharts.mountOptions(
      context, target, chartOptions(context, options, bars, factorPoints), true, {
        ...displayOptions,
        rangeOptions: incoming => {
          const range = incoming?.__ftRange || {};
          const next = {...options, price: incoming};
          return chartOptions(
            context, next, window.FTPriceChart.barsOf(incoming || {}),
            window.FTFactorSeriesModel.points(
              options.factorSeries, range.minimum, range.maximum,
            ),
          );
        },
      },
    );
    target.__ftFactorSeriesChart = chart;
    if (window.ResizeObserver) {
      const observer = new ResizeObserver(() => chart.reflow?.());
      observer.observe(target);
      target.__ftFactorSeriesObserver = observer;
    }
    return chart;
  }

  function dispose(target) {
    const chart = target?.__ftFactorSeriesChart;
    if (chart) {
      window.clearTimeout?.(chart._ftRangeLoadTimer);
      chart._ftRangeLoadGeneration = (chart._ftRangeLoadGeneration || 0) + 1;
    }
    target?.__ftFactorSeriesObserver?.disconnect?.();
    if (target) {
      if (target._ftChart === chart) target._ftChart = null;
      target.__ftFactorSeriesChart = null;
      target.__ftFactorSeriesObserver = null;
    }
    chart?.destroy?.();
  }

  function chartOptions(context, options, bars, factorPoints) {
    const t = value => context.t(value);
    const hasOI = bars.some(item => item.openInterest != null);
    const extra = [
      ["cs_rank", "因子 cs_rank", options.factorSeries?.cs_rank],
      ["returns", "收益率", options.factorSeries?.returns],
      ["returns_cs_rank", "收益率 cs_rank", options.factorSeries?.returns_cs_rank],
    ].filter(([, , value]) => value && Array.isArray(value.values));
    const axes = axisLayout(hasOI, t, extra.map(([, label]) => label));
    const volumeAxis = 2 + extra.length;
    const series = [
      {
        type: "candlestick", name: options.product || t("价格"), yAxis: 0,
        data: bars.map(item => [
          item.timestamp, item.open, item.high, item.low, item.close,
        ]),
        color: palette.priceDown, upColor: palette.priceUp,
        lineColor: palette.priceDown, upLineColor: palette.priceUp,
        dataGrouping: {enabled: false},
        tooltip: {
          pointFormatter: window.FTPriceChart.ohlcPointFormatter(context),
        },
      },
      {
        type: "line", name: t("因子值"), yAxis: 1,
        data: factorPoints, color: palette.factor, lineWidth: 1.6,
        dataGrouping: {enabled: false},
        tooltip: {pointFormatter: factorPointFormatter(context)},
      },
      {
        type: "column", name: t("成交量"), yAxis: volumeAxis,
        data: bars.map(item => [item.timestamp, item.volume]),
        color: palette.volume,
        dataGrouping: {enabled: false},
        tooltip: {
          pointFormatter: window.FTPriceChart.scalarPointFormatter(context, "成交量"),
        },
      },
    ];
    extra.forEach(([, label, value], index) => series.splice(2 + index, 0, {
      type: "line", name: t(label), yAxis: 2 + index,
      data: window.FTFactorSeriesModel.points(value),
      lineWidth: 1.35, dataGrouping: {enabled: false},
      tooltip: {pointFormatter: window.FTPriceChart.scalarPointFormatter(context, label)},
    }));
    if (hasOI) series.push({
      type: "line", name: t("持仓量"), yAxis: volumeAxis + 1,
      data: bars.map(item => [item.timestamp, item.openInterest]),
      color: palette.openInterest, lineWidth: 1.2,
      dataGrouping: {enabled: false},
      tooltip: {
        pointFormatter: window.FTPriceChart.scalarPointFormatter(context, "持仓量"),
      },
    });
    return {
      chart: {
        animation: false,
        panning: {enabled: true, type: "x"}, panKey: "shift",
        zooming: {type: "x", mouseWheel: {enabled: true, type: "x"}},
      },
      time: window.FTChartTimeline.timeOptions(),
      title: {text: `${options.product || ""} · ${options.factorLabel || t("因子")}`},
      subtitle: {text: `${bars.length} ${t("条价格")} · ${factorPoints.length} ${t("个因子值")}`},
      rangeSelector: {selected: 5},
      navigator: {
        enabled: true,
        series: {
          type: "line",
          name: options.product || t("价格"),
          data: bars.map(item => [item.timestamp, item.close]),
          dataGrouping: {enabled: false},
        },
      },
      scrollbar: {enabled: true},
      xAxis: {
        type: "datetime", ordinal: true,
        labels: {
          formatter: window.FTPriceChart.dateLabelFormatter(context),
        },
        plotBands: contractBands(options.contracts || []),
      },
      yAxis: axes,
      tooltip: {shared: true, split: false, valueDecimals: 4},
      plotOptions: {series: {animation: false, turboThreshold: 0}},
      credits: {enabled: false}, series,
    };
  }

  function factorPointFormatter(context) {
    const scalar = window.FTPriceChart.scalarPointFormatter(context, "因子值");
    return function() {
      // The OHLC formatter has no trailing break. Prefixing one keeps the
      // factor value on its own line in Highcharts' shared tooltip.
      return `<br/>${scalar.call(this)}`;
    };
  }

  function axisLayout(hasOI, t, extraLabels = []) {
    const labels = ["价格", "因子值", ...extraLabels, "成交量", ...(hasOI ? ["持仓量"] : [])];
    const weights = labels.map((_, index) => index === 0 ? 3 : (index === 1 ? 1.6 : 1));
    const gap = 2;
    const available = 100 - gap * (labels.length - 1);
    const total = weights.reduce((sum, value) => sum + value, 0);
    let top = 0;
    return labels.map((label, index) => {
      const height = available * weights[index] / total;
      const axis = {
      height: `${height}%`, top: `${top}%`, offset: 0, lineWidth: 1,
      title: {text: t(label)},
      labels: {align: "right", x: -3},
      resize: {enabled: index < labels.length - 1},
      };
      top += height + gap;
      return axis;
    });
  }

  function contractBands(contracts) {
    return contracts.flatMap((item, index) => {
      const from = window.FTPriceChart.timestampOf(item.start || item.start_date);
      const to = window.FTPriceChart.timestampOf(item.end || item.end_date);
      if (!Number.isFinite(from) || !Number.isFinite(to)) return [];
      return [{
        from, to, color: index % 2 ? "rgba(79, 70, 229, .035)" : "transparent",
        label: {text: item.contract || item.uid || "", style: {fontSize: "10px"}},
      }];
    });
  }

  window.FTFactorSeriesChart = Object.freeze({contractBands, dispose, mount});
})();
