(() => {
  const sources = Object.freeze([
    ["order_detail_data", "订单"],
    ["fill_detail_data", "成交与结算"],
    ["cash_detail_data", "现金"],
    ["position_detail_data", "持仓"],
    ["margin_detail_data", "保证金"],
    ["fee_detail_data", "手续费"],
  ]);
  const coreSources = Object.freeze(sources.slice(0, 2));

  function number(value) {
    const result = window.FTChartTimeline.timestamp(value, Number.NaN);
    if (Number.isFinite(result)) return result;
    const numeric = Number(value);
    return Number.isFinite(numeric) ? numeric : null;
  }

  function events(payloads, strategyScope, rowFilter = () => true) {
    return sources.flatMap(([artifact, label]) => (
      strategyScope.filterRows(payloads?.[artifact]?.rows || [])
        .filter(rowFilter).flatMap((row, index) => {
        const timestamp = number(row?.timestamp ?? row?.created_at ?? row?.updated_at);
        return timestamp == null ? [] : [{artifact, label, row, timestamp, index}];
      })
    )).sort((left, right) => left.timestamp - right.timestamp || left.index - right.index);
  }

  function timeline(items) {
    return [...new Set(items.map(item => item.timestamp))];
  }

  function nearestIndex(times, requested) {
    if (!times.length) return 0;
    const value = number(requested);
    if (value == null) return times.length - 1;
    let best = 0;
    for (let index = 1; index < times.length; index += 1) {
      if (Math.abs(times[index] - value) < Math.abs(times[best] - value)) best = index;
    }
    return best;
  }

  function summary(context, item) {
    const row = item.row || {};
    const product = row.product || row.instrument || "";
    const identity = row.order_id || row.fill_id || row.event_id || "";
    const action = row.status || row.event_type || row.side || row.offset || "";
    return [context.t(item.label), product, identity, action].filter(Boolean).join(" · ");
  }

  function render(context, target, payloads, strategyScope, options = {}) {
    const items = events(payloads, strategyScope, options.rowFilter);
    const times = timeline(items);
    if (!times.length) {
      target.replaceChildren(Object.assign(document.createElement("p"), {
        className: "backtest-domain-empty", textContent: context.t("暂无可追溯的交易事件"),
      }));
      return;
    }
    let active = nearestIndex(times, options.timestamp);
    const paint = () => {
      const timestamp = times[active];
      const rows = items.filter(item => item.timestamp === timestamp);
      const toolbar = document.createElement("div");
      toolbar.className = "backtest-event-toolbar";
      const previous = window.FTUI.actionButton(context.t("上一时刻"), () => {
        active = Math.max(0, active - 1); paint();
      }, {variant: "secondary"});
      const next = window.FTUI.actionButton(context.t("下一时刻"), () => {
        active = Math.min(times.length - 1, active + 1); paint();
      }, {variant: "secondary"});
      previous.disabled = active === 0; next.disabled = active === times.length - 1;
      const current = document.createElement("strong");
      current.textContent = window.FTUI.formatDate(timestamp) || String(timestamp);
      const position = document.createElement("span");
      position.textContent = `${active + 1} / ${times.length}`;
      toolbar.append(previous, current, position, next);

      const flow = document.createElement("ol");
      flow.className = "backtest-event-flow";
      rows.forEach(item => {
        const node = document.createElement("li");
        node.dataset.eventKind = item.artifact;
        const title = document.createElement("strong");
        title.textContent = summary(context, item);
        const facts = document.createElement("dl");
        facts.className = "backtest-event-facts";
        const visible = [
          ["策略", item.row.strategy || item.row.strategy_id],
          ["账户", item.row.account_id || item.row.account_ref || item.row.account
            || item.row.ledger_id || item.row.ledger],
          ["资金池", item.row.cash_pool_id || item.row.cash_pool || item.row.pool_id],
          ["产品", item.row.product || item.row.instrument],
          ["方向", item.row.side || item.row.offset],
          ["数量", item.row.quantity || item.row.filled_quantity || item.row.requested_quantity],
          ["价格", item.row.price || item.row.fill_price],
          ["手续费", item.row.fee],
          ["现金变化", item.row.cash_change],
          ["保证金变化", item.row.margin_change],
        ].filter(([, value]) => value != null && value !== "");
        visible.forEach(([label, value]) => {
          const term = document.createElement("dt"); term.textContent = context.t(label);
          const description = document.createElement("dd"); description.textContent = String(value);
          facts.append(term, description);
        });
        const detail = document.createElement("details");
        const detailTitle = document.createElement("summary");
        detailTitle.textContent = context.t("查看原始事件字段");
        const raw = document.createElement("pre");
        raw.textContent = JSON.stringify(item.row, null, 2);
        detail.append(detailTitle, raw);
        node.append(title, facts, detail); flow.append(node);
      });
      target.replaceChildren(toolbar, flow);
    };
    paint();
  }

  function open(context, payloads, strategyScope, timestamp) {
    const view = window.FTBacktestAnalysisUI.dialog(context, "交易事件", "");
    render(context, view.body, payloads, strategyScope, {timestamp});
    return view;
  }

  window.FTBacktestEventFlow = Object.freeze({coreSources, events, open, render, sources});
})();
