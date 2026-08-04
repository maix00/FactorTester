(() => {
  const sections = [
    ["account", "账户", "◉"], ["server", "服务器", "▤"],
    ["workspace", "工作区", "⌘"], ["language", "语言", "◎"],
    ["updates", "客户端更新", "↓"],
  ];

  async function show(context, selected = "account") {
    context.activeNav("settings"); context.setHeading("设置", "FTClient");
    const shell = document.createElement("div"); shell.className = "settings-hub";
    const sidebar = document.createElement("nav"); sidebar.className = "settings-sidebar";
    const body = document.createElement("div"); body.className = "settings-content";
    sections.forEach(([id, title, symbol]) => {
      const button = document.createElement("button");
      button.className = id === selected ? "active" : "";
      button.innerHTML = `<span>${symbol}</span><span></span>`;
      button.lastElementChild.textContent = title;
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
    if (selected === "language") return language(body);
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
    body.append(pageHeader("账户", "登录、身份与账户安全", "◉"));
    const action = document.createElement("button"); action.className = "primary";
    action.textContent = context.session ? "登出" : "登录";
    action.onclick = () => context.session ? context.logout() : context.openLogin();
    body.append(card("账户", [
      ["登录账户", "当前用于访问研究、任务与工作区的账户", context.session?.username || "未登录"],
      ["账户操作", "登录完成后此页面自动更新", action],
      ["用户角色", "由服务器分配，客户端不能修改", context.session?.role || ""],
      ["服务器管理", "超级管理员登录后自动获得管理页面", context.session?.capabilities?.manager ? "可用" : "不可用"],
    ]));
  }

  async function server(context, body) {
    body.append(pageHeader("服务器", "配置 Manager 与当前 FactorTester 服务端口", "▤"));
    const ports = await context.api("/api/jobs/ports");
    const input = document.createElement("input"); input.className = "inline-setting";
    input.inputMode = "numeric"; input.placeholder = `空值（自动选择的 ${ports.automatic_port || "可用"} 端口）`;
    input.value = localStorage.getItem("ft-service-port") || "";
    input.onchange = () => {
      const value = input.value.trim();
      if (value && !ports.ports.map(String).includes(value)) {
        context.showNotice("该端口当前不可用", true); return;
      }
      value ? localStorage.setItem("ft-service-port", value) : localStorage.removeItem("ft-service-port");
      context.showNotice("服务端口设置已保存");
    };
    body.append(card("Manager", [
      ["协议", "Manager 管理接口的传输协议", location.protocol.replace(":", "").toUpperCase()],
      ["网址", "Manager 主机名或 IP", location.hostname],
      ["端口", "Manager 管理端口", location.port || (location.protocol === "https:" ? "443" : "80")],
      ["测试连接", "当前页面已通过 Manager 读取可用服务", `已连接 · ${ports.ports.length} 个端口`],
    ]));
    body.append(card("FactorTester 服务端口", [
      ["服务端口", "可填写固定端口；留空时由 Manager 自动选择可用端口", input],
    ]));
  }

  async function workspace(context, body) {
    body.append(pageHeader("工作区", "个人目录、canonical 因子库与 Profile 研究现场", "⌘"));
    const value = (await context.api("/api/client/workspace")).workspace;
    body.append(card("个人工作区", [
      ["用户根目录", "当前账户的本地研究根目录", value.user_root],
      ["个人工作区", "因子、策略和可复用证据的本地空间", value.personal_workspace],
      ["Profile 根目录", "各研究现场的独立 worktree", value.profiles_root],
      ["本地 canonical 因子库", "固定位置的本地 Git 工作副本", value.factor_library?.path],
      ["Git 版本", "本地 canonical 当前提交", value.factor_library?.head || ""],
      ["未提交文件", "本地工作副本的修改数量", value.factor_library?.dirty_file_count ?? ""],
    ]));
  }

  function language(body) {
    body.append(pageHeader("语言", "选择 FTClient 的界面语言", "◎"));
    const control = document.createElement("select");
    control.innerHTML = '<option value="zh-Hans">简体中文</option><option value="en">English</option>';
    control.value = localStorage.getItem("ft-language") || "zh-Hans";
    control.onchange = () => localStorage.setItem("ft-language", control.value);
    body.append(card("界面语言", [["显示语言", "状态值与 API 协议不会随界面语言改变", control]]));
  }

  async function updates(context, body) {
    body.append(pageHeader("客户端更新", "管理 Main / Beta 客户端版本与更新策略", "↓"));
    let release = {};
    try { release = await context.api(context.servicePath("/api/client/releases/beta.json")); } catch (_) {}
    body.append(card("客户端更新", [
      ["可用版本", "当前 Beta 更新通道返回的版本", release.version || release.short_version || "暂不可用"],
      ["更新渠道", "Swift 客户端沿用既定发布与签名流程", "Beta"],
      ["更新来源", "由当前 FactorTester 服务返回并经 7998 转发", release.url || "FactorTester 服务"],
    ]));
  }

  window.FTSettings = {show};
})();
