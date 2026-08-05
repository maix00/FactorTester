(() => {
  const sections = [
    ["account", "账户", "◉"], ["server", "服务器", "▤"],
    ["workspace", "工作区", "⌘"], ["language", "语言", "◎"],
    ["updates", "客户端更新", "↓"],
  ];

  async function show(context, selected = "account") {
    context.activeNav("settings"); context.setHeading(context.t("设置"), "FTClient");
    const shell = document.createElement("div"); shell.className = "settings-hub";
    const sidebar = document.createElement("nav"); sidebar.className = "settings-sidebar";
    const body = document.createElement("div"); body.className = "settings-content";
    sections.forEach(([id, title, symbol]) => {
      const button = document.createElement("button");
      button.className = id === selected ? "active" : "";
      button.innerHTML = `<span>${symbol}</span><span></span>`;
      button.lastElementChild.textContent = context.t(title);
      button.onclick = () => show(context, id);
      sidebar.append(button);
    });
    shell.append(sidebar, body); context.content.replaceChildren(shell);
    await renderSection(context, selected, body);
  }

  async function renderSection(context, selected, body) {
    if (selected === "account") return account(context, body);
    if (selected === "server") return server(context, body);
    if (selected === "workspace") return workspace(context, body);
    if (selected === "language") return language(context, body);
    return updates(context, body);
  }

  function pageHeader(title, subtitle, icon) {
    const root = document.createElement("header"); root.className = "settings-page-header";
    root.innerHTML = `<span class="settings-icon"></span><div><h2></h2><p></p></div>`;
    root.querySelector(".settings-icon").textContent = icon;
    root.querySelector("h2").textContent = title;
    root.querySelector("p").textContent = subtitle;
    return root;
  }

  function card(title, rows) {
    const section = document.createElement("section"); section.className = "settings-section";
    const heading = document.createElement("h3"); heading.textContent = title; section.append(heading);
    const list = document.createElement("div"); list.className = "settings-rows";
    rows.forEach(item => list.append(row(...item))); section.append(list); return section;
  }

  function row(title, description, value) {
    const root = document.createElement("div"); root.className = "settings-row";
    const copy = document.createElement("div");
    const heading = document.createElement("b"); heading.textContent = title;
    const subtitle = document.createElement("small"); subtitle.textContent = description;
    copy.append(heading, subtitle);
    const control = document.createElement("div"); control.className = "settings-value";
    if (value instanceof Node) control.append(value); else control.textContent = FTUI.text(value);
    root.append(copy, control); return root;
  }

  function account(context, body) {
    body.append(pageHeader(context.t("账户"), context.t("登录、身份与账户安全"), "◉"));
    const action = document.createElement("button"); action.className = "primary";
    action.textContent = context.t(context.session ? "登出" : "登录");
    action.onclick = () => context.session ? context.logout() : context.openLogin();
    body.append(card(context.t("账户"), [
      [context.t("登录账户"), context.t("当前用于访问研究、任务与工作区的账户"), context.session?.username || context.t("未登录")],
      [context.t("账户操作"), context.t("登录完成后此页面自动更新"), action],
      [context.t("用户角色"), context.t("由服务器分配，客户端不能修改"), context.session?.role || ""],
      [context.t("服务器管理"), context.t("超级管理员登录后自动获得管理页面"), context.t(context.session?.capabilities?.manager ? "可用" : "不可用")],
    ]));
  }

  async function server(context, body) {
    body.append(pageHeader(context.t("服务器"), context.t("配置 Manager 与当前 FactorTester 服务端口"), "▤"));
    const ports = await context.api("/api/jobs/ports");
    const input = document.createElement("input"); input.className = "inline-setting";
    input.inputMode = "numeric";
    input.placeholder = FTI18n.format("空值（自动选择的 %@ 端口）", ports.automatic_port || context.t("可用"));
    input.value = localStorage.getItem("ft-service-port") || "";
    input.onchange = () => {
      const value = input.value.trim();
      if (value && !ports.ports.map(String).includes(value)) {
        context.showNotice(context.t("该端口当前不可用"), true); return;
      }
      value ? localStorage.setItem("ft-service-port", value) : localStorage.removeItem("ft-service-port");
      context.showNotice(context.t("服务端口设置已保存"));
    };
    body.append(card("Manager", [
      [context.t("协议"), context.t("Manager 管理接口的传输协议"), location.protocol.replace(":", "").toUpperCase()],
      [context.t("网址"), context.t("Manager 主机名或 IP"), location.hostname],
      [context.t("端口"), context.t("Manager 管理端口"), location.port || (location.protocol === "https:" ? "443" : "80")],
      [context.t("测试连接"), context.t("当前页面已通过 Manager 读取可用服务"), FTI18n.format("已连接 · %@ 个端口", ports.ports.length)],
    ]));
    body.append(card(context.t("FactorTester 服务端口"), [
      [context.t("服务端口"), context.t("可填写固定端口；留空时由 Manager 自动选择可用端口"), input],
    ]));
  }

  async function workspace(context, body) {
    body.append(pageHeader(context.t("工作区"), context.t("个人目录、canonical 因子库与 Profile 研究现场"), "⌘"));
    const value = (await context.api("/api/client/workspace")).workspace;
    body.append(card(context.t("个人工作区"), [
      [context.t("用户根目录"), context.t("当前账户的本地研究根目录"), value.user_root],
      [context.t("个人工作区"), context.t("因子、策略和可复用证据的本地空间"), value.personal_workspace],
      [context.t("Profile 根目录"), context.t("各研究现场的独立 worktree"), value.profiles_root],
      [context.t("本地 canonical 因子库"), context.t("固定位置的本地 Git 工作副本"), value.factor_library?.path],
      [context.t("Git 版本"), context.t("本地 canonical 当前提交"), value.factor_library?.head || ""],
      [context.t("未提交文件"), context.t("本地工作副本的修改数量"), value.factor_library?.dirty_file_count ?? ""],
    ]));
  }

  function language(context, body) {
    body.append(pageHeader(context.t("语言"), context.t("选择 FTClient 的界面语言"), "◎"));
    const control = document.createElement("select");
    control.innerHTML = '<option value="system"></option><option value="zh-Hans"></option><option value="en">English</option>';
    control.options[0].textContent = context.t("跟随系统");
    control.options[1].textContent = context.t("简体中文");
    control.value = context.languagePreference || "system";
    control.disabled = !context.session;
    control.onchange = async () => {
      control.disabled = true;
      try {
        await context.setLanguagePreference(control.value);
      } catch (error) {
        context.showNotice(error.message, true);
        control.disabled = false;
      }
    };
    const description = context.session
      ? context.t("语言偏好绑定当前登录用户，并在 Swift 与 Web 客户端之间同步")
      : context.t("未登录时跟随系统；登录后可保存用户语言偏好");
    body.append(card(context.t("界面语言"), [[context.t("显示语言"), description, control]]));
  }

  async function updates(context, body) {
    body.append(pageHeader(context.t("客户端更新"), context.t("管理 Main / Beta 客户端版本与更新策略"), "↓"));
    let release = {};
    try { release = await context.api(context.servicePath("/api/client/releases/beta.json")); } catch (_) {}
    body.append(card(context.t("客户端更新"), [
      [context.t("可用版本"), context.t("当前 Beta 更新通道返回的版本"), release.version || release.short_version || context.t("暂不可用")],
      [context.t("更新渠道"), context.t("Swift 客户端沿用既定发布与签名流程"), "Beta"],
      [context.t("更新来源"), context.t("由当前 FactorTester 服务返回并经 7998 转发"), release.url || context.t("FactorTester 服务")],
    ]));
  }

  window.FTSettings = {show};
})();
