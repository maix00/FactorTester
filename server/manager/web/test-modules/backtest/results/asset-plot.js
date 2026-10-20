(() => {
  const DAY = 86400000;
  const eventFields = [
    "timestamp", "submitted_at", "filled_at", "executed_at", "created_at",
    "instrument", "product", "contract_uid", "strategy_id", "strategy_ref",
    "strategy", "order_id", "fill_id", "event_id", "event_type", "status",
    "side", "offset", "quantity", "requested_quantity", "filled_quantity",
    "price", "fill_price", "fee", "active_leaves", "terminal_unfilled",
    "cash_before", "cash_after", "cash_change", "margin_before", "margin_after",
    "margin_change", "account_currency", "position_before", "position_after",
    "account_id", "account_ref", "account", "ledger_id", "ledger",
    "cash_pool_id", "cash_pool", "pool_id", "pool", "lifecycle",
  ];
  const productFields = ["contract_uid", "instrument", "product"];
  const strategyFields = ["strategy_id", "strategy_ref", "strategy"];
  const accountFields = ["account_id", "account_ref", "account", "ledger_id", "ledger"];
  const poolFields = ["cash_pool_id", "cash_pool", "pool_id", "pool"];
  const selectionMode = selected => selected.filterMode
    || (selected.cashPool ? "cash_pool" : selected.account ? "account" : "strategy");

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
      account: String(first(row, accountFields) || ""),
      cashPool: String(first(row, poolFields) || ""),
      timestamp: window.FTPriceChart.timestampOf(first(row,
        ["timestamp", "submitted_at", "filled_at", "executed_at", "created_at"])),
    };
  }

  function artifactPath(state, artifact) {
    const item = state.artifactsByName.get(artifact);
    return `/api/jobs/${encodeURIComponent(state.options.jobID)}/artifacts/`
      + `${encodeURIComponent(item.name)}${state.options.artifactQuery || ""}`;
  }

  function eventFilters(selected, {dimensions = true} = {}) {
    const filters = {product: {
      fields: selected.contractUID ? productFields
        : ["instrument", "product"],
      values: [selected.contractUID || selected.product],
    }};
    if (selected.strategy) filters.strategy = {
      fields: strategyFields,
      values: [selected.strategy],
    };
    if (dimensions && selectionMode(selected) === "account" && selected.account) filters.account = {
      fields: accountFields, values: [selected.account],
    };
    if (dimensions && selectionMode(selected) === "cash_pool" && selected.cashPool) {
      filters.cash_pool = {fields: poolFields, values: [selected.cashPool]};
    }
    return filters;
  }

  function productKey(selected) {
    return String(selected?.contractUID || selected?.product || "");
  }

  function matchesSelection(row, selected, orderIDs = null) {
    const orderID = String(row?.order_id || "");
    const rowProduct = productKey(identity(row));
    if ((!rowProduct || rowProduct !== productKey(selected)) && !orderIDs?.has(orderID)) return false;
    if (selected.strategy && first(row, strategyFields) !== selected.strategy) return false;
    if (selectionMode(selected) === "account" && selected.account
        && first(row, accountFields) !== selected.account) return false;
    if (selectionMode(selected) === "cash_pool" && selected.cashPool
        && first(row, poolFields) !== selected.cashPool) return false;
    return true;
  }

  function orderFacts(order) {
    const lifecycle = Array.isArray(order.lifecycle) ? order.lifecycle : [];
    const facts = lifecycle.flatMap((fact, index) => {
      const timestamp = window.FTPriceChart.timestampOf(fact.timestamp);
      if (!Number.isFinite(timestamp)) return [];
      return [{artifact: "order_lifecycle", order, index, timestamp,
        row: {...order, ...fact, status: fact.status || "", timestamp}}];
    });
    if (facts.length) return facts;
    // Old Jobs have a final snapshot but no retained phase facts. Mark the
    // submitted-time row as a snapshot, never as a dated terminal transition.
    const timestamp = window.FTPriceChart.timestampOf(first(order,
      ["submitted_at", "timestamp", "created_at"]));
    return Number.isFinite(timestamp) ? [{artifact: "order_detail_data", order,
      row: {...order, kind: "legacy_snapshot"}, index: 0, timestamp}] : [];
  }

  async function loadEvents(context, state, selected, minimum, maximum, maxPoints) {
    const query = async (name, filters) => {
      const source = window.FTJobArtifactQuery.timeSource(
        context, artifactPath(state, name), {mode: "time_rows", maxPoints},
      );
      const value = await source.load({min: minimum, max: maximum, maxPoints}, {
        filters, fields: eventFields,
      });
      return {name, rows: value?.rows || [], sampling: value?.sampling || {}};
    };
    const hasFills = state.artifactsByName.has("fill_detail_data");
    const [orders, productFills] = await Promise.all([
      state.artifactsByName.has("order_detail_data")
        ? query("order_detail_data", eventFilters(selected, {dimensions: false})) : null,
      hasFills ? query("fill_detail_data", eventFilters(selected)) : null,
    ]);
    if (orders) orders.rows = orders.rows.filter(row => (
      productKey(identity(row)) === productKey(selected)
      && (!selected.strategy || first(row, strategyFields) === selected.strategy)
    ));
    const results = orders ? [orders] : [];
    if (hasFills) {
      // Native fill rows identify their contract through order_id, not product.
      // Query both representations so older and newer Job artifacts work alike.
      const identifiers = [...new Set((orders?.rows || [])
        .map(row => String(row.order_id || "")).filter(Boolean))];
      const groups = [];
      for (let index = 0; index < identifiers.length; index += 256) {
        groups.push(identifiers.slice(index, index + 256));
      }
      const fillResults = await Promise.all([
        productFills,
        ...groups.map(values => query("fill_detail_data", {
          order: {fields: ["order_id"], values},
          ...(selectionMode(selected) === "account" && selected.account
            ? {account: {fields: accountFields, values: [selected.account]}} : {}),
          ...(selectionMode(selected) === "cash_pool" && selected.cashPool
            ? {cash_pool: {fields: poolFields, values: [selected.cashPool]}} : {}),
        })),
      ]);
      const seen = new Set();
      const orderIDs = new Set(identifiers);
      const rows = fillResults.flatMap(result => result.rows)
        .filter(row => matchesSelection(row, selected, orderIDs)).filter(row => {
        const key = String(row.fill_id || row.event_id || JSON.stringify(row));
        if (seen.has(key)) return false;
        seen.add(key); return true;
      });
      results.push({name: "fill_detail_data", rows, sampling: {
        omitted_rows: fillResults.reduce((count, result) => (
          count + Math.max(0, Number(result.sampling.visible_rows
            || result.rows.length) - result.rows.length)
        ), 0),
      }});
    }
    const orderByID = new Map((orders?.rows || []).filter(row => row.order_id)
      .map(row => [String(row.order_id), row]));
    const matchingFillIDs = new Set(results.filter(result => result.name === "fill_detail_data")
      .flatMap(result => result.rows).map(row => String(row.order_id || "")).filter(Boolean));
    const visibleOrders = (orders?.rows || []).filter(row => {
      if (selectionMode(selected) === "account" && selected.account) {
        return first(row, accountFields) === selected.account
          || matchingFillIDs.has(String(row.order_id || ""));
      }
      if (selectionMode(selected) === "cash_pool" && selected.cashPool) {
        return first(row, poolFields) === selected.cashPool
          || matchingFillIDs.has(String(row.order_id || ""));
      }
      return true;
    });
    const events = [
      ...visibleOrders.flatMap(orderFacts),
      ...results.filter(result => result.name === "fill_detail_data")
        .flatMap(({rows}) => rows.map((row, index) => ({
          artifact: "fill_detail_data", row, index,
          order: orderByID.get(String(row.order_id || "")),
          timestamp: window.FTPriceChart.timestampOf(first(row,
            ["timestamp", "filled_at", "executed_at", "created_at"])),
        }))),
    ].filter(item => Number.isFinite(item.timestamp)
      && item.timestamp >= minimum && item.timestamp <= maximum)
      .sort((a, b) => a.timestamp - b.timestamp);
    const omittedOrders = orders ? Math.max(0,
      Number(orders.sampling.visible_rows || orders.rows.length) - orders.rows.length) : 0;
    return {events, sourceCount: events.length + omittedOrders
      + Number(results.find(item => item.name === "fill_detail_data")
        ?.sampling.omitted_rows || 0)};
  }

  function nearestPrice(bars, timestamp) {
    return nearestBar(bars, timestamp)?.close ?? null;
  }

  function nearestBar(bars, timestamp) {
    if (!bars.length) return null;
    let nearest = bars[0];
    for (const bar of bars) {
      if (Math.abs(bar.timestamp - timestamp) < Math.abs(nearest.timestamp - timestamp)) {
        nearest = bar;
      }
    }
    return nearest;
  }

  function escapeHTML(value) {
    return String(value).replace(/[&<>"']/g, character => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[character]));
  }

  function number(value) {
    if (value == null || value === "") return "—";
    const numeric = Number(value);
    return Number.isFinite(numeric) ? numeric.toLocaleString() : String(value);
  }

  function change(row, before, after) {
    if (row?.[before] == null || row?.[after] == null) return "未记录";
    return `${number(row[before])} → ${number(row[after])}`;
  }

  function eventDetail(item) {
    return eventFieldsFor(item).map(([label, value]) => `${label} ${value}`).join(" · ");
  }

  function stageLabel(item) {
    if (item.artifact === "fill_detail_data") return "成交执行";
    const kind = String(item.row.kind || "");
    if (kind === "submitted") return "订单建立";
    if (kind === "attempt") return "撮合尝试";
    if (kind === "action") return ({submit: "提交请求", cancel: "撤单请求",
      replace: "改单请求"})[String(item.row.action || "")] || "订单请求";
    return "历史订单快照";
  }

  function eventFieldsFor(item) {
    const row = item.row;
    const isFill = item.artifact === "fill_detail_data";
    const side = first(row, ["side", "offset"]) || "—";
    const amount = first(row, isFill ? ["quantity", "filled_quantity"]
      : ["requested_quantity", "quantity"]);
    const order = item.order || row;
    const currency = String(first(row, ["account_currency", "currency"]) || "");
    const remaining = isFill ? first(row, ["active_leaves"]) : null;
    const parts = [
      ["阶段", stageLabel(item)],
      ["事件 ID", first(row, ["fill_id", "attempt_id", "request_id",
        "order_id", "event_id"]) || "未记录"],
      ["时间", window.FTUI?.formatDate?.(item.timestamp)
        || new Date(item.timestamp).toLocaleString()],
      ["方向", side],
      ["数量", number(amount)],
      ["价格", number(first(row, ["fill_price", "price"]))],
    ];
    const strategy = first(row, strategyFields) || first(order, strategyFields);
    const account = first(row, accountFields) || first(order, accountFields);
    if (isFill && order?.order_id) {
      parts.push(["关联订单", order.order_id]);
      const submitted = first(order, ["submitted_at", "timestamp", "created_at"]);
      const submittedAt = window.FTPriceChart.timestampOf(submitted);
      if (Number.isFinite(submittedAt)) parts.push(["下单时间",
        window.FTUI?.formatDate?.(submittedAt) || new Date(submittedAt).toLocaleString()]);
    }
    if (strategy) parts.push(["策略", strategy]);
    if (account) parts.push(["账本", account]);
    const pool = first(row, poolFields) || first(order, poolFields);
    if (pool) parts.push(["资金池", pool]);
    if (row.status) parts.push(["状态", row.status]);
    if (!isFill && order?.status) parts.push(["订单最终状态", order.status]);
    if (isFill) parts.push(["手续费", row.fee != null
      ? `${number(row.fee)} ${currency}`.trim() : "未记录"]);
    if (remaining != null) parts.push(["事件后剩余", number(remaining)]);
    else if (order?.active_leaves != null) {
      parts.push(["订单最终剩余", number(order.active_leaves)]);
    }
    if (order?.terminal_unfilled != null) {
      parts.push(["终止未成交", number(order.terminal_unfilled)]);
    }
    if (row.cash_before != null && row.cash_after != null) {
      parts.push(["现金", `${change(row, "cash_before", "cash_after")} ${currency}`.trim()]);
    }
    if (row.margin_before != null && row.margin_after != null
        && (Number(row.margin_before) !== 0 || Number(row.margin_after) !== 0)) {
      parts.push(["账本保证金", change(row, "margin_before", "margin_after")]);
    }
    if (row.position_before != null && row.position_after != null) {
      parts.push(["持仓", change(row, "position_before", "position_after")]);
    }
    return parts;
  }

  function chartEvent(item) {
    const rawPrice = item.artifact === "fill_detail_data"
      ? first(item.row, ["fill_price", "price"]) : null;
    const price = rawPrice == null ? null : Number(rawPrice);
    return {
      timestamp: item.timestamp,
      artifact: item.artifact,
      orderID: String(first(item.row, ["order_id"])
        || first(item.order, ["order_id"]) || ""),
      side: String(first(item.row, ["side"]) || ""),
      stage: stageLabel(item),
      id: String(first(item.row, ["fill_id", "attempt_id", "request_id",
        "order_id", "event_id"]) || "未记录 ID"),
      fillPrice: price !== null && Number.isFinite(price) ? price : null,
      fields: eventFieldsFor(item).map(([label, value]) => [label, String(value)]),
      raw: item,
    };
  }

  function eventInspector(context, items, allEvents = []) {
    const panel = document.createElement("section");
    panel.className = "backtest-asset-inspector";
    panel.setAttribute("aria-label", context.t("交易事件详情"));
    const heading = document.createElement("h4");
    heading.textContent = context.t(`交易事件详情 · ${items.length} 笔`);
    panel.append(heading);
    items.forEach((item, index) => {
      const card = document.createElement("details");
      card.className = "backtest-asset-event-card";
      card.open = items.length === 1 || index === 0;
      const summary = document.createElement("summary");
      const id = first(item.row, ["fill_id", "attempt_id", "request_id",
        "order_id", "event_id"]) || "未记录 ID";
      summary.textContent = `${context.t(stageLabel(item))} ${index + 1} · ${id}`;
      const fields = document.createElement("dl");
      fields.className = "backtest-asset-event-fields";
      eventFieldsFor(item).forEach(([label, value]) => {
        const name = document.createElement("dt");
        name.textContent = context.t(label);
        const content = document.createElement("dd");
        content.textContent = String(value);
        fields.append(name, content);
      });
      card.append(summary, fields);
      panel.append(card);
    });
    const orderIDs = [...new Set(items.map(item => String(item.row.order_id
      || item.order?.order_id || "")).filter(Boolean))];
    for (const orderID of orderIDs) {
      const related = allEvents.filter(item => String(item.row.order_id
        || item.order?.order_id || "") === orderID);
      const order = related.find(item => item.order)?.order;
      const flow = document.createElement("section");
      flow.className = "backtest-asset-order-flow";
      const title = document.createElement("h5");
      title.textContent = context.t(`订单流 · ${orderID}`);
      const timeline = document.createElement("ol");
      related.forEach(item => {
        const step = document.createElement("li");
        const time = window.FTUI?.formatDate?.(item.timestamp)
          || new Date(item.timestamp).toLocaleString();
        const amount = first(item.row, item.artifact === "fill_detail_data"
          ? ["quantity", "filled_quantity"] : ["requested_quantity", "quantity"]);
        step.textContent = `${time} · ${context.t(stageLabel(item))}`
          + (amount == null ? "" : ` · ${context.t("数量")} ${number(amount)}`);
        timeline.append(step);
      });
      if (order?.status) {
        const final = document.createElement("li");
        final.textContent = `${context.t("最终快照")} · ${order.status}`
          + (order.terminal_unfilled == null ? ""
            : ` · ${context.t("终止未成交")} ${number(order.terminal_unfilled)}`)
          + ` · ${context.t("状态变更时间未单独记录")}`;
        timeline.append(final);
      }
      const availability = document.createElement("p");
      availability.textContent = context.t("本任务未记录独立审核事件或逐档订单簿；无法展示审核通过时间、盘口深度或排队位置。撮合尝试不等于交易所审核通过。");
      flow.append(title, timeline, availability);
      panel.append(flow);
    }
    return panel;
  }

  function eventGroupKey(item, price) {
    // Preserve exact event time; different prices at the same instant stay separate.
    return `${item.timestamp}\u0000${price}`;
  }

  function groupedPoints(events, bars) {
    const groups = new Map();
    for (const item of events) {
      const raw = first(item.row, ["fill_price", "price"]);
      const actual = raw != null ? Number(raw) : Number.NaN;
      const price = Number.isFinite(actual) ? actual : nearestPrice(bars, item.timestamp);
      if (price == null) continue;
      const key = eventGroupKey(item, price);
      if (!groups.has(key)) groups.set(key, {x: item.timestamp, y: price, items: []});
      groups.get(key).items.push(item);
    }
    return [...groups.values()];
  }

  function markerSeries(events, bars, onSelect) {
    // Only executions belong on the price plot. Symbols sit outside the
    // wick; recorded execution prices are shown separately on selection.
    const groups = new Map();
    for (const item of events) {
      const bar = nearestBar(bars, item.timestamp);
      if (!bar) continue;
      if (!groups.has(bar.timestamp)) groups.set(bar.timestamp, {bar, items: []});
      groups.get(bar.timestamp).items.push(item);
    }
    const kinds = [
      ["buy", "买入成交", "#16a34a", "triangle", item => item.artifact === "fill_detail_data"
        && /^(buy|long|b|买)/i.test(String(item.row.side || "")), -1],
      ["sell", "卖出成交", "#dc2626", "triangle-down", item => item.artifact === "fill_detail_data"
        && /^(sell|short|s|卖)/i.test(String(item.row.side || "")), 1],
      ["other", "其他成交", "#2563eb", "circle", item => item.artifact === "fill_detail_data"
        && !/^(buy|long|b|买|sell|short|s|卖)/i.test(String(item.row.side || "")), -2],
    ];
    return kinds.map(([key, name, color, symbol, include, direction]) => ({
      id: `asset-${key}`, type: "scatter", name, color,
      yAxis: 0, zIndex: 5,
      marker: {enabled: true, radius: 4, symbol, lineColor: "#fff", lineWidth: 1},
      dataLabels: {enabled: false},
      dataGrouping: {enabled: false},
      data: [...groups.values()].map(group => {
        const items = group.items.filter(include);
        if (!items.length) return null;
        const bar = group.bar;
        // The price value only anchors the point to the price axis. Its final
        // position is translated in pixels, so a wide y-range cannot shrink
        // the visible gap between the symbol and neighboring candles.
        const y = direction > 0 ? bar.high : bar.low;
        return {x: bar.timestamp, y, custom: {items, bar}};
      }).filter(Boolean),
      events: {afterTranslate() {
        const candles = this.chart.series[0]?.points || [];
        for (const point of this.points) {
          if (!Number.isFinite(point.plotX)) continue;
          const neighbors = candles.filter(candle => Number.isFinite(candle.plotX)
            && Math.abs(candle.plotX - point.plotX) <= 10);
          if (!neighbors.length) continue;
          const edges = neighbors.map(candle => direction > 0
            ? candle.plotHigh : candle.plotLow).filter(Number.isFinite);
          if (!edges.length) continue;
          const edge = direction > 0 ? Math.min(...edges) : Math.max(...edges);
          const distance = 10 + (Math.abs(direction) - 1) * 14;
          point.plotY = edge + (direction > 0 ? -distance : distance);
        }
      }},
      point: {events: {click() { onSelect(this.options.custom.items, this); }}},
      tooltip: {pointFormatter() {
        const items = this.options.custom.items;
        const bar = this.options.custom.bar;
        const prices = [...new Set(items.map(item => first(item.row,
          ["fill_price", "price"])).filter(value => value != null)
          .map(Number).filter(Number.isFinite))];
        return `<strong>${escapeHTML(name)} · ${items.length} 笔</strong><br>`
          + `${escapeHTML("开 / 高 / 低 / 收")} ${[bar.open, bar.high, bar.low,
            bar.close].map(number).join(" / ")}<br>`
          + `${escapeHTML("成交量")} ${escapeHTML(number(bar.volume))}<br>`
          + `${escapeHTML("持仓量")} ${escapeHTML(number(bar.openInterest))}<br>`
          + (prices.length ? `事件价格 ${escapeHTML(prices.map(number).join("、"))}<br>` : "")
          + "点击查看逐笔详情";
      }},
    }));
  }

  function orderTimeline(context, events, minimum, maximum, onSelect,
    {limit = 10} = {}) {
    const orders = new Map();
    for (const item of events) {
      if (item.timestamp < minimum || item.timestamp > maximum) continue;
      const id = String(item.row.order_id || item.order?.order_id || "");
      if (!id) continue;
      if (!orders.has(id)) orders.set(id, []);
      orders.get(id).push(item);
    }
    const ordered = [...orders].sort((left, right) => (
      Math.max(...right[1].map(item => item.timestamp))
      - Math.max(...left[1].map(item => item.timestamp))
    ));
    const shownCount = Math.min(Math.max(1, limit), ordered.length);
    const rows = ordered.slice(0, shownCount);
    const series = [];
    const nodes = [];
    for (const [index, [id, items]] of rows.entries()) {
      const y = shownCount - index - 1;
      const times = [...new Set(items.map(item => item.timestamp))].sort((a, b) => a - b);
      series.push({id: `asset-order-line-${id}`, type: "line", name: id,
        yAxis: "asset-order-axis", data: times.map(time => [time, y]),
        color: "#8893a5", lineWidth: 2, marker: {enabled: false},
        enableMouseTracking: false, showInLegend: false,
        dataGrouping: {enabled: false}});
      for (const time of times) {
        const group = items.filter(item => item.timestamp === time);
        const item = group[0];
        const phase = item.artifact === "fill_detail_data" ? "fill"
          : item.row.kind === "attempt" ? "attempt"
            : item.row.action === "replace" ? "update"
              : item.row.action === "cancel" ? "cancel" : "submit";
        nodes.push({x: time, y,
          marker: {symbol: group.length > 1 ? "diamond" : ({fill: "circle", attempt: "square",
            update: "diamond", cancel: "triangle-down", submit: "circle"})[phase],
          radius: group.length > 1 ? 6 : 4,
          fillColor: group.length > 1 ? "#64748b" : ({fill: "#16a34a", attempt: "#d97706",
            update: "#2563eb", cancel: "#dc2626", submit: "#fff"})[phase],
          lineColor: group.length > 1 ? "#64748b" : ({fill: "#16a34a", attempt: "#d97706",
            update: "#2563eb", cancel: "#dc2626", submit: "#64748b"})[phase]},
          custom: {items: group, orderID: id,
          phase}});
      }
    }
    series.push({id: "asset-order-nodes", type: "scatter",
      name: context.t("订单变化"), yAxis: "asset-order-axis",
      data: nodes.sort((left, right) => left.x - right.x),
      dataGrouping: {enabled: false}, showInLegend: false,
      marker: {symbol: "circle", radius: 4, lineWidth: 1,
        lineColor: "#64748b", fillColor: "#fff"},
      dataLabels: {enabled: false},
      point: {events: {click() { onSelect(this.custom.items, this); }}},
      tooltip: {enabled: false}});
    return {rows, total: ordered.length, series};
  }

  function tradePriceLines(chart, items) {
    if (!chart?.yAxis?.[0]) return;
    for (let index = 0; index < (chart._ftTradePriceLineCount || 0); index += 1) {
      chart.yAxis[0].removePlotLine(`asset-trade-price-${index}`);
    }
    const prices = [...new Set(items.filter(item => item.artifact === "fill_detail_data")
      .map(item => first(item.row, ["fill_price", "price"]))
      .filter(value => value != null && value !== "")
      .map(Number)
      .filter(Number.isFinite))];
    chart._ftTradePriceLineCount = prices.length;
    prices.forEach((price, index) => {
      chart.yAxis[0].addPlotLine({
        id: `asset-trade-price-${index}`, value: price,
        color: "#2563eb", width: 1, dashStyle: "ShortDash", zIndex: 1,
        label: {text: `成交价 ${number(price)}`, align: "right", x: -8,
          style: {color: "#2563eb", fontSize: "11px"}},
      });
    });
  }

  function frequencyMs(frequency) {
    const match = /^(SEC|MIN|HOUR|DAY|WEEK)(\d+)$/i.exec(String(frequency || ""));
    if (!match) return 86400000;
    return {SEC: 1000, MIN: 60000, HOUR: 3600000,
      DAY: 86400000, WEEK: 604800000}[match[1].toUpperCase()] * Number(match[2]);
  }

  function selectionKey(items) {
    return items.map(item => [item.artifact, item.timestamp,
      first(item.row, ["fill_id", "order_id", "event_id"]) || item.index,
    ].join(":")).sort().join("|");
  }

  async function discover(context, state) {
    const source = window.FTJobArtifactQuery.tableSource(
      context, artifactPath(state, "order_detail_data"), {pageSize: 1},
    );
    const data = await source.page(1, {facets: {
      product: productFields, strategy: strategyFields, account: accountFields,
      cash_pool: poolFields,
    }});
    const fillFacets = state.artifactsByName.has("fill_detail_data")
      ? await window.FTJobArtifactQuery.tableSource(context,
        artifactPath(state, "fill_detail_data"), {pageSize: 1}).page(1, {facets: {
          account: accountFields, cash_pool: poolFields,
        }}) : null;
    const choices = {
      products: data.facets?.product || [],
      strategies: data.facets?.strategy || [],
      accounts: [...new Set([...(data.facets?.account || []),
        ...(fillFacets?.facets?.account || [])])],
      cashPools: [...new Set([...(data.facets?.cash_pool || []),
        ...(fillFacets?.facets?.cash_pool || [])])],
    };
    let selected = state.selectedAsset;
    if (!selected || !choices.products.includes(productKey(selected))) {
      let anchor = data.rows?.[0];
      const picked = (state.strategySelection || []).filter(value => (
        value && value !== window.FTBacktestStrategySelection.ALL_STRATEGIES
      ));
      if (picked.length === 1) {
        const match = (state.model?.strategies || []).find(value => (
          [value.id, value.strategyID, value.strategy_id, value.label, value.name]
            .some(alias => String(alias || "") === picked[0])
        ));
        const aliases = [...new Set([
          picked[0], match?.id, match?.label, match?.display_name,
          match?.name, match?.strategy_id,
        ].map(value => String(value || "").trim()).filter(Boolean))];
        const scoped = await source.page(1, {filters: {strategy: {
          fields: strategyFields, values: aliases,
        }}});
        if (scoped.rows?.length) anchor = scoped.rows[0];
      }
      selected = anchor ? {...identity(anchor), account: "", cashPool: "",
        filterMode: "strategy"} : null;
      if (picked.length !== 1 && selected) selected.strategy = "";
    }
    if (selected && !choices.strategies.includes(selected.strategy)) {
      selected = {...selected, strategy: ""};
    }
    if (selected && !choices.accounts.includes(selected.account)) {
      selected = {...selected, account: ""};
    }
    if (selected && !choices.cashPools.includes(selected.cashPool)) {
      selected = {...selected, cashPool: ""};
    }
    return {choices, selected};
  }

  function ensureDiscovery(context, state) {
    if (state.assetPlotDiscovery || !state.artifactsByName.has("order_detail_data")) return;
    state.assetPlotDiscovery = {status: "loading"};
    void discover(context, state).then(({choices, selected}) => {
      if (state.target?.isConnected === false) return;
      state.assetPlotDiscovery = {status: "ready", ...choices};
      state.selectedAsset = selected;
      state.rerender();
    }).catch(error => {
      if (state.target?.isConnected === false) return;
      state.assetPlotDiscovery = {status: "error", message: error.message || String(error)};
      state.rerender();
    });
  }

  function selector(context, label, values, selected, onChange, allLabel = "") {
    const all = `__all_asset_${label}__`;
    const items = [
      ...(allLabel ? [{value: all, label: context.t(allLabel), exclusive: true}] : []),
      ...values.map(value => ({value, label: value})),
    ];
    const filter = window.FTMultiSelectFilter.create(context, {
      title: context.t(label), compact: true, multi: false,
      className: "backtest-asset-filter", items,
      selected: [selected || all],
      searchPlaceholder: context.t(`搜索${label}…`),
      onChange: choices => onChange(choices[0] === all ? ""
        : choices[0] || (allLabel ? "" : selected)),
    });
    return {label, element: filter.element};
  }

  function controls(context, state) {
    const index = state.assetPlotDiscovery;
    if (index?.status !== "ready" || !index.products.length) return [];
    const current = state.selectedAsset || {};
    const update = change => {
      state.selectedAsset = {...state.selectedAsset, ...change};
      state.rerender();
    };
    return [
      selector(context, "筛选维度", ["按策略", "按账户", "按资金池"],
        ({strategy: "按策略", account: "按账户", cash_pool: "按资金池"})[
          current.filterMode || "strategy"], value => update({
          filterMode: ({"按策略": "strategy", "按账户": "account",
            "按资金池": "cash_pool"})[value] || "strategy",
          strategy: "", account: "", cashPool: "",
        })),
      ...(current.filterMode === "account"
        ? [selector(context, "账户", index.accounts, current.account || "",
          account => update({account}), "全部账户")]
        : current.filterMode === "cash_pool"
          ? [selector(context, "资金池", index.cashPools, current.cashPool || "",
            cashPool => update({cashPool}), "全部资金池")]
          : [selector(context, "策略", index.strategies,
            current.strategy || "", strategy => update({strategy}), "全部策略")]),
      selector(context, "品种 / 合约", index.products, productKey(current), product => {
        const generation = state.assetPlotSelectionGeneration
          = (state.assetPlotSelectionGeneration || 0) + 1;
        const source = window.FTJobArtifactQuery.tableSource(
          context, artifactPath(state, "order_detail_data"), {pageSize: 1},
        );
        void source.page(1, {filters: {product: {
          fields: productFields, values: [product],
        }}}).then(data => {
          const row = data.rows?.[0];
          if (!row || state.target?.isConnected === false
              || generation !== state.assetPlotSelectionGeneration
              || state.executionView !== "asset_plot") return;
          const anchor = identity(row);
          update({product: anchor.product, contractUID: anchor.contractUID,
            timestamp: anchor.timestamp});
        }).catch(error => context.showNotice?.(error.message || String(error), true));
      }),
    ];
  }

  function show(state, row) {
    const selected = identity(row);
    if (!selected.product || !Number.isFinite(selected.timestamp)) return;
    state.selectedAsset = {...selected, filterMode: selected.cashPool ? "cash_pool"
      : selected.account ? "account" : "strategy"};
    state.activeTab = "execution_account";
    state.executionView = "asset_plot";
    state.rerender();
  }

  function render(context, state) {
    const root = document.createElement("section");
    root.className = "backtest-asset-result";
    ensureDiscovery(context, state);
    const index = state.assetPlotDiscovery;
    if (index?.status === "loading") {
      root.append(window.FTUI.loading(context.t("正在查找可绘制的交易…")));
      return root;
    }
    if (index?.status === "error") {
      root.append(window.FTUI.empty(context.t("无法读取交易图可选范围"), index.message));
      return root;
    }
    const selected = state.selectedAsset;
    if (!selected) {
      root.append(window.FTUI.empty(context.t("本次任务没有可绘制的订单"), ""));
      return root;
    }
    const heading = document.createElement("header");
    heading.className = "backtest-asset-heading";
    const title = document.createElement("h3");
    title.textContent = context.t("Asset Plot · 交易图");
    const subtitle = document.createElement("span");
    subtitle.textContent = [selected.product,
      selected.filterMode === "strategy" ? selected.strategy : "",
      selected.filterMode === "account" ? selected.account : "",
      selected.filterMode === "cash_pool" ? selected.cashPool : ""]
      .filter(Boolean).join(" · ");
    heading.append(title, subtitle);
    const note = document.createElement("p");
    note.className = "backtest-asset-note";
    note.textContent = context.t("价格来自当前行情源；点击 K 线查看行情，点击其上下方的买卖标记查看逐笔事件，并可为每笔成交选择价格线。行情若更新，图上价格可能与回测时不同。");
    const chartMount = document.createElement("div");
    chartMount.className = "backtest-asset-chart";
    const timelineControls = document.createElement("div");
    timelineControls.className = "backtest-order-track-controls";
    chartMount.addEventListener("wheel", event => {
      if (event.target?.closest?.(".highcharts-tooltip")) {
        // Let the tooltip scroll itself; do not pass the wheel to Highcharts'
        // chart-wide mouse-wheel zoom handler.
        event.stopImmediatePropagation();
      }
    }, {capture: true, passive: true});
    const inspector = document.createElement("div");
    inspector.className = "backtest-asset-inspector-mount";
    const list = document.createElement("div");
    list.className = "backtest-asset-events";
    root.append(heading, note, chartMount, timelineControls, inspector, list);
    let generation = 0;
    let events = [];
    let chart = null;
    let disposeAssetChart = null;
    let usingLightweight = false;
    let removalObserver = null;
    let currentPayload = null;
    let page = 1;
    let selectedItems = [];
    const selectedGroups = new Map();
    const selectedPriceEvents = new Map();
    let tooltipEvents = [];
    let toolkitItems = [];
    let toolkitTime = null;
    let groupFilter = null;
    let eventCache = null;
    let priceCache = null;
    let orderLimit = 10;
    let timelineRange = null;
    const renderTimeline = (minimum, maximum) => {
      if (usingLightweight) {
        timelineControls.replaceChildren();
        return;
      }
      if (!timelineRange || timelineRange[0] !== minimum
          || timelineRange[1] !== maximum) orderLimit = 10;
      timelineRange = [minimum, maximum];
      const visible = events.filter(item => item.timestamp >= minimum
        && item.timestamp <= maximum);
      const model = orderTimeline(context, visible, minimum, maximum,
        items => select(items), {limit: orderLimit});
      timelineControls.replaceChildren();
      const label = document.createElement("span");
      label.textContent = `${context.t("订单历史")} · ${model.rows.length}/${model.total}`;
      timelineControls.append(label);
      const legend = document.createElement("span");
      legend.textContent = context.t("○ 提交 · ◇ 改单 · □ 撮合 · ● 成交 · ▾ 撤单 · 灰色◇ 同刻多笔");
      timelineControls.append(legend);
      if (model.total > model.rows.length) {
        timelineControls.append(window.FTUI.actionButton(context.t("加载更多订单"), () => {
          orderLimit += 10;
          renderTimeline(minimum, maximum);
          if (!currentPayload) return;
          const previous = chart?.xAxis?.[0];
          const bounds = [previous?.min, previous?.max];
          chart = window.FTPriceChart.render(context, chartMount, currentPayload,
            chartDisplayOptions);
          if (bounds.every(Number.isFinite)) chart?.xAxis?.[0]?.setExtremes(
            ...bounds, true, false, {trigger: "ft-data-refresh"});
          tradePriceLines(chart, [...selectedPriceEvents.values()]);
        }));
      }
    };
    const renderTable = () => {
      list.replaceChildren();
      if (!events.length) {
        const empty = document.createElement("p");
        empty.textContent = context.t("当前范围没有该合约的订单或成交");
        list.append(empty); return;
      }
      const shown = groupFilter || events;
      if (groupFilter) {
        const filterBar = document.createElement("div");
        filterBar.className = "backtest-asset-group-filter";
        const label = document.createElement("strong");
        label.textContent = context.t(`已选择 ${groupFilter.length} 笔事件`);
        const clear = window.FTUI.actionButton(context.t("显示全部事件"), () => {
          selectedGroups.clear();
          selectedItems = [];
          groupFilter = null;
          toolkitItems = [];
          toolkitTime = null;
          if (!usingLightweight) chart?.tooltip?.hide?.();
          inspector.replaceChildren();
          page = 1;
          renderTable();
        });
        filterBar.append(label, clear);
        list.append(filterBar);
      }
      const table = window.FTUI.pagedTable([
        "时间", "订单阶段 / ID", "策略", "账户 / 资金池", "方向 / 状态", "数量",
        "价格", "剩余", "手续费", "账本变化",
      ].map(label => context.t(label)), shown, {
        page, pageSize: 20,
        onPageChange(next) { page = next; renderTable(); },
        renderRow(item) {
          const row = item.row;
          const isFill = item.artifact === "fill_detail_data";
          const remaining = isFill ? first(row, ["active_leaves"]) : null;
          const finalRemaining = first(item.order, ["active_leaves"]);
          const terminalUnfilled = first(item.order, ["terminal_unfilled"]);
          const currency = String(first(row, ["account_currency", "currency"]) || "");
          const ledger = [
            row.cash_before != null && row.cash_after != null
              ? `现金 ${change(row, "cash_before", "cash_after")} ${currency}`.trim() : "",
            row.margin_before != null && row.margin_after != null
              && (Number(row.margin_before) !== 0 || Number(row.margin_after) !== 0)
              ? `保证金 ${change(row, "margin_before", "margin_after")} ${currency}`.trim() : "",
            row.position_before != null && row.position_after != null
              ? `持仓 ${change(row, "position_before", "position_after")}` : "",
          ].filter(Boolean).join("；");
          return [
            window.FTUI.formatDate(item.timestamp) || new Date(item.timestamp).toLocaleString(),
            `${stageLabel(item)} · ${first(row, ["fill_id", "attempt_id", "request_id",
              "order_id", "event_id"]) || "—"}`,
            first(row, strategyFields) || first(item.order, strategyFields) || "—",
            [first(row, accountFields) || first(item.order, accountFields),
              first(row, poolFields) || first(item.order, poolFields)]
              .filter(Boolean).join(" / ") || "—",
            first(row, ["side", "offset", "status"]) || "—",
            number(first(row, isFill ? ["quantity", "filled_quantity"]
              : ["requested_quantity", "quantity"])),
            number(first(row, ["fill_price", "price"])),
            [remaining != null ? `${number(remaining)}（事件后）`
              : finalRemaining != null ? `${number(finalRemaining)}（订单最终）` : "未记录",
              terminalUnfilled != null ? `终止未成交 ${number(terminalUnfilled)}` : "",
            ].filter(Boolean).join("；"),
            isFill && row.fee != null ? `${number(row.fee)} ${currency}`.trim() : "—",
            ledger || "未记录",
          ];
        },
      });
      table.tableShell.classList.add("backtest-domain-table");
      table.tableShell.setAttribute("aria-label", context.t("交易事件明细"));
      [...table.body.rows].forEach((row, index) => {
        const item = shown[table.start + index];
        row.tabIndex = 0;
        row.classList.toggle("active", selectedItems.includes(item));
        row.addEventListener("click", () => select([item]));
        row.addEventListener("keydown", event => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault(); select([item]);
          }
        });
      });
      list.append(table.shell);
    };
    const select = (items, point = null) => {
      const key = selectionKey(items);
      if (selectedGroups.has(key)) {
        selectedGroups.delete(key);
        toolkitItems = [];
        toolkitTime = null;
      } else {
        selectedGroups.set(key, items);
        toolkitItems = items;
        toolkitTime = point?.x ?? null;
      }
      selectedItems = [...new Set([...selectedGroups.values()].flat())];
      inspector.replaceChildren();
      if (selectedItems.length) inspector.append(eventInspector(context, selectedItems, events));
      if (!usingLightweight && toolkitItems.length && point?.x != null) {
        chart?.tooltip?.refresh?.(point);
      }
      else if (!usingLightweight) chart?.tooltip?.hide?.();
      groupFilter = selectedItems.length ? selectedItems : null;
      const firstIndex = (groupFilter || events).indexOf(items[0]);
      if (firstIndex >= 0) page = Math.floor(firstIndex / 20) + 1;
      renderTable();
    };
    const openMarket = point => {
      toolkitItems = [];
      tooltipEvents = [];
      toolkitTime = point.x;
      chart?.tooltip?.refresh?.(point);
    };
    chartMount.addEventListener("click", event => {
      const button = event.target?.closest?.(".asset-tooltip-price-toggle");
      if (!button || !chartMount.contains(button)) return;
      event.preventDefault();
      event.stopPropagation();
      const item = tooltipEvents[Number(button.getAttribute("data-ft-event-index"))];
      if (!item) return;
      const key = selectionKey([item]);
      if (selectedPriceEvents.has(key)) selectedPriceEvents.delete(key);
      else selectedPriceEvents.set(key, item);
      tradePriceLines(chart, [...selectedPriceEvents.values()]);
      const selected = selectedPriceEvents.has(key);
      button.setAttribute("aria-pressed", String(selected));
      button.textContent = `${selected ? "移除价格线" : "显示价格线"} · ${number(
        first(item.row, ["fill_price", "price"]))}`;
    });
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
    const load = async (minimum, maximum, maxPoints = 1200,
      visibleMinimum = minimum, visibleMaximum = maximum) => {
      const current = ++generation;
      let matching;
      if (eventCache && Date.now() - eventCache.fetchedAt < 15000
          && minimum >= eventCache.minimum
          && maximum <= eventCache.maximum) {
        const cached = eventCache.result.events.filter(item => item.timestamp >= minimum
          && item.timestamp <= maximum);
        matching = {events: cached, sourceCount: cached.length};
      } else {
        matching = await loadEvents(context, state, selected, minimum, maximum,
          Math.min(1200, maxPoints));
        if (matching.sourceCount === matching.events.length) {
          eventCache = {minimum, maximum, result: matching, fetchedAt: Date.now()};
        }
      }
      if (!root.isConnected || current !== generation) return null;
      const ranged = window.FTMarketData.rangeRequest(priceRequest, minimum, maximum,
        maxPoints);
      ranged.anchor_timestamps = [...new Set(matching.events.map(item => item.timestamp))];
      ranged.anchor_tolerance_ms = frequencyMs(frequency);
      let price = null;
      if (priceCache && Date.now() - priceCache.fetchedAt < 15000
          && minimum >= priceCache.minimum && maximum <= priceCache.maximum) {
        const rows = (priceCache.price.payload.data || []).filter(row => {
          const time = window.FTPriceChart.timestampOf(Array.isArray(row)
            ? row[0] : first(row, ["timestamp", "datetime", "date", "time"]));
          return time >= minimum && time <= maximum;
        });
        if (rows.length && rows.length <= maxPoints) {
          price = {payload: {...priceCache.price.payload, data: rows,
            count: rows.length, returned_count: rows.length}};
        }
      }
      if (!price) {
        price = await window.FTMarketData.prices(context, ranged, "server");
        const count = Number(price.payload?.count);
        const returned = Number(price.payload?.returned_count);
        if (Number.isFinite(count) && count === returned
            && Array.isArray(price.payload?.data)) {
          priceCache = {minimum, maximum, price, fetchedAt: Date.now()};
        }
      }
      if (!root.isConnected || current !== generation) return null;
      events = matching.events;
      page = 1;
      groupFilter = null;
      selectedItems = [];
      selectedGroups.clear();
      selectedPriceEvents.clear();
      toolkitItems = [];
      toolkitTime = null;
      if (!usingLightweight) tradePriceLines(chart, []);
      inspector.replaceChildren();
      renderTable();
      const sampling = matching.sourceCount > events.length
        ? ` · 事件展示 ${events.length}/${matching.sourceCount}` : "";
      note.textContent = context.t("价格来自当前行情源；点击 K 线查看行情，点击买卖标记查看成交，下方订单历史按订单展示已记录的状态变化。成交可单独显示价格线；订单历史不表示盘口深度或排队位置。行情若更新，图上价格可能与回测时不同。")
        + ` · ${price.payload.data_source || context.t("自动行情源")}` + sampling;
      renderTimeline(visibleMinimum, visibleMaximum);
      currentPayload = {...price.payload, product: selected.product,
        freq: price.payload.freq || frequency,
        __assetEvents: events,
        __ftEventsComplete: matching.sourceCount === matching.events.length};
      return currentPayload;
    };
    const chartDisplayOptions = {
      assetMode: true, preserveSourceBars: true, showRangeLoading: false,
      tooltipActiveTime: () => toolkitTime,
      onMarketClick: openMarket,
      eventTooltipFields: eventFieldsFor,
      tooltipEventItems: timestamp => timestamp === toolkitTime ? toolkitItems : [],
      onTooltipEvents: items => { tooltipEvents = items; },
      isPriceSelected: item => selectedPriceEvents.has(selectionKey([item])),
      keepOtherSeriesVisible: true,
      reuseSeriesPresentation: true,
      loadingText: context.t("正在读取当前时间范围…"),
      rangeDebounceMs: 120,
      overlaySeries: (value, bars) => markerSeries(value.__assetEvents || [], bars,
        select),
      orderTimeline: value => {
        const rows = value.__assetEvents || [];
        const minimum = timelineRange?.[0] ?? -Infinity;
        const maximum = timelineRange?.[1] ?? Infinity;
        return orderTimeline(context, rows, minimum, maximum,
          items => select(items), {limit: orderLimit});
      },
      loadRange: (minimum, maximum, range) => load(minimum, maximum,
        range.maxPoints, range.visibleMinimum, range.visibleMaximum),
      onRangeError: error => { note.textContent = error.message || String(error); },
    };
    chartMount.append(window.FTUI.loading(context.t("正在读取行情与交易事件…")));
    const initialSpan = /^(MIN|HOUR)/i.test(frequency) ? 7 * DAY : 30 * DAY;
    load(selected.timestamp - initialSpan, selected.timestamp + initialSpan)
      .then(async payload => {
        if (!payload) return;
        if (window.FTStaticLoader?.loadGroups) {
          await window.FTStaticLoader.loadGroups(["chart-workbench-asset"]);
          if (!root.isConnected) return;
          if (!window.FTChartWorkbench?.mountAssetChart) {
            throw new Error(context.t("交易图组件未加载"));
          }
          usingLightweight = true;
          timelineControls.replaceChildren();
          disposeAssetChart = window.FTChartWorkbench.mountAssetChart(chartMount, {
            bars: window.FTPriceChart.barsOf(payload),
            events: events.map(chartEvent),
            frequencyMs: frequencyMs(frequency),
            translate: value => context.t(value),
            onEventClick: selectedEvents => select(selectedEvents),
            loadRange: async (minimum, maximum, maxPoints) => {
              const updated = await load(minimum, maximum, maxPoints,
                minimum, maximum);
              return updated ? {bars: window.FTPriceChart.barsOf(updated),
                events: updated.__assetEvents.map(chartEvent)} : null;
            },
          });
        } else {
          chart = window.FTPriceChart.render(context, chartMount, payload,
            chartDisplayOptions);
          if (Number.isFinite(chart?.xAxis?.[0]?.min)
              && Number.isFinite(chart?.xAxis?.[0]?.max)) {
            renderTimeline(chart.xAxis[0].min, chart.xAxis[0].max);
          }
        }
      }).catch(error => {
        chartMount.replaceChildren();
        const message = document.createElement("p");
        message.textContent = error.message || String(error);
        chartMount.append(message);
      });
    state.assetPlotCleanup = () => {
      generation += 1;
      removalObserver?.disconnect();
      disposeAssetChart?.();
      disposeAssetChart = null;
      chartMount.__ftPriceChartObserver?.disconnect?.();
      chart?.destroy?.();
      chart = null;
    };
    queueMicrotask(() => {
      if (!root.isConnected || !window.MutationObserver) return;
      removalObserver = new MutationObserver(() => {
        if (!root.isConnected) state.assetPlotCleanup?.();
      });
      removalObserver.observe(document.body, {childList: true, subtree: true});
    });
    return root;
  }

  window.FTBacktestAssetPlot = Object.freeze({
    controls, discover, eventFilters, eventDetail, groupedPoints, identity,
    loadEvents, markerSeries, orderTimeline, render, show, tradePriceLines,
  });
})();
