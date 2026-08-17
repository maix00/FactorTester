(() => {
  function render(context, target, payload) {
    const highcharts = window.Highcharts;
    if (!highcharts?.stockChart) {
      target.replaceChildren?.(empty(context, "交互式行情图组件未加载"));
      return null;
    }
    const bars = barsOf(payload);
    if (!bars.length) {
      target.replaceChildren?.(empty(context, "未找到可绘制的 OHLCV 数据"));
      return null;
    }
    target.__ftPriceChart?.destroy?.();
    target.__ftPriceChartObserver?.disconnect?.();
    target.classList?.add("interactive-price-chart");
    const chart = highcharts.stockChart(target, optionsOf(context, payload, bars));
    target.__ftPriceChart = chart;
    if (window.ResizeObserver) {
      const observer = new ResizeObserver(() => chart.reflow?.());
      observer.observe(target);
      target.__ftPriceChartObserver = observer;
    }
    return chart;
  }

  function rowsOf(payload) {
    if (Array.isArray(payload)) return payload;
    if (Array.isArray(payload?.data)) return payload.data;
    if (Array.isArray(payload?.rows)) return payload.rows;
    return [];
  }

  function barsOf(payload) {
    return rowsOf(payload).map(normalizeBar).filter(Boolean)
      .sort((left, right) => left.timestamp - right.timestamp);
  }

  function normalizeBar(row) {
    if (Array.isArray(row)) {
      return barOf(row[0], row[1], row[2], row[3], row[4], row[5], row[6]);
    }
    if (!row || typeof row !== "object") return null;
    const fields = Object.fromEntries(
      Object.entries(row).map(([key, value]) => [String(key).toLowerCase(), value]),
    );
    return barOf(
      first(fields, "timestamp", "datetime", "date", "time", "index"),
      first(fields, "open", "o"),
      first(fields, "high", "h"),
      first(fields, "low", "l"),
      first(fields, "close", "c"),
      first(fields, "volume", "vol", "v"),
      first(fields, "open_interest", "openinterest", "oi"),
    );
  }

  function first(value, ...keys) {
    for (const key of keys) if (value[key] !== undefined) return value[key];
    return undefined;
  }

  function barOf(rawTime, open, high, low, close, volume, openInterest) {
    const timestamp = timestampOf(rawTime);
    const values = [open, high, low, close].map(Number);
    if (!Number.isFinite(timestamp) || values.some(value => !Number.isFinite(value))) {
      return null;
    }
    return {
      timestamp,
      open: values[0], high: values[1], low: values[2], close: values[3],
      volume: finiteOrNull(volume), openInterest: finiteOrNull(openInterest),
    };
  }

  function timestampOf(value) {
    const numeric = Number(value);
    if (Number.isFinite(numeric)) return Math.abs(numeric) < 1e11 ? numeric * 1000 : numeric;
    const parsed = Date.parse(String(value || ""));
    return Number.isFinite(parsed) ? parsed : NaN;
  }

  function finiteOrNull(value) {
    if (value === null || value === undefined || value === "") return null;
    const numeric = Number(value);
    return Number.isFinite(numeric) ? numeric : null;
  }

  function optionsOf(context, payload, bars) {
    const t = value => context?.t?.(value) || value;
    const hasOI = bars.some(item => item.openInterest !== null);
    const title = [payload?.product || payload?.product_name || "", payload?.desc || ""]
      .filter(Boolean).join(" — ");
    const priceHeight = hasOI ? "50%" : "62%";
    const volumeTop = hasOI ? "55%" : "67%";
    const volumeHeight = hasOI ? "23%" : "31%";
    const yAxis = [
      axis(priceHeight, "0%", true),
      axis(volumeHeight, volumeTop, false),
    ];
    const series = [
      {
        type: "candlestick", name: payload?.product || payload?.product_name || t("价格"),
        data: bars.map(item => [item.timestamp, item.open, item.high, item.low, item.close]),
        color: "#e14d5b", upColor: "#18a572", lineColor: "#e14d5b",
        upLineColor: "#18a572", dataGrouping: {groupAll: true},
      },
      {
        type: "column", name: t("成交量"), yAxis: 1,
        data: bars.map(item => [item.timestamp, item.volume]),
        color: "#8aa4c8", dataGrouping: {approximation: "sum", groupAll: true},
      },
    ];
    if (hasOI) {
      yAxis.push(axis("17%", "82%", false));
      series.push({
        type: "line", name: t("持仓量"), yAxis: 2,
        data: bars.map(item => [item.timestamp, item.openInterest]),
        color: "#af52de", lineWidth: 1.4,
        dataGrouping: {approximation: "average", groupAll: true},
      });
    }
    return {
      chart: {
        animation: false, height: 650,
        panning: {enabled: true, type: "x"}, panKey: "shift",
        zooming: {type: "x", mouseWheel: {enabled: true, type: "x"}},
      },
      time: {useUTC: false},
      title: {text: title || null},
      subtitle: {text: [payload?.freq, `${bars.length} ${t("条数据")}`].filter(Boolean).join(" · ")},
      rangeSelector: {
        selected: 4,
        buttons: [
          {type: "day", count: 3, text: t("3天")},
          {type: "week", count: 1, text: t("1周")},
          {type: "month", count: 1, text: t("1月")},
          {type: "month", count: 3, text: t("3月")},
          {type: "year", count: 1, text: t("1年")},
          {type: "all", text: t("全部")},
        ],
      },
      xAxis: {type: "datetime", ordinal: true},
      yAxis,
      tooltip: {shared: true, split: false, valueDecimals: 2},
      navigator: {enabled: true},
      scrollbar: {enabled: true},
      plotOptions: {series: {animation: false, turboThreshold: 0}},
      credits: {enabled: false},
      series,
    };
  }

  function axis(height, top, resizable) {
    return {
      labels: {align: "right", x: -3}, title: {text: ""},
      height, top, offset: 0, lineWidth: 1,
      resize: {enabled: resizable},
    };
  }

  function empty(context, message) {
    if (window.FTUI?.empty) return FTUI.empty(context?.t?.(message) || message, "");
    const node = document.createElement("p"); node.textContent = context?.t?.(message) || message;
    return node;
  }

  window.FTPriceChart = Object.freeze({barsOf, render, timestampOf});
})();
