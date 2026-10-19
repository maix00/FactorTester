(() => {
  const DAY = 86400000;
  const eventArtifacts = ["order_detail_data", "fill_detail_data"];

  function first(row, keys) {
    return keys.map(key => row?.[key]).find(value => value !== null
      && value !== undefined && String(value).trim() !== "");
  }

  function identity(row) {
    const product = String(first(row, ["instrument", "product", "contract_uid"]) || "");
    const contractUID = String(first(row, ["contract_uid"]) || (
      /^[^|]+\|[^|]+\|[^|]+\|[^|]+$/.test(product) ? product : ""
    ));
    return {
      product,
      contractUID,
      strategy: String(first(row, ["strategy_id", "strategy_ref", "strategy"]) || ""),
      timestamp: window.FTPriceChart.timestampOf(first(row,
        ["timestamp", "submitted_at", "filled_at", "executed_at", "created_at"])),
    };
  }

  function artifactPath(state, artifact) {
    const item = state.artifactsByName.get(artifact);
    return `/api/jobs/${encodeURIComponent(state.options.jobID)}/artifacts/`
      + `${encodeURIComponent(item.name)}${state.options.artifactQuery || ""}`;
  }

  function eventFilters(selected) {
    const filters = {product: {
      fields: selected.contractUID ? ["contract_uid", "instrument", "product"]
        : ["instrument", "product"],
      values: [selected.contractUID || selected.product],
    }};
    if (selected.strategy) filters.strategy = {
      fields: ["strategy_id", "strategy_ref", "strategy"],
      values: [selected.strategy],
    };
    return filters;
  }

  async function loadEvents(context, state, selected, minimum, maximum, maxPoints) {
    const results = await Promise.all(eventArtifacts.filter(name => (
      state.artifactsByName.has(name)
    )).map(async name => {
      const source = window.FTJobArtifactQuery.timeSource(
        context, artifactPath(state, name), {mode: "time_rows", maxPoints},
      );
      const value = await source.load({min: minimum, max: maximum, maxPoints}, {
        filters: eventFilters(selected),
        fields: [
          "timestamp", "submitted_at", "filled_at", "executed_at", "created_at",
          "instrument", "product",
          "contract_uid", "strategy_id", "strategy_ref", "strategy",
          "order_id", "fill_id", "event_id", "event_type", "status",
          "side", "offset", "quantity", "requested_quantity", "filled_quantity",
          "price", "fill_price", "fee",
        ],
      });
      return {name, rows: value?.rows || [], sampling: value?.sampling || {}};
    }));
    const events = results.flatMap(({name, rows}) => rows.map((row, index) => ({
      artifact: name, row, index,
      timestamp: window.FTPriceChart.timestampOf(first(row,
        ["timestamp", "submitted_at", "filled_at", "executed_at", "created_at"])),
    }))).filter(item => Number.isFinite(item.timestamp))
      .sort((a, b) => a.timestamp - b.timestamp);
    return {events, sourceCount: results.reduce((total, item) => (
      total + Number(item.sampling.visible_rows || item.rows.length)
    ), 0)};
  }

  function nearestPrice(bars, timestamp) {
    if (!bars.length) return null;
    let nearest = bars[0];
    for (const bar of bars) {
      if (Math.abs(bar.timestamp - timestamp) < Math.abs(nearest.timestamp - timestamp)) {
        nearest = bar;
      }
    }
    return nearest.close;
  }

  function escapeHTML(value) {
    return String(value).replace(/[&<>"']/g, character => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[character]));
  }

  function markerSeries(events, bars, onSelect) {
    return [
      ["order", "订单", "#d97706", "diamond", item => item.artifact === "order_detail_data"],
      ["buy", "买入成交", "#16a34a", "triangle", item => item.artifact === "fill_detail_data"
        && /^(buy|long|b|买)/i.test(String(item.row.side || ""))],
      ["sell", "卖出成交", "#dc2626", "triangle-down", item => item.artifact === "fill_detail_data"
        && /^(sell|short|s|卖)/i.test(String(item.row.side || ""))],
      ["other", "其他成交", "#2563eb", "circle", item => item.artifact === "fill_detail_data"
        && !/^(buy|long|b|买|sell|short|s|卖)/i.test(String(item.row.side || ""))],
    ].map(([key, name, color, symbol, include]) => ({
      id: `asset-${key}`, type: "scatter", name, color, yAxis: 0,
      marker: {enabled: true, radius: 5, symbol, lineColor: "#fff", lineWidth: 1},
      dataGrouping: {enabled: false},
      data: events.filter(include).map(item => {
        const raw = first(item.row, ["fill_price", "price"]);
        const actual = item.artifact === "fill_detail_data" && raw != null
          ? Number(raw) : Number.NaN;
        return {
          x: item.timestamp,
          y: Number.isFinite(actual) ? actual : nearestPrice(bars, item.timestamp),
          custom: {item},
        };
      }).filter(point => point.y != null),
      point: {events: {click() { onSelect(this.options.custom.item); }}},
      tooltip: {pointFormatter() {
        const item = this.options.custom.item;
        const side = String(first(item.row, ["side", "offset", "status"]) || "");
        const quantity = String(first(item.row,
          ["filled_quantity", "quantity", "requested_quantity"]) || "");
        return `${name}: ${escapeHTML(side)} ${escapeHTML(quantity)}`
          + ` · ${Number(this.y).toLocaleString()}`;
      }},
    }));
  }

  function eventList(context, target, events, onSelect, onHover) {
    target.replaceChildren();
    if (!events.length) {
      const empty = document.createElement("p");
      empty.textContent = context.t("当前范围没有该合约的订单或成交");
      target.append(empty); return;
    }
    for (const item of events) {
      const row = item.row;
      const button = document.createElement("button");
      button.type = "button";
      button.className = "backtest-asset-event";
      const kind = item.artifact === "fill_detail_data" ? "成交" : "订单";
      button.textContent = [
        window.FTUI.formatDate(item.timestamp) || new Date(item.timestamp).toLocaleString(),
        context.t(kind), first(row, ["side", "offset", "status"]),
        first(row, ["filled_quantity", "quantity", "requested_quantity"]),
        first(row, ["fill_price", "price"]),
      ].filter(value => value != null && value !== "").join(" · ");
      button.addEventListener("click", () => onSelect(item));
      button.addEventListener("mouseenter", () => onHover(item));
      button.addEventListener("mouseleave", () => onHover(null));
      item.button = button;
      target.append(button);
    }
  }

  function open(context, state, row) {
    const selected = identity(row);
    if (!selected.product || !Number.isFinite(selected.timestamp)) return null;
    const dialog = window.FTBacktestAnalysisUI.dialog(
      context, "Asset Plot · 交易图", [selected.product, selected.strategy].filter(Boolean).join(" · "),
    );
    dialog.root.classList.add("backtest-asset-dialog");
    const note = document.createElement("p");
    note.className = "backtest-asset-note";
    note.textContent = context.t("价格来自当前行情源；标记来自本次 Job 的订单与成交。行情若更新，图上价格可能与回测时不同。");
    const chartMount = document.createElement("div");
    chartMount.className = "backtest-asset-chart";
    const list = document.createElement("div");
    list.className = "backtest-asset-events";
    dialog.body.append(note, chartMount, list);
    let generation = 0;
    let events = [];
    let chart = null;
    const select = item => {
      events.forEach(value => value.button?.classList.toggle("active", value === item));
      item.button?.scrollIntoView?.({block: "nearest"});
      const axis = chart?.xAxis?.[0];
      if (axis) axis.setExtremes(item.timestamp - DAY, item.timestamp + DAY);
    };
    const hover = item => {
      for (const series of chart?.series || []) {
        for (const point of series.points || []) {
          const active = item && point.options?.custom?.item === item;
          point.setState?.(active ? "hover" : "");
          if (active) chart.tooltip?.refresh?.(point);
        }
      }
      if (!item) chart?.tooltip?.hide?.();
    };
    const configuration = state.options.configuration || {};
    const request = configuration.configuration?.payload || configuration.payload
      || configuration;
    const settings = request.analyses?.backtest?.execution?.settings
      || request.backtest?.execution?.settings || request.execution?.settings || request;
    const frequency = String(settings.freq || settings.frequency || "DAY1");
    const priceRequest = {
      ...(selected.contractUID ? {contract_uid: selected.contractUID}
        : {product_name: selected.product}),
      freq: frequency, adjusted: false,
    };
    const load = async (minimum, maximum, maxPoints = 1200) => {
      const current = ++generation;
      const ranged = window.FTMarketData.rangeRequest(
        priceRequest, minimum, maximum, maxPoints,
      );
      const [price, matching] = await Promise.all([
        window.FTMarketData.prices(context, ranged, "server"),
        loadEvents(context, state, selected, minimum, maximum,
          Math.min(1200, maxPoints)),
      ]);
      if (dialog.root.open === false || current !== generation) return null;
      events = matching.events;
      eventList(context, list, events, select, hover);
      const sampling = matching.sourceCount > events.length
        ? ` · 事件展示 ${events.length}/${matching.sourceCount}` : "";
      note.textContent = context.t("价格来自当前行情源；标记来自本次 Job 的订单与成交。行情若更新，图上价格可能与回测时不同。")
        + ` · ${price.payload.data_source || context.t("自动行情源")}` + sampling;
      return {...price.payload, product: selected.product,
        freq: price.payload.freq || frequency,
        __assetEvents: events};
    };
    chartMount.append(window.FTUI.loading(context.t("正在读取行情与交易事件…")));
    const initialSpan = /^(MIN|HOUR)/i.test(frequency) ? 7 * DAY : 30 * DAY;
    load(selected.timestamp - initialSpan, selected.timestamp + initialSpan)
      .then(payload => {
        if (!payload) return;
        chart = window.FTPriceChart.render(context, chartMount, payload, {
          loadingText: context.t("正在读取当前时间范围…"),
          overlaySeries: (value, bars) => markerSeries(value.__assetEvents || [], bars, select),
          loadRange: (minimum, maximum, range) => load(minimum, maximum, range.maxPoints),
          onRangeError: error => { note.textContent = error.message || String(error); },
        });
      }).catch(error => {
        chartMount.replaceChildren();
        const message = document.createElement("p");
        message.textContent = error.message || String(error);
        chartMount.append(message);
      });
    dialog.root.addEventListener("close", () => {
      generation += 1;
      chartMount.__ftPriceChartObserver?.disconnect?.();
      chart?.destroy?.();
    });
    return dialog;
  }

  window.FTBacktestAssetPlot = Object.freeze({eventFilters, identity, markerSeries, open});
})();
