(() => {
  function render(context, target, payload, displayOptions = {}) {
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
    if (displayOptions.assetMode && highcharts.AST) {
      // The tooltip is built only from escaped event fields. Highcharts strips
      // disclosure elements unless explicitly allowed by its HTML sanitizer.
      for (const tag of ["details", "summary", "dl", "dt", "dd"]) {
        if (!highcharts.AST.allowedTags.includes(tag)) highcharts.AST.allowedTags.push(tag);
      }
      if (!highcharts.AST.allowedAttributes.includes("open")) {
        highcharts.AST.allowedAttributes.push("open");
      }
      for (const attribute of ["data-ft-event-index", "aria-pressed"]) {
        if (!highcharts.AST.allowedAttributes.includes(attribute)) {
          highcharts.AST.allowedAttributes.push(attribute);
        }
      }
    }
    target.__ftPriceChart?.destroy?.();
    target.__ftPriceChartObserver?.disconnect?.();
    target.classList?.add("interactive-price-chart");
    const chartOptions = optionsOf(context, payload, bars, displayOptions);
    window.TRHighchartsRangeLoader?.attach(chartOptions, {
      ...displayOptions,
      rangeOptions: incoming => optionsOf(context, incoming, barsOf(incoming), displayOptions),
    });
    const chart = highcharts.stockChart(target, chartOptions);
    target.__ftPriceChart = chart;
    chart._ftCompleteRange = chartOptions._ftCompleteRange || null;
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
    if (Number.isFinite(numeric)) {
      if (Math.abs(numeric) >= 1e18) return numeric / 1e6;
      if (Math.abs(numeric) >= 1e15) return numeric / 1e3;
      return Math.abs(numeric) < 1e11 ? numeric * 1000 : numeric;
    }
    const parsed = Date.parse(String(value || ""));
    return Number.isFinite(parsed) ? parsed : NaN;
  }

  function finiteOrNull(value) {
    if (value === null || value === undefined || value === "") return null;
    const numeric = Number(value);
    return Number.isFinite(numeric) ? numeric : null;
  }

  function tooltipNumber(value) {
    return value !== null && value !== undefined && value !== ""
      && Number.isFinite(Number(value)) ? Number(value).toLocaleString(
      undefined, {maximumFractionDigits: 6},
    ) : "—";
  }

  function pointLabel(context, label, value) {
    const translated = context?.t?.(label) || label;
    return `${translated}: <b>${tooltipNumber(value)}</b>`;
  }

  function escapeHTML(value) {
    return String(value).replace(/[&<>"']/g, character => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[character]));
  }

  function ohlcPointFormatter(context) {
    return function() {
      return [
        pointLabel(context, "开盘价", this.open),
        pointLabel(context, "最高价", this.high),
        pointLabel(context, "最低价", this.low),
        pointLabel(context, "收盘价", this.close),
      ].join("<br/>");
    };
  }

  function scalarPointFormatter(context, label) {
    return function() { return `${pointLabel(context, label, this.y)}<br/>`; };
  }

  function frequencyIntervalMs(frequency) {
    const match = /^(SEC|MIN|HOUR|DAY|WEEK)(\d+)$/i.exec(String(frequency || ""));
    if (!match) return undefined;
    const unit = {SEC: 1000, MIN: 60000, HOUR: 3600000,
      DAY: 86400000, WEEK: 604800000}[match[1].toUpperCase()];
    const count = Number(match[2]);
    return Number.isSafeInteger(count) && count > 0 ? unit * count : undefined;
  }

  function assetTooltipFormatter(context, bars, overlay, displayOptions,
    sourceIntervalMs) {
    const byTime = new Map(bars.map(bar => [bar.timestamp, bar]));
    const nearestBar = timestamp => {
      let low = 0; let high = bars.length;
      while (low < high) {
        const middle = (low + high) >>> 1;
        if (bars[middle].timestamp < timestamp) low = middle + 1;
        else high = middle;
      }
      const next = bars[low]; const previous = bars[low - 1];
      if (!next) return previous;
      if (!previous) return next;
      return timestamp - previous.timestamp <= next.timestamp - timestamp
        ? previous : next;
    };
    const eventsByTime = new Map();
    for (const series of overlay) {
      for (const point of series.data || []) {
        if (point?.custom?.items?.length) {
          eventsByTime.set(point.x, [
            ...(eventsByTime.get(point.x) || []), ...point.custom.items,
          ]);
        }
      }
    }
    return function() {
      const timestamp = Number(this.x ?? this.point?.x ?? this.points?.[0]?.point?.x);
      if (typeof displayOptions.tooltipActiveTime === "function"
        && timestamp !== displayOptions.tooltipActiveTime()) return false;
      const shared = this.points || [];
      const plotted = type => shared.find(item => item.point?.series?.type === type)?.point;
      const candle = plotted("candlestick");
      const volume = plotted("column");
      const interest = plotted("line");
      const nearby = !candle && Number.isFinite(sourceIntervalMs)
        ? nearestBar(timestamp) : null;
      const bar = byTime.get(timestamp) || (candle && {
        open: candle.open, high: candle.high, low: candle.low, close: candle.close,
        volume: volume?.y, openInterest: interest?.y,
      }) || (nearby && Math.abs(nearby.timestamp - timestamp) <= sourceIntervalMs
        ? nearby : null);
      if (!bar) return false;
      const time = new Date(timestamp).toLocaleString(localeTag(context));
      const lines = [
        `<strong>${time}</strong>`,
        pointLabel(context, "开盘价", bar.open),
        pointLabel(context, "最高价", bar.high),
        pointLabel(context, "最低价", bar.low),
        pointLabel(context, "收盘价", bar.close),
        pointLabel(context, "成交量", bar.volume),
        pointLabel(context, "持仓量", bar.openInterest),
      ];
      const events = typeof displayOptions.tooltipEventItems === "function"
        ? displayOptions.tooltipEventItems(timestamp) : eventsByTime.get(timestamp);
      displayOptions.onTooltipEvents?.(events || []);
      if (events?.length) {
        const cards = events.map((item, index) => {
          const fields = displayOptions.eventTooltipFields?.(item) || [];
          const kind = item.artifact === "fill_detail_data" ? "成交" : "订单";
          const rawPrice = item.artifact === "fill_detail_data"
            ? item.row?.fill_price ?? item.row?.price : null;
          const hasPrice = rawPrice !== null && rawPrice !== undefined
            && rawPrice !== "" && Number.isFinite(Number(rawPrice));
          const selected = hasPrice && displayOptions.isPriceSelected?.(item);
          return `<details class="asset-tooltip-event" ${events.length === 1 || index === 0 ? "open" : ""}>`
            + `<summary>${escapeHTML(context?.t?.(kind) || kind)} ${index + 1}`
            + ` · ${escapeHTML(item.row?.fill_id || item.row?.order_id || item.row?.event_id || "")}</summary>`
            + `<dl>${fields.map(([label, value]) => `<dt>${escapeHTML(context?.t?.(label) || label)}</dt>`
              + `<dd>${escapeHTML(value)}</dd>`).join("")}</dl>`
            + (hasPrice ? `<button type="button" class="asset-tooltip-price-toggle"`
              + ` data-ft-event-index="${index}" aria-pressed="${selected ? "true" : "false"}">`
              + `${selected ? "移除价格线" : "显示价格线"} · ${escapeHTML(tooltipNumber(rawPrice))}</button>` : "")
            + `</details>`;
        });
        lines.push(`<div class="asset-tooltip-events"><strong>${escapeHTML(
          context?.t?.("交易事件") || "交易事件")}: ${events.length} 笔</strong>`
          + cards.join("") + `</div>`);
      }
      return lines.join("<br/>");
    };
  }

  function localeTag(context) {
    const documentLocale = typeof document !== "undefined"
      ? document.documentElement?.lang : "";
    const value = String(
      context?.locale || documentLocale || context?.languagePreference || "zh-Hans",
    ).toLowerCase();
    return value.startsWith("en") ? "en-US" : "zh-CN";
  }

  function dateLabelFormatter(context) {
    const locale = localeTag(context);
    return function() {
      const timestamp = Number(this.value);
      if (!Number.isFinite(timestamp)) return String(this.value ?? "");
      const span = Number(this.axis?.max) - Number(this.axis?.min);
      const options = Number.isFinite(span) && span <= 86400000
        ? {hour: "2-digit", minute: "2-digit", hour12: false}
        : Number.isFinite(span) && span <= 3 * 86400000
          ? {month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false}
        : {year: "numeric", month: "short", day: "numeric"};
      try {
        return new Intl.DateTimeFormat(locale, options).format(new Date(timestamp));
      } catch (_) {
        return new Date(timestamp).toISOString().slice(0, 16).replace("T", " ");
      }
    };
  }

  function optionsOf(context, payload, bars, displayOptions = {}) {
    const t = value => context?.t?.(value) || value;
    const hasOI = bars.some(item => item.openInterest !== null);
    const eventLane = displayOptions.eventLane === true;
    const orderTimeline = typeof displayOptions.orderTimeline === "function"
      ? displayOptions.orderTimeline(payload) : null;
    const hasOrders = Boolean(orderTimeline);
    const title = [payload?.product || payload?.product_name || "", payload?.desc || ""]
      .filter(Boolean).join(" — ");
    const priceHeight = hasOrders ? (hasOI ? 245 : 300)
      : hasOI ? (eventLane ? "42%" : "50%") : (eventLane ? "54%" : "62%");
    const volumeTop = hasOrders ? (hasOI ? 260 : 315) : hasOI ? "55%" : "67%";
    const volumeHeight = hasOrders ? (hasOI ? 80 : 105) : hasOI ? "23%" : "31%";
    const yAxis = [
      {...axis(priceHeight, eventLane ? "8%" : "0%", true),
        ...(displayOptions.assetMode ? {minPadding: 0.1, maxPadding: 0.1} : {})},
      axis(volumeHeight, volumeTop, false),
    ];
    const series = [
      {
        type: "candlestick", name: payload?.product || payload?.product_name || t("价格"),
        data: bars.map(item => [item.timestamp, item.open, item.high, item.low, item.close]),
        color: "#e14d5b", upColor: "#18a572", lineColor: "#e14d5b",
        upLineColor: "#18a572", dataGrouping: {
          enabled: !displayOptions.preserveSourceBars, groupAll: true,
        },
        tooltip: {pointFormatter: ohlcPointFormatter(context)},
        ...(typeof displayOptions.onMarketClick === "function"
          ? {point: {events: {click() { displayOptions.onMarketClick(this); }}}} : {}),
      },
      {
        type: "column", name: t("成交量"), yAxis: 1,
        data: bars.map(item => [item.timestamp, item.volume]),
        color: "#8aa4c8", dataGrouping: {
          enabled: !displayOptions.preserveSourceBars,
          approximation: "sum", groupAll: true,
        },
        tooltip: {pointFormatter: scalarPointFormatter(context, "成交量")},
      },
    ];
    if (hasOI) {
      yAxis.push(axis(hasOrders ? 60 : "17%", hasOrders ? 355 : "82%", false));
      series.push({
        type: "line", name: t("持仓量"), yAxis: 2,
        data: bars.map(item => [item.timestamp, item.openInterest]),
        color: "#af52de", lineWidth: 1.4,
        dataGrouping: {enabled: !displayOptions.preserveSourceBars,
          approximation: "average", groupAll: true},
        tooltip: {pointFormatter: scalarPointFormatter(context, "持仓量")},
      });
    }
    if (eventLane) yAxis.push({
      ...axis("6%", "0%", false), min: 0,
      labels: {enabled: false}, lineWidth: 0, gridLineWidth: 0,
      startOnTick: false, endOnTick: false,
    });
    if (hasOrders) {
      const rows = orderTimeline.rows || [];
      yAxis.push({id: "asset-order-axis", ...axis(
        Math.max(36, rows.length * 28 + 8), hasOI ? 430 : 440, false),
      min: -0.5, max: Math.max(0.5, rows.length - 0.5),
      tickPositions: rows.map((_, index) => index),
      labels: {align: "right", x: -4, style: {fontSize: "10px"},
        formatter() {
          const row = rows[rows.length - 1 - Number(this.value)];
          return row ? String(row[0]).slice(-12) : "";
        }},
      title: {text: null}, gridLineWidth: 1,
      startOnTick: false, endOnTick: false});
      series.push(...orderTimeline.series);
    }
    const overlay = typeof displayOptions.overlaySeries === "function"
      ? displayOptions.overlaySeries(payload, bars) : [];
    if (Array.isArray(overlay)) series.push(...overlay);
    return {
      _ftCompleteRange: Number(payload?.count) === Number(payload?.returned_count)
        && Number(payload?.count) === bars.length
        && (!displayOptions.assetMode || payload?.__ftEventsComplete === true)
        ? [bars[0]?.timestamp, bars[bars.length - 1]?.timestamp] : null,
      chart: {
        animation: false, height: hasOrders ? 660 + Math.max(1,
          orderTimeline.rows.length) * 28 : 650,
        panning: {enabled: true, type: "x"}, panKey: "shift",
        zooming: {type: "x", mouseWheel: {enabled: true, type: "x"}},
      },
      time: {useUTC: false},
      title: {text: title || null},
      subtitle: {text: [payload?.freq, `${bars.length} ${t("条数据")}`].filter(Boolean).join(" · ")},
      rangeSelector: {
        selected: 4, allButtonsEnabled: true,
        buttons: [
          {type: "day", count: 3, text: t("3天")},
          {type: "week", count: 1, text: t("1周")},
          {type: "month", count: 1, text: t("1月")},
          {type: "month", count: 3, text: t("3月")},
          {type: "year", count: 1, text: t("1年")},
          {type: "all", text: t("全部")},
        ],
      },
      xAxis: {
        type: "datetime", ordinal: true,
        minRange: frequencyIntervalMs(payload?.freq),
        tickPixelInterval: 140,
        labels: {formatter: dateLabelFormatter(context),
          autoRotation: [-45], style: {whiteSpace: "nowrap"}},
      },
      yAxis,
      tooltip: {shared: true, split: false, valueDecimals: 2,
        ...(eventLane || displayOptions.assetMode
          ? {useHTML: true, stickOnContact: true, hideDelay: 400,
            formatter: assetTooltipFormatter(context, bars, overlay, displayOptions,
              frequencyIntervalMs(payload?.freq))} : {})},
      navigator: {enabled: true, adaptToUpdatedData: false},
      scrollbar: {enabled: true},
      plotOptions: {series: {
        animation: false, turboThreshold: 0,
        ...(displayOptions.keepOtherSeriesVisible ? {states: {inactive: {opacity: 1}}} : {}),
      }},
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

  window.FTPriceChart = Object.freeze({
    barsOf, dateLabelFormatter, ohlcPointFormatter, render,
    scalarPointFormatter, timestampOf,
  });
})();
