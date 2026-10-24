(() => {
  // The trading desk is a status surface until a server-owned venue adapter,
  // account reconciliation, and trading permission contract are installed.
  // No broker credential or order intent may be handled in browser state.
  const modes = Object.freeze({paper: "模拟盘", live: "实盘"});
  const reasons = Object.freeze({
    "live data adapter not configured": "未配置实时行情适配器",
    "venue execution adapter not configured": "未配置券商执行适配器",
  });

  function node(tag, className, value) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (value != null) element.textContent = value;
    return element;
  }

  function reason(value) {
    const raw = String(value || "").trim();
    return reasons[raw] || raw;
  }

  function connectionSnapshot(payload, mode) {
    const capability = payload?.[mode === "live" ? "live" : "sandbox"];
    const reported = capability && typeof capability.available === "boolean";
    const available = payload?.installed === true
      && reported && capability.available === true;
    const executionName = mode === "live" ? "实盘交易链路" : "模拟交易链路";
    const unknown = ["未报告", "服务端尚未提供该连接的状态"];
    return {
      available,
      reported,
      engine: payload?.installed === true
        ? `NautilusTrader ${String(payload.engine_version || "").trim()}`.trim()
        : "本服务尚未安装 NautilusTrader",
      rows: [
        ["实时行情", ...unknown],
        [executionName, reported ? (available ? "服务端报告可用" : "不可用") : unknown[0],
          reported ? payload?.installed !== true
            ? "本服务尚未安装 NautilusTrader"
            : reason(capability.reason) || "等待独立验收" : unknown[1]],
        ["账户对账", ...unknown],
      ],
    };
  }

  function switcher(context, mode) {
    const tabs = node("div", "backend-settings-tab-bar");
    tabs.setAttribute("role", "tablist");
    for (const [value, label] of Object.entries(modes)) {
      const button = context.button(context.t(label), () => {
        context.navigate(`/trading?mode=${value}`);
      }, context.t(label));
      button.type = "button";
      button.setAttribute("role", "tab");
      button.setAttribute("aria-selected", String(mode === value));
      button.classList.toggle("active", mode === value);
      tabs.append(button);
    }
    return tabs;
  }

  function render(context, requestedMode) {
    const mode = requestedMode === "live" ? "live" : "paper";
    context.activeNav("trading");
    context.setHeading(context.t("交易台"));
    context.toolbar.replaceChildren(switcher(context, mode));

    const root = node("div", "trading-workbench");
    const heading = node("div", "trading-workbench-heading");
    heading.append(
      node("h2", "", context.t(modes[mode])),
      node("p", "", context.t("连接、账户与风险状态由服务端确认；此页面暂不提供下单操作。")),
    );
    const state = node("section", "trading-workbench-panel");
    const stateHeading = node("div", "trading-workbench-panel-heading");
    stateHeading.append(node("h3", "", context.t("运行状态")));
    const badge = node("span", "trading-workbench-status", context.t("正在读取"));
    stateHeading.append(badge);
    const engine = node("p", "trading-workbench-engine", context.t("正在读取服务能力…"));
    const detail = node("p", "trading-workbench-note",
      context.t("未完成接入及账户对账前，模拟盘和实盘都不可操作。"));
    state.append(stateHeading, engine, detail);

    const connections = node("section", "trading-workbench-panel");
    const connectionHeading = node("div", "trading-workbench-panel-heading");
    connectionHeading.append(node("h3", "", context.t("连接状态")));
    const refresh = context.button(context.t("刷新状态"), () => void load(),
      context.t("刷新状态"));
    refresh.type = "button";
    refresh.classList.add("secondary-button");
    connectionHeading.append(refresh);
    const connectionHost = node("div", "trading-workbench-table");
    connections.append(connectionHeading, connectionHost);

    const accounts = node("section", "trading-workbench-panel");
    accounts.append(
      node("h3", "", context.t("账户与持仓")),
      node("p", "trading-workbench-note",
        context.t("能力接口尚未提供经对账的账户、权益和持仓快照；此处不显示推测值。")),
      FTUI.table([
        context.t("账户"), context.t("权益"), context.t("持仓"),
        context.t("对账时间"),
      ], []).shell,
    );
    root.append(heading, state, connections, accounts);
    context.content.replaceChildren(root);

    let requestRevision = 0;
    async function load() {
      const revision = ++requestRevision;
      refresh.disabled = true;
      badge.textContent = context.t("正在读取");
      badge.className = "trading-workbench-status loading";
      let payload = null;
      let failure = "";
      try {
        payload = await context.api("/api/nautilus/capabilities");
      } catch (error) {
        failure = error?.message || String(error);
      }
      if (revision !== requestRevision || context.isRouteCurrent?.() === false
          || root.isConnected === false) return;
      refresh.disabled = false;
      const snapshot = connectionSnapshot(payload, mode);
      badge.textContent = context.t(failure ? "无法读取" : snapshot.available
        ? "仅可查看" : "不可用");
      badge.className = `trading-workbench-status ${failure ? "error"
        : snapshot.available ? "read-only" : "unavailable"}`;
      engine.textContent = failure
        ? context.t("无法读取服务能力") : snapshot.engine;
      detail.textContent = failure
        ? `${context.t("服务状态读取失败")}: ${failure}`
        : snapshot.available
          ? context.t("服务端报告该模式可用；交易台仍仅提供状态查看，尚未开放下单。")
          : context.t("该模式尚未完成适配器接入和账户对账。");
      const rows = failure
        ? [[context.t("能力接口"), context.t("无法读取"), failure]]
        : snapshot.rows.map(row => row.map(value => context.t(value)));
      connectionHost.replaceChildren(FTUI.table([
        context.t("连接"), context.t("状态"), context.t("说明"),
      ], rows).shell);
    }
    void load();
  }

  window.FTTradingWorkbench = Object.freeze({connectionSnapshot, render});
})();
