(() => {
  function statusLabel(context, value) {
    if (value.running) return context.t("运行中");
    if (!value.configured) return context.t("配置不可用");
    return context.t("已停止");
  }

  function actionButton(context, label, action, disabled = false) {
    const button = document.createElement("button");
    button.className = "secondary";
    button.type = "button";
    button.textContent = context.t(label);
    button.disabled = disabled;
    button.onclick = action;
    return button;
  }

  function statusView(context, value, reload) {
    const root = document.createElement("section");
    root.className = "settings-section manager-access-section";
    const heading = document.createElement("h3");
    heading.textContent = context.t("Mihomo Dashboard");
    const note = document.createElement("p");
    note.className = "settings-muted";
    note.textContent = value.last_error || (
      value.configured ? "" : context.t("不可用")
    );
    const actions = document.createElement("div");
    actions.className = "settings-inline-actions";
    const run = async action => {
      actions.querySelectorAll("button").forEach(item => { item.disabled = true; });
      try {
        await context.api("/api/admin/mihomo", {
          method: "POST",
          body: JSON.stringify({action}),
        });
        context.showNotice(context.t("操作已完成"));
      } catch (error) {
        context.showNotice(error.message, true);
      }
      await reload();
    };
    actions.append(
      actionButton(context, "启动", () => run("start"), value.running),
      actionButton(context, "停止", () => run("stop"), !value.running),
    );
    const status = document.createElement("span");
    status.className = `pill manager-status ${value.running ? "running" : "stopped"}`;
    status.textContent = statusLabel(context, value);
    actions.append(status);
    root.append(heading);
    if (note.textContent) root.append(note);
    root.append(actions);
    return root;
  }

  async function show(context) {
    context.activeNav("mihomo");
    context.setHeading(context.t("Mihomo Dashboard"), "Mihomo");
    const wrapper = document.createElement("div");
    wrapper.className = "detail-stack manager-page";
    const body = document.createElement("div");
    body.className = "manager-tab-content";
    wrapper.append(body);
    context.toolbar.append(
      FTUI.refreshButton(context, () => show(context)),
    );
    context.content.replaceChildren(wrapper);

    const reload = async () => {
      try {
        const payload = await context.api("/api/admin/mihomo");
        const value = payload.mihomo || {};
        const dashboard = value.running
          ? (() => {
            const frame = document.createElement("iframe");
            frame.className = "module-frame mihomo-dashboard-frame";
            frame.title = context.t("Mihomo Dashboard");
            frame.src = "/mihomo-dashboard/?presentation=embedded";
            return frame;
          })()
          : null;
        body.replaceChildren(statusView(context, value, reload));
        if (dashboard) body.append(dashboard);
      } catch (error) {
        body.replaceChildren(FTUI.empty(
          context.t("无法读取"),
          error.message || context.t("Mihomo Dashboard 不可用"),
        ));
      }
    };
    await reload();
  }

  window.FTMihomo = Object.freeze({show});
})();
