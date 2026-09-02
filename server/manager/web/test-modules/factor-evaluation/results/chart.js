(() => {
  const palette = {
    priceDown: "#e14d5b", priceUp: "#18a572", factor: "#9b35d1",
    volume: "#8aa4c8", openInterest: "#d97706",
  };

  function mount(context, target, options) {
    if (!window.Highcharts?.stockChart) {
      throw new Error(context.t("Highcharts 组件未加载"));
    }
    const bars = window.FTPriceChart.barsOf(options.price || {});
    const factorPoints = window.FTFactorSeriesModel.points(options.factorSeries);
    if (!bars.length && !factorPoints.length) {
      throw new Error(context.t("没有可绘制的价格或因子序列"));
    }
    target.__ftFactorSeriesChart?.destroy?.();
    target.__ftFactorSeriesObserver?.disconnect?.();
    target.replaceChildren();
    target.classList.add("factor-series-chart");
    const chart = window.FTJobHighcharts.mountOptions(
      context, target, chartOptions(context, options, bars, factorPoints), true,
    );
    target.__ftFactorSeriesChart = chart;
    if (window.ResizeObserver) {
      const observer = new ResizeObserver(() => chart.reflow?.());
      observer.observe(target);
      target.__ftFactorSeriesObserver = observer;
    }
    return chart;
  }

  function chartOptions(context, options, bars, factorPoints) {
    const t = value => context.t(value);
    const hasOI = bars.some(item => item.openInterest != null);
    const axes = axisLayout(hasOI, t);
    const series = [
      {
        type: "candlestick", name: options.product || t("价格"), yAxis: 0,
        data: bars.map(item => [
          item.timestamp, item.open, item.high, item.low, item.close,
        ]),
        color: palette.priceDown, upColor: palette.priceUp,
        lineColor: palette.priceDown, upLineColor: palette.priceUp,
        dataGrouping: {groupAll: true},
        tooltip: {
          pointFormatter: window.FTPriceChart.ohlcPointFormatter(context),
        },
      },
      {
        type: "line", name: options.factorLabel || t("因子"), yAxis: 1,
        data: factorPoints, color: palette.factor, lineWidth: 1.6,
        dataGrouping: {approximation: "average", groupAll: true},
      },
      {
        type: "column", name: t("成交量"), yAxis: 2,
        data: bars.map(item => [item.timestamp, item.volume]),
        color: palette.volume,
        dataGrouping: {approximation: "sum", groupAll: true},
        tooltip: {
          pointFormatter: window.FTPriceChart.scalarPointFormatter(context, "成交量"),
        },
      },
    ];
    if (hasOI) series.push({
      type: "line", name: t("持仓量"), yAxis: 3,
      data: bars.map(item => [item.timestamp, item.openInterest]),
      color: palette.openInterest, lineWidth: 1.2,
      dataGrouping: {approximation: "average", groupAll: true},
      tooltip: {
        pointFormatter: window.FTPriceChart.scalarPointFormatter(context, "持仓量"),
      },
    });
    return {
      chart: {
        animation: false, height: 650,
        panning: {enabled: true, type: "x"}, panKey: "shift",
        zooming: {type: "x", mouseWheel: {enabled: true, type: "x"}},
      },
      time: window.FTChartTimeline.timeOptions(),
      title: {text: `${options.product || ""} · ${options.factorLabel || t("因子")}`},
      subtitle: {text: `${bars.length} ${t("条价格")} · ${factorPoints.length} ${t("个因子值")}`},
      rangeSelector: {selected: 5},
      navigator: {enabled: true}, scrollbar: {enabled: true},
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

  function axisLayout(hasOI, t) {
    const values = hasOI
      ? [["42%", "0%"], ["18%", "45%"], ["13%", "66%"], ["13%", "82%"]]
      : [["48%", "0%"], ["22%", "51%"], ["20%", "77%"]];
    const labels = [t("价格"), t("因子"), t("成交量"), t("持仓量")];
    return values.map(([height, top], index) => ({
      height, top, offset: 0, lineWidth: 1,
      title: {text: labels[index]},
      labels: {align: "right", x: -3},
      resize: {enabled: index < values.length - 1},
    }));
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

  window.FTFactorSeriesChart = Object.freeze({contractBands, mount});
})();
