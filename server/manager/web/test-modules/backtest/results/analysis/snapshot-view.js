(() => {
  const statusLabels = Object.freeze({
    absent: "无持仓", selected: "已选中", entering: "新进入", exiting: "已退出",
    increasing: "加仓", decreasing: "减仓", holding: "持有", pending_exit: "待退出",
  });

  function compactNumber(value) {
    const number = FTBacktestAnalysisUI.finite(value);
    return number == null ? "" : number.toLocaleString(undefined, {maximumFractionDigits: 2});
  }

  function productName(value) {
    return FTBacktestAnalysisUI.product(value?.product || value);
  }

  function matrixCell(context, value) {
    if (!value || value.status === "absent") return "—";
    const root = document.createElement("div");
    root.className = `snapshot-cell snapshot-${value.status || "holding"}`;
    const status = document.createElement("strong");
    status.textContent = context.t(statusLabels[value.status] || value.status || "持有");
    const values = [];
    if (value.quantity != null) values.push(`${context.t("数量")} ${compactNumber(value.quantity)}`);
    if (value.amount != null) values.push(`${context.t("金额")} ${compactNumber(value.amount)} ${value.currency || ""}`.trim());
    if (value.margin_amount != null) values.push(`${context.t("保证金")} ${compactNumber(value.margin_amount)}`);
    if (value.delta_quantity) values.push(`${context.t("变化")} ${compactNumber(value.delta_quantity)}`);
    const detail = document.createElement("small"); detail.textContent = values.join(" · ");
    root.append(status, detail);
    if (value.open_reason) {
      const reason = document.createElement("small"); reason.textContent = value.open_reason;
      root.append(reason);
    }
    return root;
  }

  function matrix(context, value) {
    const columns = value?.columns || [];
    const rows = value?.rows || [];
    const result = FTUI.table([
      context.t("产品"), ...columns.map(column => (
        `${column.label || "—"}${column.count == null ? "" : ` (${column.count})`}`
      )),
    ]);
    result.shell.classList.add("snapshot-matrix-scroll");
    result.table.classList.add("snapshot-matrix-table");
    rows.forEach((row, rowIndex) => FTUI.appendRow(result.body, [
      productName(row), ...columns.map((_column, columnIndex) => (
        matrixCell(context, value?.cells?.[rowIndex]?.[columnIndex])
      )),
    ]));
    return result.shell;
  }

  function orderFlowTable(context, records) {
    return FTBacktestAnalysisUI.table(context, [
      {label: "时间", value: row => FTBacktestAnalysisUI.timestamp(row.timestamp)},
      {label: "步骤", value: row => row.step || row.label},
      {label: "产品", key: "product"}, {label: "状态", key: "status"},
      {label: "委托数量", value: row => compactNumber(row.intent_quantity)},
      {label: "成交数量", value: row => compactNumber(row.quantity)},
      {label: "成交价", value: row => compactNumber(row.effective_price)},
      {label: "手续费", value: row => compactNumber(row.fee_cost)},
      {label: "拒绝原因", key: "reject_reason"},
    ], records, {empty: "该事件没有订单记录"});
  }

  function renderSnapshot(context, view, state) {
    const value = state.snapshot;
    const toolbar = document.createElement("div"); toolbar.className = "snapshot-toolbar";
    const nav = (label, target, disabled) => {
      const button = FTUI.actionButton(context.t(label), target, {variant: "secondary"});
      button.disabled = disabled; return button;
    };
    const cursors = value.event_cursors || [];
    const cursorIndex = cursors.indexOf(value.event_cursor);
    toolbar.append(
      nav("前一事件", () => state.load({event_cursor: cursors[cursorIndex - 1]}), cursorIndex <= 0),
      nav("后一事件", () => state.load({event_cursor: cursors[cursorIndex + 1]}), cursorIndex < 0 || cursorIndex >= cursors.length - 1),
      nav("前一持仓变化", () => state.load({
        timestamp_ms: value.prev_change_timestamp_ms,
        event_cursor: value.prev_change_event_cursor,
      }), !value.prev_change_event_cursor),
      nav("后一持仓变化", () => state.load({
        timestamp_ms: value.next_change_timestamp_ms,
        event_cursor: value.next_change_event_cursor,
      }), !value.next_change_event_cursor),
    );
    const event = document.createElement("span"); event.className = "snapshot-event-label";
    event.textContent = `${value.event_label || value.event_type || ""} · ${FTBacktestAnalysisUI.timestamp(value.timestamp_ms)}`;
    toolbar.append(event);

    const tabs = document.createElement("div"); tabs.className = "snapshot-main-tabs";
    const matrixButton = document.createElement("button"); matrixButton.type = "button";
    matrixButton.textContent = context.t("持仓矩阵");
    const flowButton = document.createElement("button"); flowButton.type = "button";
    flowButton.textContent = context.t("订单流");
    const content = document.createElement("div"); content.className = "snapshot-tab-content";
    const renderMatrix = () => {
      matrixButton.classList.add("active"); flowButton.classList.remove("active");
      const controls = document.createElement("div"); controls.className = "backtest-analysis-switch";
      const body = document.createElement("div");
      let selected = value.default_matrix_key || value.matrices?.[0]?.key;
      const draw = () => {
        [...controls.children].forEach(button => button.classList.toggle(
          "active", button.dataset.key === selected,
        ));
        const current = (value.matrices || []).find(item => item.key === selected);
        body.replaceChildren(current ? matrix(context, current) : FTUI.empty("", context.t("暂无快照矩阵")));
      };
      (value.matrices || []).forEach(item => {
        const button = document.createElement("button"); button.type = "button";
        button.dataset.key = item.key; button.textContent = context.t(item.label || item.key);
        button.addEventListener("click", () => { selected = item.key; draw(); }); controls.append(button);
      });
      content.replaceChildren(controls, body); draw();
    };
    const renderFlow = async () => {
      flowButton.classList.add("active"); matrixButton.classList.remove("active");
      const controls = document.createElement("div"); controls.className = "snapshot-order-controls";
      const select = document.createElement("select");
      (value.order_flow_groups || []).forEach(group => select.append(
            new Option(
              group.display_name || group.group_name || group.strategy_id || group.group_id,
              group.strategy_id || group.group_id,
            ),
      ));
      const body = document.createElement("div");
      const load = async () => {
        body.replaceChildren(FTUI.loading(context.t("正在读取订单流…")));
        try {
          const payload = await FTBacktestAnalysisAPI.orderFlow(context, state.options, {
            product_path_selection_id: state.request.product_path_selection_id,
            group_id: select.value,
            timestamp_ms: value.timestamp_ms,
          });
          const group = (payload.groups || []).find(item => (
            (item.strategy_id || item.group_id) === select.value
          ))
            || payload.groups?.[0];
          body.replaceChildren(orderFlowTable(context, group?.records || []));
        } catch (error) {
          body.replaceChildren(Object.assign(document.createElement("p"), {textContent: error.message}));
        }
      };
      select.addEventListener("change", load); controls.append(select);
      content.replaceChildren(controls, body); await load();
    };
    matrixButton.addEventListener("click", renderMatrix);
    flowButton.addEventListener("click", renderFlow);
    tabs.append(matrixButton, flowButton);
    view.body.replaceChildren(toolbar, tabs, content); renderMatrix();
  }

  async function open(context, options) {
    const request = FTBacktestResultModel.initialSnapshot(options.resultSummary);
    if (!request) throw new Error(context.t("该任务没有可读取的快照时间点"));
    const view = FTBacktestAnalysisUI.dialog(context, "分组持仓快照", "");
    const state = {request, options, snapshot: null};
    state.load = async patch => {
      view.body.replaceChildren(FTUI.loading(context.t("正在读取持仓快照…")));
      try {
        state.snapshot = await FTBacktestAnalysisAPI.snapshot(context, options, {
          ...request, timestamp_ms: state.snapshot?.timestamp_ms || request.timestamp_ms,
          ...(patch || {}),
        });
        renderSnapshot(context, view, state);
      } catch (error) {
        view.body.replaceChildren(Object.assign(document.createElement("p"), {
          className: "backtest-domain-empty", textContent: error.message,
        }));
      }
    };
    await state.load();
  }

  window.FTBacktestSnapshotView = Object.freeze({matrix, open, orderFlowTable, renderSnapshot});
})();
