(() => {
  function pageHeader(context) {
    const root = document.createElement("header");
    root.className = "settings-page-header";
    root.innerHTML = '<span class="settings-icon"></span><div><h2></h2><p></p></div>';
    root.querySelector(".settings-icon").append(
      FTIcons.node("externaldrive.connected.to.line.below"),
    );
    root.querySelector("h2").textContent = context.t("控制数据库");
    root.querySelector("p").textContent = context.t(
      "集中管理用户、机构、层级、配额与公网设备白名单",
    );
    return root;
  }

  function input(type, value = "") {
    const field = document.createElement("input");
    field.className = "inline-setting";
    field.type = type;
    field.value = value;
    return field;
  }

  function row(context, title, description, value) {
    const root = document.createElement("div");
    root.className = "settings-row";
    const copy = document.createElement("div");
    const heading = document.createElement("b");
    heading.textContent = context.t(title);
    const detail = document.createElement("small");
    detail.textContent = context.t(description);
    copy.append(heading, detail);
    const control = document.createElement("div");
    control.className = "settings-value";
    if (value instanceof Node) control.append(value);
    else control.textContent = FTUI.text(value);
    root.append(copy, control);
    return root;
  }

  function card(context, title, rows) {
    const section = document.createElement("section");
    section.className = "settings-section";
    const heading = document.createElement("h3");
    heading.textContent = context.t(title);
    const list = document.createElement("div");
    list.className = "settings-rows";
    rows.forEach(item => list.append(row(context, ...item)));
    section.append(heading, list);
    return section;
  }

  async function show(context, body) {
    body.append(pageHeader(context));
    if (!context.session?.capabilities?.manager) {
      body.append(card(context, "需要超级管理员", [[
        "控制数据库设置",
        "只有超级管理员可以配置控制数据库连接",
        "不可用",
      ]]));
      return;
    }
    let payload;
    try {
      payload = await context.api("/api/control-database/config");
    } catch (error) {
      body.append(card(context, "控制数据库", [[
        "读取设置失败", error.message, "不可用",
      ]]));
      return;
    }
    const config = payload.config || {};
    const managed = config.managed_by === "environment";
    const host = input("text", config.host || "");
    host.placeholder = "101.133.144.27";
    const port = input("number", String(config.port || 5432));
    port.min = "1"; port.max = "65535";
    const database = input("text", config.database || "factortester_control");
    const user = input("text", config.user || "factortester_control");
    user.autocomplete = "username";
    const password = input("password");
    password.autocomplete = "new-password";
    password.placeholder = config.password_configured
      ? context.t("已配置 · 留空保持不变") : context.t("数据库密码");
    const sslmode = document.createElement("select");
    sslmode.className = "inline-setting";
    ["require", "verify-ca", "verify-full"].forEach(value => {
      const option = document.createElement("option");
      option.value = value; option.textContent = value; sslmode.append(option);
    });
    sslmode.value = config.sslmode || "require";
    const save = document.createElement("button");
    save.className = "primary";
    save.textContent = context.t("保存并连接");
    [host, port, database, user, password, sslmode, save].forEach(control => {
      control.disabled = managed;
    });
    const status = document.createElement("span");
    status.textContent = managed
      ? context.t("由服务器环境管理")
      : config.configured ? context.t("已配置") : context.t("未配置");
    save.onclick = async () => {
      save.disabled = true;
      try {
        const result = await context.api("/api/control-database/config", {
          method: "PUT",
          body: JSON.stringify({
            host: host.value.trim(),
            port: Number(port.value || 5432),
            database: database.value.trim(),
            user: user.value.trim(),
            password: password.value,
            sslmode: sslmode.value,
            connect_timeout: 5,
          }),
        });
        password.value = "";
        password.placeholder = context.t("已配置 · 留空保持不变");
        status.textContent = result.config?.healthy
          ? context.t("已连接") : context.t("已配置");
        context.showNotice(context.t("控制数据库设置已保存"));
      } catch (error) {
        context.showNotice(error.message, true);
      } finally {
        save.disabled = false;
      }
    };
    body.append(card(context, "PostgreSQL", [
      ["数据库主机", "填写 PostgreSQL 服务器可达的 IP 地址或主机名", host],
      ["端口", "PostgreSQL 默认使用 5432", port],
      ["数据库名称", "用户、机构、层级、配额与已认证设备的权威数据库", database],
      ["用户名", "仅使用 FactorTester 专用数据库角色", user],
      ["密码", "密码写入服务器权限 600 的状态文件且不会回显", password],
      ["SSL 模式", "公网数据库连接至少使用 require", sslmode],
      ["连接状态", "保存前会验证网络、凭据与数据库 schema", status],
      ["应用", "连接成功后立即切换本机 Manager", save],
    ]));
  }

  window.FTSettingsControlDatabase = {show};
})();
