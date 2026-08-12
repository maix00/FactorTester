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

  function deviceDatabase() {
    return new Promise((resolve, reject) => {
      if (!window.indexedDB) return reject(new Error("浏览器不支持设备凭证存储"));
      const request = indexedDB.open("factortester-device", 1);
      request.onupgradeneeded = () => request.result.createObjectStore("credentials", {keyPath: "device_id"});
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error || new Error("设备凭证存储不可用"));
    });
  }

  async function saveDeviceCredential(value) {
    const database = await deviceDatabase();
    await new Promise((resolve, reject) => {
      const request = database.transaction("credentials", "readwrite")
        .objectStore("credentials").put(value);
      request.onsuccess = resolve;
      request.onerror = () => reject(request.error || new Error("设备凭证保存失败"));
    });
    database.close();
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
      value.append(title, detail);
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
    try {
      payload = await context.api("/api/devices");
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
    const enroll = document.createElement("button"); enroll.className = "primary";
    enroll.textContent = context.t("登记本设备");
    enroll.onclick = async () => {
      enroll.disabled = true;
      try {
        if (!window.crypto?.subtle) throw new Error(context.t("浏览器不支持设备密钥"));
        const pair = await window.crypto.subtle.generateKey(
          {name: "ECDSA", namedCurve: "P-256"}, false, ["sign"],
        );
        const publicKey = await window.crypto.subtle.exportKey("jwk", pair.publicKey);
        const deviceId = window.crypto.randomUUID ? window.crypto.randomUUID() : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
        await context.api("/api/devices/enroll", {
          method: "POST", body: JSON.stringify({device_id: deviceId, public_key: publicKey, device_name: ""}),
        });
        try {
          await saveDeviceCredential({
            device_id: deviceId, username: context.session.username,
            public_key: publicKey, private_key: pair.privateKey,
          });
        } catch (storageError) {
          await context.api("/api/devices/revoke", {
            method: "POST", body: JSON.stringify({device_id: deviceId}),
          }).catch(() => {});
          throw storageError;
        }
        context.showNotice(context.t("设备登记成功；私钥仅保存在此浏览器"));
        await refresh();
      } catch (error) {
        context.showNotice(error.message, true);
      } finally { enroll.disabled = false; }
    };
    const limit = Number(payload.public_device_limit || 3);
    const count = Number(payload.public_device_count || 0);
    body.append(card(context, "登记设备", [
      ["当前账户", "设备将绑定到当前登录用户", context.session.username],
      ["公网设备名额", "每个用户最多登记三台；撤销后可重新登记", `${count} / ${limit}`],
      ["存储位置", "服务器只保存随机设备编号和公钥；私钥保存在浏览器的不可导出存储中", payload.backend || ""],
      ["操作", "在公司内网登记后，可用于公网自动认证", enroll],
    ]));
    content.append(deviceListSection(context, payload, refresh)); body.append(content);
  }

  window.FTSettingsDevices = {show: devices};
})();
