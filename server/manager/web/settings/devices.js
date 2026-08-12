(() => {
  function current(context) {
    return context.isRouteCurrent?.() !== false;
  }

  function pageHeader(context, title, subtitle, icon) {
    const root = document.createElement("header");
    root.className = "settings-page-header";
    root.innerHTML = '<span class="settings-icon"></span><div><h2></h2><p></p></div>';
    root.querySelector(".settings-icon").append(FTIcons.node(icon));
    root.querySelector("h2").textContent = context.t(title);
    root.querySelector("p").textContent = context.t(subtitle);
    return root;
  }

  function row(context, title, description, value) {
    const root = document.createElement("div"); root.className = "settings-row";
    const copy = document.createElement("div");
    const heading = document.createElement("b"); heading.textContent = context.t(title);
    const subtitle = document.createElement("small"); subtitle.textContent = context.t(description);
    copy.append(heading, subtitle);
    const control = document.createElement("div"); control.className = "settings-value";
    if (value instanceof Node) control.append(value); else control.textContent = FTUI.text(value);
    root.append(copy, control); return root;
  }

  function card(context, title, rows) {
    const section = document.createElement("section"); section.className = "settings-section";
    const heading = document.createElement("h3"); heading.textContent = context.t(title); section.append(heading);
    const list = document.createElement("div"); list.className = "settings-rows";
    rows.forEach(item => list.append(row(context, ...item)));
    section.append(list); return section;
  }

  function deviceListSection(context, payload, refresh) {
    const section = document.createElement("section"); section.className = "settings-section";
    const heading = document.createElement("h3"); heading.textContent = context.t("已登记设备"); section.append(heading);
    const list = document.createElement("div"); list.className = "settings-rows";
    const records = Array.isArray(payload.devices) ? payload.devices : [];
    if (!records.length) {
      const empty = document.createElement("p"); empty.textContent = context.t("尚未登记设备"); section.append(empty); return section;
    }
    records.forEach(record => {
      const value = document.createElement("div"); value.style.display = "grid"; value.style.gap = "4px";
      const title = document.createElement("strong"); title.textContent = record.device_name || record.device_id;
      const detail = document.createElement("small");
      const state = record.enabled ? context.t("启用") : context.t("已撤销");
      detail.textContent = `${record.username || ""} · ${state} · ${context.t("公钥指纹")} ${record.public_key_fingerprint || ""} · ${record.source_server_id || ""}`;
      const client = document.createElement("small");
      const clientType = {
        browser: context.t("浏览器"),
        swift: context.t("Swift 客户端"),
      }[record.client_type] || context.t("未知客户端");
      client.textContent = `${context.t("客户端")}：${record.client_name || clientType} · ${context.t("登记 IP")}：${record.enrollment_ip || context.t("未记录")} · ${context.t("最近访问 IP")}：${record.last_seen_ip || context.t("未记录")}`;
      value.append(title, detail, client);
      if (record.enabled) {
        const revoke = document.createElement("button"); revoke.className = "secondary";
        revoke.textContent = context.t("撤销");
        revoke.onclick = async () => {
          revoke.disabled = true;
          try {
            await context.api("/api/devices/revoke", {
              method: "POST", body: JSON.stringify({device_id: record.device_id}),
            });
            context.showNotice(context.t("设备已撤销")); await refresh();
          } catch (error) {
            context.showNotice(error.message, true); revoke.disabled = false;
          }
        };
        value.append(revoke);
      }
      const rowRoot = document.createElement("div"); rowRoot.className = "settings-row";
      rowRoot.append(value); list.append(rowRoot);
    });
    section.append(list); return section;
  }

  async function devices(context, body) {
    body.append(pageHeader(
      context, "设备白名单", "使用浏览器设备密钥控制公网 FactorTester 访问", "checkmark.seal",
    ));
    if (!context.session) {
      body.append(card(context, "设备白名单", [[
        "需要登录", "登录后才能登记或撤销设备", "不可用",
      ]]));
      return;
    }
    let payload;
    let targetPayload;
    try {
      [payload, targetPayload] = await Promise.all([
        context.api("/api/devices"),
        context.api("/api/device/public-targets"),
      ]);
    } catch (error) {
      body.append(card(context, "设备白名单", [["读取设置失败", error.message, "不可用"]]));
      return;
    }
    if (!current(context)) return;
    const content = document.createElement("div");
    const refresh = async () => {
      const latest = await context.api("/api/devices");
      if (!current(context)) return;
      content.replaceChildren(deviceListSection(context, latest, refresh));
    };
    const targets = Array.isArray(targetPayload.targets) ? targetPayload.targets : [];
    const targetServer = document.createElement("select");
    targetServer.className = "inline-setting";
    const targetPlaceholder = document.createElement("option");
    targetPlaceholder.value = "";
    targetPlaceholder.textContent = context.t("选择公网服务器");
    targetServer.append(targetPlaceholder);
    targets.forEach(target => {
      const option = document.createElement("option");
      option.value = target.server_id || "";
      option.dataset.endpoint = target.endpoint || "";
      const latency = Number.isFinite(Number(target.latency_ms))
        ? `${Number(target.latency_ms).toFixed(0)} ms`
        : context.t("延迟未知");
      option.textContent = `${target.server_id || ""} · ${target.endpoint || ""} · ${latency}`;
      targetServer.append(option);
    });
    if (targets.length) targetServer.selectedIndex = 1;
    const targetEndpoint = document.createElement("span");
    targetEndpoint.className = "settings-muted";
    const selectedTarget = () => {
      const option = targetServer.selectedOptions[0];
      if (!option?.value || !option.dataset.endpoint) return null;
      return {serverID: option.value, endpoint: option.dataset.endpoint};
    };
    const updateTargetEndpoint = () => {
      const target = selectedTarget();
      targetEndpoint.textContent = target
        ? target.endpoint
        : context.t("内网 Manager 未发现在线的 HTTPS 公网服务器");
    };
    targetServer.addEventListener("change", updateTargetEndpoint);
    updateTargetEndpoint();
    const deviceName = document.createElement("input");
    deviceName.className = "inline-setting";
    deviceName.placeholder = context.t("例如：我的 Mac");
    const authorize = document.createElement("button");
    authorize.className = "primary";
    authorize.textContent = context.t("生成一次性公网授权");
    authorize.disabled = !targets.length;
    const authorizationURL = document.createElement("textarea");
    authorizationURL.className = "inline-setting";
    authorizationURL.readOnly = true; authorizationURL.rows = 3;
    authorizationURL.placeholder = context.t("生成后复制授权链接");
    authorizationURL.style.width = "min(100%, 520px)";
    const copyURL = document.createElement("button");
    copyURL.className = "secondary"; copyURL.textContent = context.t("复制授权链接");
    copyURL.disabled = true;
    copyURL.onclick = async () => {
      try {
        await navigator.clipboard.writeText(authorizationURL.value);
        context.showNotice(context.t("授权链接已复制；请在目标公网地址打开"));
      } catch (_) { context.showNotice(context.t("请手动复制授权链接"), true); }
    };
    authorize.onclick = async () => {
      const target = selectedTarget();
      if (!target) {
        context.showNotice(
          context.t("内网 Manager 未发现在线的 HTTPS 公网服务器"), true,
        );
        return;
      }
      authorize.disabled = true; copyURL.disabled = true; authorizationURL.value = "";
      try {
        const result = await context.api("/api/device/authorization", {
          method: "POST",
          body: JSON.stringify({
            target_server_id: target.serverID,
            target_endpoint: target.endpoint,
            device_name: deviceName.value.trim(),
            next: "/",
          }),
        });
        authorizationURL.value = result.authorization_url || "";
        copyURL.disabled = !authorizationURL.value;
        context.showNotice(context.t("授权链接已生成；请在目标公网浏览器中打开"));
      } catch (error) {
        context.showNotice(error.message, true);
      } finally { authorize.disabled = !targets.length; }
    };
    const limit = Number(payload.public_device_limit || 3);
    const count = Number(payload.public_device_count || 0);
    const userCount = Number(payload.public_user_count || (count ? 1 : 0));
    body.append(card(context, "登记设备", [
      ["当前账户", "设备将绑定到当前登录用户", context.session.username],
      ["公网访问用户数", "当前统计范围内拥有启用公网设备的用户数量", userCount],
      ["公网设备名额", "每个用户最多登记三台；撤销后可重新登记", `${count} / ${limit}`],
      ["目标公网服务器", "由内网 Manager 提供，并按延迟、负载和服务器标识排序", targetServer],
      ["目标公网地址", "地址来自服务器登记信息；客户端不保存或硬编码公网 IP", targetEndpoint],
      ["设备名称", "设备名称只用于白名单管理，不参与设备识别", deviceName],
      ["授权流程", "内网只生成一次性授权；公网来源重新生成并保存自己的私钥", authorize],
      ["授权链接", "链接短时有效且只能使用一次；请通过安全渠道复制到目标公网浏览器", authorizationURL],
      ["复制", "不要把授权链接提交到公开聊天、日志或代码仓库", copyURL],
      ["存储位置", "服务器只保存随机设备编号和公钥；公网私钥保存在对应来源浏览器的不可导出存储中", payload.backend || ""],
    ]));
    content.append(deviceListSection(context, payload, refresh)); body.append(content);
  }

  window.FTSettingsDevices = {show: devices};
})();
