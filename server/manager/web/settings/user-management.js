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

  function section(context, title, subtitle) {
    const root = document.createElement("section");
    root.className = "settings-section";
    const heading = document.createElement("h3");
    heading.textContent = context.t(title);
    root.append(heading);
    if (subtitle) {
      const note = document.createElement("p");
      note.className = "settings-muted";
      note.textContent = context.t(subtitle);
      root.append(note);
    }
    return root;
  }

  function valueRow(context, title, value) {
    const row = document.createElement("div");
    row.className = "settings-row";
    const label = document.createElement("b");
    label.textContent = context.t(title);
    const content = document.createElement("span");
    content.className = "settings-value";
    content.textContent = String(value ?? "");
    row.append(label, content);
    return row;
  }

  function accountLabel(context, account) {
    const alias = String(account?.alias || account?.username || "");
    const username = String(account?.username || "");
    const organization = String(account?.organization_id || "");
    return organization ? `${alias} · ${organization} · ${username}` : `${alias} · ${username}`;
  }

  function allowlistRows(context, payload, refresh) {
    const root = section(
      context,
      "公网访客白名单",
      "白名单按当前服务器保存；共享同一 PostgreSQL 的 Manager 会读取同一条记录。",
    );
    const entries = Array.isArray(payload.visitor_allowlist)
      ? payload.visitor_allowlist : [];
    const users = Array.isArray(payload.users) ? payload.users : [];
    const enabled = new Set(entries.filter(item => item.enabled).map(item => item.username));
    const candidates = users.filter(item => (
      item.active && item.role === "user" && !item.is_admin && !enabled.has(item.username)
    ));
    const controls = document.createElement("div");
    controls.className = "settings-inline-actions";
    const select = document.createElement("select");
    select.className = "inline-setting";
    const placeholder = document.createElement("option");
    placeholder.value = "";
    placeholder.textContent = context.t("选择普通用户");
    select.append(placeholder);
    candidates.forEach(account => {
      const option = document.createElement("option");
      option.value = account.username || "";
      option.textContent = accountLabel(context, account);
      select.append(option);
    });
    const add = document.createElement("button");
    add.className = "primary";
    add.textContent = context.t("添加到白名单");
    add.disabled = !candidates.length;
    add.onclick = async () => {
      if (!select.value) return;
      add.disabled = true;
      try {
        await context.api("/api/admin/public-visitor-allowlist", {
          method: "POST", body: JSON.stringify({username: select.value}),
        });
        context.showNotice(context.t("白名单已更新"));
        await refresh();
      } catch (error) {
        context.showNotice(error.message, true);
        add.disabled = false;
      }
    };
    controls.append(select, add);
    root.append(controls);
    if (!entries.length) {
      const empty = document.createElement("p");
      empty.textContent = context.t("当前服务器没有白名单用户");
      root.append(empty);
      return root;
    }
    entries.forEach(entry => {
      const row = document.createElement("div");
      row.className = "settings-row";
      const copy = document.createElement("div");
      const title = document.createElement("b");
      title.textContent = entry.alias || entry.username || "";
      const detail = document.createElement("small");
      const status = entry.enabled && entry.account_active
        ? context.t("已启用") : context.t("已停用或账户不可用");
      detail.textContent = `${entry.username || ""} · ${entry.organization_id || ""} · ${status}`;
      copy.append(title, detail);
      const remove = document.createElement("button");
      remove.className = "secondary";
      remove.textContent = context.t("从白名单移除");
      remove.disabled = !entry.enabled;
      remove.onclick = async () => {
        remove.disabled = true;
        try {
          await context.api("/api/admin/public-visitor-allowlist", {
            method: "DELETE", body: JSON.stringify({username: entry.username}),
          });
          context.showNotice(context.t("白名单已更新"));
          await refresh();
        } catch (error) {
          context.showNotice(error.message, true);
          remove.disabled = false;
        }
      };
      row.append(copy, remove);
      root.append(row);
    });
    return root;
  }

  function deviceRows(context, payload, refresh) {
    const root = section(
      context,
      "已认证设备",
      "设备记录来自 control_devices；撤销会立即对共享 PostgreSQL 的所有 Manager 生效。",
    );
    const records = Array.isArray(payload.devices) ? payload.devices : [];
    if (!records.length) {
      const empty = document.createElement("p");
      empty.textContent = context.t("当前没有已认证设备");
      root.append(empty);
      return root;
    }
    records.forEach(record => {
      const row = document.createElement("div");
      row.className = "settings-row";
      const copy = document.createElement("div");
      const title = document.createElement("b");
      title.textContent = record.device_name || context.t("白名单设备");
      const detail = document.createElement("small");
      const status = record.enabled ? context.t("已启用") : context.t("已撤销");
      detail.textContent = `${record.username || ""} · ${status} · ${record.source_server_id || ""}`;
      const network = document.createElement("small");
      network.textContent = `${context.t("客户端")}: ${record.client_name || record.client_type || context.t("未知客户端")} · ${context.t("登记 IP")}: ${record.enrollment_ip || context.t("未记录")} · ${context.t("最近访问 IP")}: ${record.last_seen_ip || context.t("未记录")}`;
      copy.append(title, detail, network);
      if (record.enabled) {
        const revoke = document.createElement("button");
        revoke.className = "secondary";
        revoke.textContent = context.t("撤销设备");
        revoke.onclick = async () => {
          revoke.disabled = true;
          try {
            await context.api("/api/admin/access-control/devices/revoke", {
              method: "POST", body: JSON.stringify({device_id: record.device_id}),
            });
            context.showNotice(context.t("设备已撤销"));
            await refresh();
          } catch (error) {
            context.showNotice(error.message, true);
            revoke.disabled = false;
          }
        };
        row.append(copy, revoke);
      } else {
        row.append(copy);
      }
      root.append(row);
    });
    return root;
  }

  async function show(context, body) {
    body.append(pageHeader(
      context,
      "用户与机构",
      "管理当前服务器的访客白名单与所有已认证设备",
      "person.2",
    ));
    if (context.session?.role !== "super_admin") {
      body.append(section(context, "需要超级管理员", "只有超级管理员可以管理访客白名单和已认证设备。"));
      return;
    }
    const content = document.createElement("div");
    const refresh = async () => {
      const payload = await context.api("/api/admin/access-control");
      if (!current(context)) return;
      content.replaceChildren(
        valueRow(context, "当前服务器", payload.server_id),
        valueRow(context, "同步方式", context.t("中央 PostgreSQL（跨 Manager 共享）")),
        allowlistRows(context, payload, refresh),
        deviceRows(context, payload, refresh),
      );
    };
    try {
      await refresh();
    } catch (error) {
      const unavailable = section(
        context,
        "读取失败",
        "中央控制数据库不可用；白名单和设备管理不会使用本地陈旧副本。",
      );
      const detail = document.createElement("small");
      detail.textContent = error.message || "";
      unavailable.append(detail);
      content.append(unavailable);
    }
    body.append(content);
  }

  window.FTSettingsUserManagement = {show};
})();
