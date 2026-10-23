(() => {
  // This entry is deliberately read-only until a venue adapter, account
  // reconciliation, and server-side trading permissions have been installed.
  // In particular, it must never accept broker credentials in browser state.
  function render(context, requestedMode) {
    const mode = requestedMode === "live" ? "live" : "paper";
    context.activeNav("trading");
    context.setHeading(context.t("交易台"));

    const switcher = document.createElement("div");
    switcher.className = "backend-settings-tab-bar";
    switcher.setAttribute("role", "tablist");
    for (const [value, label] of [["paper", "模拟盘"], ["live", "实盘"]]) {
      const button = context.button(context.t(label), () => {
        context.navigate(`/trading?mode=${value}`);
      }, context.t(label));
      button.type = "button";
      button.setAttribute("role", "tab");
      button.setAttribute("aria-selected", String(mode === value));
      button.classList.toggle("active", mode === value);
      switcher.append(button);
    }
    context.toolbar.replaceChildren(switcher);

    const root = document.createElement("div");
    root.className = "trading-workbench";
    const heading = document.createElement("div");
    heading.className = "section-heading";
    const title = document.createElement("h2");
    title.textContent = context.t(mode === "live" ? "实盘" : "模拟盘");
    const note = document.createElement("p");
    note.textContent = context.t(mode === "live"
      ? "尚未配置券商执行适配器与账户对账，实盘操作暂不可用。"
      : "尚未配置实时行情与模拟成交适配器，模拟盘操作暂不可用。");
    heading.append(title, note);

    const status = FTUI.table(
      [context.t("连接"), context.t("状态"), context.t("作用")],
      [
        [context.t("行情"), context.t("未接入"), context.t("行情与图表")],
        [context.t(mode === "live" ? "券商执行" : "模拟成交"), context.t("未接入"), context.t("订单与成交")],
        [context.t("账户对账"), context.t("未接入"), context.t("资金、持仓与风险")],
      ],
    );
    const accessTitle = document.createElement("h3");
    accessTitle.textContent = context.t("接入与账户");
    const accessNote = document.createElement("p");
    accessNote.textContent = context.t("尚无已接入的券商或行情连接。接入信息和凭据只能由服务端适配器管理；接通并验证对账后，这里才会显示账户及可执行操作。");
    root.append(heading, status.shell, accessTitle, accessNote);
    context.content.replaceChildren(root);
  }

  window.FTTradingWorkbench = Object.freeze({render});
})();
