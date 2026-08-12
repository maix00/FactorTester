(() => {
  const sections = [
    ["account", "账户", "person.crop.circle"], ["server", "服务器", "server.rack"],
    ["federation", "服务器互联", "server.rack"],
    ["control-database", "控制数据库", "externaldrive.connected.to.line.below"],
    ["devices", "设备白名单", "checkmark.seal"],
    ["workspace", "工作区", "square.grid.2x2"], ["language", "语言", "globe"],
    ["updates", "客户端更新", "arrow.down.circle"],
  ];

  function current(context) {
    return context.isRouteCurrent?.() !== false;
  }

  async function show(context, selected = "account") {
    context.activeNav("settings"); context.setHeading(context.t("设置"), "FTClient");
    const shell = document.createElement("div"); shell.className = "settings-hub";
    const sidebar = document.createElement("nav"); sidebar.className = "settings-sidebar";
    const body = document.createElement("div"); body.className = "settings-content";
    sections.forEach(([id, title, symbol]) => {
      const button = document.createElement("button");
      button.className = id === selected ? "active" : "";
      button.innerHTML = '<span class="settings-sidebar-icon"></span><span></span>';
      button.querySelector(".settings-sidebar-icon").append(FTIcons.node(symbol));
      button.lastElementChild.textContent = context.t(title);
      button.onclick = () => context.navigate(`/settings/${encodeURIComponent(id)}`);
      sidebar.append(button);
    });
    shell.append(sidebar, body); context.content.replaceChildren(shell);
    await renderSection(context, selected, body);
  }

  async function renderSection(context, selected, body) {
    if (selected === "account") return account(context, body);
    if (selected === "server") return server(context, body);
    if (selected === "federation") return federation(context, body);
    if (selected === "control-database") {
      return window.FTSettingsControlDatabase.show(context, body);
    }
    if (selected === "devices") return window.FTSettingsDevices.show(context, body);
    if (selected === "workspace") return workspace(context, body);
    if (selected === "language") return language(context, body);
    return updates(context, body);
  }

  function pageHeader(title, subtitle, icon) {
    const root = document.createElement("header"); root.className = "settings-page-header";
    root.innerHTML = '<span class="settings-icon"></span><div><h2></h2><p></p></div>';
    root.querySelector(".settings-icon").append(FTIcons.node(icon));
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
    body.append(pageHeader(context.t("账户"), context.t("登录、身份与账户安全"), "person.crop.circle"));
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
    body.append(pageHeader(context.t("服务器"), context.t("配置 Manager 与当前 FactorTester 服务端口"), "server.rack"));
    const [ports, manifest] = await Promise.all([
      context.api("/api/jobs/ports"),
      context.api("/api/backtest/settings/group_test"),
    ]);
    if (!current(context)) return;
    const servicePort = FTTestRunFields.field(manifest, "service_port");
    if (!servicePort) throw new Error(context.t("运行字段缺少服务端口声明"));
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
      [context.t(servicePort.label), context.t(servicePort.help_text), input],
    ]));
  }

  async function federation(context, body) {
    body.append(pageHeader(
      context.t("服务器互联"),
      context.t("让本机 7998 Manager 与另一台服务器互相转发任务"),
      "server.rack",
    ));
    if (!context.session?.capabilities?.manager) {
      body.append(card(context.t("需要超级管理员"), [[
        context.t("服务器互联设置"),
        context.t("只有超级管理员可以开启、关闭或修改服务器互联"),
        context.t("不可用"),
      ]]));
      return;
    }
    let payload;
    try {
      payload = await context.api("/api/federation/config");
    } catch (error) {
      body.append(card(context.t("服务器互联"), [[
        context.t("读取设置失败"), error.message, context.t("不可用"),
      ]]));
      return;
    }
    if (!current(context)) return;
    const config = payload.config || {};
    const available = Array.isArray(payload.available_ports)
      ? payload.available_ports : [];
    const enabled = document.createElement("input");
    enabled.type = "checkbox"; enabled.checked = Boolean(config.enabled);
    const registerURL = document.createElement("input");
    registerURL.className = "inline-setting"; registerURL.type = "url";
    registerURL.placeholder = "https://remote-host:7998/api/federation/register";
    registerURL.value = config.register_url || "";
    const endpoint = document.createElement("input");
    endpoint.className = "inline-setting"; endpoint.type = "url";
    endpoint.placeholder = "https://this-host:7998";
    endpoint.value = config.public_endpoint || "";
    const artifactEndpoint = document.createElement("input");
    artifactEndpoint.className = "inline-setting"; artifactEndpoint.type = "url";
    artifactEndpoint.placeholder = "https://this-host:7997";
    artifactEndpoint.value = config.artifact_endpoint || "";
    const token = document.createElement("input");
    token.className = "inline-setting"; token.type = "password";
    token.autocomplete = "new-password";
    token.placeholder = config.registration_token_configured
      ? context.t("已配置 · 留空保持不变") : context.t("远端登记令牌");
    const interval = document.createElement("input");
    interval.className = "inline-setting"; interval.type = "number";
    interval.min = "3"; interval.max = "300"; interval.step = "1";
    interval.value = String(config.interval || 10);
    const syncStatus = document.createElement("span");
    const renderSyncStatus = sync => {
      const reports = Array.isArray(sync?.last_report) ? sync.last_report : [];
      const failed = reports.filter(item => item?.status === "error").length;
      const offline = reports.filter(item => item?.status === "offline").length;
      if (!reports.length) {
        syncStatus.textContent = context.t("尚未同步");
      } else if (failed || offline) {
        syncStatus.textContent = `${context.t("部分失败")} · ${failed + offline}`;
      } else {
        const applied = reports.reduce((sum, item) => sum + Number(item?.applied || 0), 0);
        syncStatus.textContent = `${context.t("已同步")} · ${applied} ${context.t("条更新")}`;
      }
      syncStatus.title = context.t("任务列表使用访问时查询；此处仅保留管理员修复同步");
    };
    renderSyncStatus(payload.status?.sync);
    const syncNow = document.createElement("button");
    syncNow.className = "secondary";
    syncNow.textContent = context.t("立即同步");
    syncNow.onclick = async () => {
      syncNow.disabled = true;
      try {
        const result = await context.api("/api/federation/sync", {method: "POST"});
        renderSyncStatus({
          ...(payload.status?.sync || {}),
          last_report: result.reports || [],
          active: payload.status?.sync?.active,
        });
        context.showNotice(context.t("同步请求已完成"));
      } catch (error) {
        context.showNotice(error.message, true);
      } finally { syncNow.disabled = false; }
    };
    const ports = document.createElement("div");
    ports.style.display = "grid"; ports.style.gap = "6px";
    if (!available.length) {
      const empty = document.createElement("small");
      empty.textContent = context.t("没有在线服务端口");
      ports.append(empty);
    }
    available.forEach(route => {
      const text = document.createElement("span");
      text.textContent = `${route.port} · ${route.branch || route.role || context.t("服务")} · ${context.t("在线")}`;
      ports.append(text);
    });
    const save = document.createElement("button");
    save.className = "primary"; save.textContent = context.t("保存并应用");
    const status = document.createElement("small");
    status.textContent = `${config.enabled ? context.t("已启用") : context.t("未启用")} · ${payload.status?.server_id || ""}`;
    save.onclick = async () => {
      save.disabled = true;
      try {
        const bodyValue = {
          enabled: enabled.checked,
          register_url: registerURL.value.trim(),
          public_endpoint: endpoint.value.trim(),
          artifact_endpoint: artifactEndpoint.value.trim(),
          ports: [],
          interval: Number(interval.value || 10),
        };
        if (token.value.trim()) bodyValue.registration_token = token.value.trim();
        const result = await context.api("/api/federation/config", {
          method: "PUT", body: JSON.stringify(bodyValue),
        });
        const next = result.config || {};
        status.textContent = `${next.enabled ? context.t("已启用") : context.t("未启用")} · ${result.status?.active ? context.t("心跳运行中") : context.t("等待连接")}`;
        renderSyncStatus(result.status?.sync);
        token.value = "";
        context.showNotice(context.t("服务器互联设置已保存"));
      } catch (error) {
        context.showNotice(error.message, true);
      } finally { save.disabled = false; }
    };
    body.append(card(context.t("互联节点"), [
      [context.t("启用互联"), context.t("开启后本机 7998 会向对端登记；关闭后停止心跳"), enabled],
      [context.t("远端登记地址"), context.t("对端 Manager 的 7998 注册接口"), registerURL],
      [context.t("本机回调地址"), context.t("对端只通过这个 Manager 地址转发，不直接访问本机服务端口"), endpoint],
      [context.t("生成物公开地址"), context.t("留空时使用回调地址的主机与 7997；反向隧道应填写独立的数据端口"), artifactEndpoint],
      [context.t("登记令牌"), context.t("与对端 Manager 预共享的登记令牌"), token],
      [context.t("心跳间隔（秒）"), context.t("只用于对等 Manager 登记续租；跨服务器任务列表按需查询"), interval],
      [context.t("对外提供的服务端口"), context.t("自动登记当前在线的所有服务端口；新建 issue worktree 并启动后会自动出现在远端"), ports],
      [context.t("状态"), context.t("当前 Manager 对等连接状态"), status],
      [context.t("跨服务器任务"), context.t("打开任务列表的“跨服务器任务”选项卡时，并行查询各节点 7998"), syncStatus],
      [context.t("管理员修复同步"), context.t("仅在需要修复本地任务投影时拉取增量事件；不参与普通列表读取"), syncNow],
      [context.t("应用"), context.t("修改后立即重启本机登记心跳"), save],
    ]));
  }

  async function workspace(context, body) {
    body.append(pageHeader(context.t("工作区"), context.t("个人目录、canonical 因子库与 Profile 研究现场"), "square.grid.2x2"));
    const payload = await context.api("/api/client/workspace");
    if (!current(context)) return;
    const value = payload.workspace;
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
    body.append(pageHeader(context.t("语言"), context.t("选择 FTClient 的界面语言"), "globe"));
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
    body.append(pageHeader(context.t("客户端更新"), context.t("管理 Main / Beta 客户端版本与更新策略"), "arrow.down.circle"));
    let release = {};
    try { release = await context.api(context.servicePath("/api/client/releases/beta.json")); } catch (_) {}
    if (!current(context)) return;
    body.append(card(context.t("客户端更新"), [
      [context.t("可用版本"), context.t("当前 Beta 更新通道返回的版本"), release.version || release.short_version || context.t("暂不可用")],
      [context.t("更新渠道"), context.t("Swift 客户端沿用既定发布与签名流程"), "Beta"],
      [context.t("更新来源"), context.t("由当前 FactorTester 服务返回并经 7998 转发"), release.url || context.t("FactorTester 服务")],
    ]));
  }

  window.FTSettings = {show};
})();
