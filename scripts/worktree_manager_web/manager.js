(() => {
  function statusPill(status) {
    const pill = document.createElement("span");
    pill.className = `pill manager-status ${status}`;
    pill.textContent = ({running: "运行中", degraded: "部分运行", occupied: "端口占用", stopped: "已停止", orphan: "无端口"})[status] || status;
    return pill;
  }

  function actionButton(context, actions, label, path, instanceID, disabled = false, danger = false) {
    const button = document.createElement("button");
    button.textContent = label;
    button.disabled = disabled;
    if (danger) button.classList.add("danger-action");
    button.onclick = async () => {
      if (danger && !window.confirm(`确认执行“${label}”？`)) return;
      await action(context, path, instanceID);
    };
    actions.append(button);
  }

  function openLink(actions, label, href, disabled = false) {
    const link = document.createElement("a");
    link.className = `manager-open${disabled ? " disabled" : ""}`;
    link.textContent = label;
    link.href = href;
    link.target = "_blank";
    link.rel = "noreferrer";
    actions.append(link);
  }

  async function show(context) {
    context.activeNav("manager"); context.setHeading("服务器管理", "Manager 7998");
    context.content.replaceChildren(FTUI.loading("正在读取端口状态…"));
    const payload = await context.api("/api/worktrees");
    const worktrees = payload.worktrees || [];
    const manager = payload.manager || {};
    const wrapper = document.createElement("div"); wrapper.className = "detail-stack manager-page";
    const intro = document.createElement("div"); intro.className = "manager-intro";
    intro.innerHTML = `<b>并行服务与工作树</b><small>本机 127.0.0.1 · 局域网 ${manager.lan_ip || "不可用"} · VS Code 调试前请先停止同端口服务</small>`;
    wrapper.append(intro);
    const view = FTUI.table(["工作树 / 服务", "实例", "端口", "状态", "操作"], []);

    const vibe = payload.vibe_trading || {};
    if (vibe.instance_id) {
      const actions = document.createElement("div"); actions.className = "row-actions manager-actions";
      const occupied = Boolean(vibe.port_in_use && !vibe.running);
      actionButton(context, actions, "启动", "/vibe/start", vibe.instance_id, vibe.running || occupied);
      actionButton(context, actions, "停止", "/vibe/stop", vibe.instance_id, !vibe.running);
      openLink(actions, "打开", `http://127.0.0.1:${vibe.port}/`, !vibe.running && !occupied);
      FTUI.appendRow(view.body, [
        "Vibe-Trading\nresearch UI + MaxA MCP gateway", vibe.instance_id, vibe.port,
        statusPill(vibe.running ? "running" : occupied ? "occupied" : "stopped"), actions,
      ]);
    }

    worktrees.forEach(item => {
      const actions = document.createElement("div"); actions.className = "row-actions";
      const noPort = !item.port;
      const occupied = Boolean(item.port_in_use && !item.running);
      const canStop = Boolean(item.running || item.daemon_running);
      const canOpen = Boolean(item.running || occupied);
      if (!noPort) {
        actionButton(context, actions, "启动", "/start", item.instance_id, item.running || occupied);
        actionButton(context, actions, "停止", "/stop", item.instance_id, !canStop);
        actionButton(context, actions, "重启 API", "/restart-api", item.instance_id, !item.daemon_running);
        actionButton(context, actions, "完整重启", "/restart-bundle", item.instance_id, !item.daemon_running);
        actionButton(context, actions, "强制停止", "/force-stop", item.instance_id, !canStop, true);
        openLink(actions, "本机打开", `http://127.0.0.1:${item.port}/`, !canOpen);
        if (manager.lan_ip) openLink(actions, "局域网打开", `http://${manager.lan_ip}:${item.port}/`, !canOpen);
      } else {
        const warning = document.createElement("small");
        warning.textContent = "分支名没有 issue 编号，未分配服务端口";
        actions.append(warning);
      }
      const identity = document.createElement("div"); identity.className = "manager-identity";
      const title = document.createElement("b"); title.textContent = item.label || item.branch;
      const detail = document.createElement("small"); detail.textContent = `${item.branch || ""} · ${item.head || ""}`;
      identity.append(title, detail);
      const status = noPort ? "orphan" : item.running && item.daemon_running ? "running" : item.running ? "degraded" : occupied ? "occupied" : "stopped";
      FTUI.appendRow(view.body, [
        identity, item.instance_id, noPort ? "—" : item.port, statusPill(status), actions,
      ]);
    });
    context.toolbar.append(context.button("↻", () => show(context), "刷新"));
    wrapper.append(view.shell);
    context.content.replaceChildren(wrapper);
  }

  async function action(context, path, instanceID) {
    const body = new URLSearchParams({instance_id: instanceID});
    await context.api(path, {method: "POST", headers: {"Content-Type": "application/x-www-form-urlencoded"}, body});
    context.showNotice("操作已完成"); await show(context);
  }

  window.FTManager = {show};
})();
