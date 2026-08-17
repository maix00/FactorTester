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
      const title = document.createElement("strong"); title.textContent =
        record.device_name || context.t("白名单设备");
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
      let revoke;
      if (record.enabled) {
        revoke = document.createElement("button"); revoke.className = "secondary";
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
      }
      const rowRoot = document.createElement("div"); rowRoot.className = "settings-row";
      rowRoot.append(value);
      if (revoke) rowRoot.append(revoke);
      list.append(rowRoot);
    });
    section.append(list); return section;
  }

  async function devices(context, body) {
    body.append(pageHeader(
      context,
      "我的设备",
      "白名单用户通过公网访客模式登录后自动登记当前浏览器；可在此查看或撤销自己的设备",
      "checkmark.seal",
    ));
    if (!context.session) {
      body.append(card(context, "我的设备", [[
        "需要登录", "登录后才能查看或撤销自己的设备", "不可用",
      ]]));
      return;
    }
    let payload;
    try {
      payload = await context.api("/api/devices");
    } catch (error) {
      body.append(card(context, "我的设备", [["读取设置失败", error.message, "不可用"]]));
      return;
    }
    if (!current(context)) return;
    const content = document.createElement("div");
    const refresh = async () => {
      const latest = await context.api("/api/devices");
      if (!current(context)) return;
      content.replaceChildren(deviceListSection(context, latest, refresh));
    };
    const totalCount = Number(payload.public_device_total_count ?? payload.public_device_count ?? 0);
    body.append(card(context, "白名单设备自动登记", [
      ["当前账户", "设备会绑定到当前登录用户", context.session.username],
      ["自动登记方式", "白名单用户在公网访客模式登录后，当前浏览器自动生成设备密钥并登记", context.t("仅公网访客模式")],
      ["设备策略", "所有已登记设备均来自白名单用户的公网访客自动登记", context.t("白名单设备自动登记")],
      ["公网设备总数", "包括当前服务器已登记且启用的白名单设备", totalCount],
      ["私钥存储", "服务器只保存随机设备编号和公钥；私钥保存在当前浏览器的不可导出存储中", payload.backend || ""],
    ]));
    content.append(deviceListSection(context, payload, refresh)); body.append(content);
  }

  window.FTSettingsDevices = {show: devices};
})();
