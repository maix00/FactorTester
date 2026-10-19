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
  ];
  const productFields = ["contract_uid", "instrument", "product"];
  const strategyFields = ["strategy_id", "strategy_ref", "strategy"];
  const accountFields = ["account_id", "account_ref", "account", "ledger_id", "ledger"];

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
      fields: selected.contractUID ? productFields
        : ["instrument", "product"],
      values: [selected.contractUID || selected.product],
    }};
    if (selected.strategy) filters.strategy = {
      fields: strategyFields,
      values: [selected.strategy],
    };
    if (selected.account) filters.account = {
      fields: accountFields, values: [selected.account],
    };
    return filters;
  }

  function productKey(selected) {
    return String(selected?.contractUID || selected?.product || "");
  }

  function matchesSelection(row, selected, orderIDs = null) {
    const orderID = String(row?.order_id || "");
    if (orderIDs?.has(orderID)) return true;
    const rowProduct = productKey(identity(row));
    if (!rowProduct || rowProduct !== productKey(selected)) return false;
    if (selected.strategy && first(row, strategyFields) !== selected.strategy) return false;
    if (selected.account && first(row, accountFields) !== selected.account) return false;
    return true;
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
    const orders = state.artifactsByName.has("order_detail_data")
      ? await query("order_detail_data", eventFilters(selected)) : null;
    if (orders) orders.rows = orders.rows.filter(row => matchesSelection(row, selected));
    const results = orders ? [orders] : [];
    if (state.artifactsByName.has("fill_detail_data")) {
      // Native fill rows identify their contract through order_id, not product.
      // Query both representations so older and newer Job artifacts work alike.
      const identifiers = [...new Set((orders?.rows || [])
        .map(row => String(row.order_id || "")).filter(Boolean))];
      const groups = [];
      for (let index = 0; index < identifiers.length; index += 256) {
        groups.push(identifiers.slice(index, index + 256));
      }
      const fillResults = await Promise.all([
        query("fill_detail_data", eventFilters(selected)),
        ...groups.map(values => query("fill_detail_data", {
          order: {fields: ["order_id"], values},
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
    const filledOrderIDs = new Set(results.filter(result => result.name === "fill_detail_data")
      .flatMap(result => result.rows).map(row => String(row.order_id || "")).filter(Boolean));
    const collapseCompletedOrder = item => item.artifact === "order_detail_data"
      && filledOrderIDs.has(String(item.row.order_id || ""))
      && /^(filled|complete|completed|executed)$/i.test(String(item.row.status || "").trim())
      && !(Number(item.row.active_leaves || 0) > 0)
      && !(Number(item.row.terminal_unfilled || 0) > 0);
    const events = results.flatMap(({name, rows}) => rows.map((row, index) => ({
      artifact: name, row, index,
      order: name === "fill_detail_data" ? orderByID.get(String(row.order_id || "")) : row,
      timestamp: window.FTPriceChart.timestampOf(first(row,
        ["timestamp", "submitted_at", "filled_at", "executed_at", "created_at"])),
    }))).filter(item => Number.isFinite(item.timestamp) && !collapseCompletedOrder(item))
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

  function eventFieldsFor(item) {
    const row = item.row;
    const isFill = item.artifact === "fill_detail_data";
    const side = first(row, ["side", "offset"]) || "—";
    const amount = first(row, isFill ? ["quantity", "filled_quantity"]
      : ["requested_quantity", "quantity"]);
    const order = item.order || row;
    const currency = String(first(row, ["account_currency", "currency"]) || "");
    const remaining = first(row, ["active_leaves"]);
    const parts = [
      ["类型", isFill ? "成交" : "订单"],
      ["事件 ID", first(row, ["fill_id", "order_id", "event_id"]) || "未记录"],
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
    if (row.status) parts.push(["状态", row.status]);
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

  function eventInspector(context, items) {
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
      const kind = item.artifact === "fill_detail_data" ? "成交" : "订单";
      const id = first(item.row, ["fill_id", "order_id", "event_id"]) || "未记录 ID";
      summary.textContent = `${context.t(kind)} ${index + 1} · ${id}`;
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
    // Aggregate events of one kind at each candle. Symbols sit outside its
    // wick; recorded execution prices are shown separately on selection.
    const groups = new Map();
    for (const item of events) {
      const bar = nearestBar(bars, item.timestamp);
      if (!bar) continue;
      if (!groups.has(bar.timestamp)) groups.set(bar.timestamp, {bar, items: []});
      groups.get(bar.timestamp).items.push(item);
    }
    const kinds = [
      ["order", "订单", "#d97706", "diamond", item => item.artifact === "order_detail_data", 2],
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
        const gap = Math.max((bar.high - bar.low) * 0.25,
          Math.abs(bar.close) * 0.001, 0.000001);
        const y = direction > 0 ? bar.high + gap * direction
          : bar.low + gap * direction;
        return {x: bar.timestamp, y, custom: {items, bar}};
      }).filter(Boolean),
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
    }});
    const choices = {
      products: data.facets?.product || [],
      strategies: data.facets?.strategy || [],
      accounts: data.facets?.account || [],
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
      selected = anchor ? {...identity(anchor), account: ""} : null;
      if (picked.length !== 1 && selected) selected.strategy = "";
    }
    if (selected && !choices.strategies.includes(selected.strategy)) {
      selected = {...selected, strategy: ""};
    }
    if (selected && !choices.accounts.includes(selected.account)) {
      selected = {...selected, account: ""};
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
      ...(index.strategies.length ? [selector(context, "策略", index.strategies,
        current.strategy || "", strategy => update({strategy}), "全部策略")] : []),
      ...(index.accounts.length ? [selector(context, "账本", index.accounts,
        current.account || "", account => update({account}), "全部账本")] : []),
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
    state.selectedAsset = selected;
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
    subtitle.textContent = [selected.product, selected.strategy, selected.account]
      .filter(Boolean).join(" · ");
    heading.append(title, subtitle);
    const note = document.createElement("p");
    note.className = "backtest-asset-note";
    note.textContent = context.t("价格来自当前行情源；买卖标记位于对应 K 线下方或上方，点击标记打开逐笔事件面板，再选择需要显示的成交价水平线。行情若更新，图上价格可能与回测时不同。");
    const chartMount = document.createElement("div");
    chartMount.className = "backtest-asset-chart";
    const inspector = document.createElement("div");
    inspector.className = "backtest-asset-inspector-mount";
    const list = document.createElement("div");
    list.className = "backtest-asset-events";
    root.append(heading, note, chartMount, inspector, list);
    let generation = 0;
    let events = [];
    let chart = null;
    let removalObserver = null;
    let page = 1;
    let selectedItems = [];
    const selectedGroups = new Map();
    const selectedPriceEvents = new Map();
    let tooltipEvents = [];
    let toolkitItems = [];
    let toolkitTime = null;
    let groupFilter = null;
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
          chart?.tooltip?.hide?.();
          inspector.replaceChildren();
          page = 1;
          renderTable();
        });
        filterBar.append(label, clear);
        list.append(filterBar);
      }
      const table = window.FTUI.pagedTable([
        "时间", "事件 / ID", "策略", "账本", "方向 / 状态", "数量", "价格",
        "剩余", "手续费", "账本变化",
      ].map(context.t), shown, {
        page, pageSize: 20,
        onPageChange(next) { page = next; renderTable(); },
        renderRow(item) {
          const row = item.row;
          const isFill = item.artifact === "fill_detail_data";
          const remaining = first(row, ["active_leaves"]);
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
            `${isFill ? "成交" : "订单"} · ${first(row, ["fill_id", "order_id", "event_id"]) || "—"}`,
            first(row, strategyFields) || first(item.order, strategyFields) || "—",
            first(row, accountFields) || first(item.order, accountFields) || "—",
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
        row.addEventListener("mouseenter", () => hover(item));
        row.addEventListener("mouseleave", () => hover(null));
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
      if (selectedItems.length) inspector.append(eventInspector(context, selectedItems));
      if (toolkitItems.length && point?.x != null) chart?.tooltip?.refresh?.(point);
      else chart?.tooltip?.hide?.();
      groupFilter = selectedItems.length ? selectedItems : null;
      const firstIndex = (groupFilter || events).indexOf(items[0]);
      if (firstIndex >= 0) page = Math.floor(firstIndex / 20) + 1;
      renderTable();
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
    const hover = item => {
      for (const series of chart?.series || []) {
        for (const point of series.points || []) {
          if (!point.options?.custom?.items) continue;
          const active = item && point.options.custom.items.includes(item);
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
      const matching = await loadEvents(context, state, selected, minimum, maximum,
        Math.min(1200, maxPoints));
      if (!root.isConnected || current !== generation) return null;
      const ranged = window.FTMarketData.rangeRequest(priceRequest, minimum, maximum,
        maxPoints);
      ranged.anchor_timestamps = [...new Set(matching.events.map(item => item.timestamp))];
      ranged.anchor_tolerance_ms = frequencyMs(frequency);
      const price = await window.FTMarketData.prices(context, ranged, "server");
      if (!root.isConnected || current !== generation) return null;
      events = matching.events;
      page = 1;
      groupFilter = null;
      selectedItems = [];
      selectedGroups.clear();
      selectedPriceEvents.clear();
      toolkitItems = [];
      toolkitTime = null;
      tradePriceLines(chart, []);
      inspector.replaceChildren();
      renderTable();
      const sampling = matching.sourceCount > events.length
        ? ` · 事件展示 ${events.length}/${matching.sourceCount}` : "";
      note.textContent = context.t("价格来自当前行情源；买卖标记位于对应 K 线下方或上方，点击标记打开逐笔事件面板，再选择需要显示的成交价水平线。行情若更新，图上价格可能与回测时不同。")
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
          assetMode: true, preserveSourceBars: true,
          eventTooltipFields: eventFieldsFor,
          tooltipEventItems: timestamp => timestamp === toolkitTime ? toolkitItems : [],
          onTooltipEvents: items => { tooltipEvents = items; },
          isPriceSelected: item => selectedPriceEvents.has(selectionKey([item])),
          keepOtherSeriesVisible: true,
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
    state.assetPlotCleanup = () => {
      generation += 1;
      removalObserver?.disconnect();
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
    loadEvents, markerSeries, render, show, tradePriceLines,
  });
})();
