(() => {
  function current(context) {
    return context.isRouteCurrent?.() !== false;
  }

  function section(context, title, subtitle) {
    const root = document.createElement("section");
    root.className = "settings-section manager-access-section";
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

  function accountLabel(context, account) {
    const alias = String(account?.alias || account?.username || "");
    const username = String(account?.username || "");
    const organization = String(account?.organization_id || "");
    return organization ? `${alias} · ${organization} · ${username}` : `${alias} · ${username}`;
  }

  function allowlistView(context, payload, reload) {
    const root = section(
      context,
      "公网访客白名单",
      "白名单按当前服务器保存；共享同一 PostgreSQL 的 Manager 会读取同一条记录。",
    );
    const entries = Array.isArray(payload.visitor_allowlist)
      ? payload.visitor_allowlist : [];
    const users = Array.isArray(payload.users) ? payload.users : [];
    const enabled = new Set(
      entries.filter(item => item.enabled).map(item => item.username),
    );
    const candidates = users.filter(item => item.active && !enabled.has(item.username));
    const controls = document.createElement("div");
    controls.className = "settings-inline-actions";
    const select = document.createElement("select");
    select.className = "inline-setting";
    const placeholder = document.createElement("option");
    placeholder.value = "";
    placeholder.textContent = context.t("选择账户");
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
        await reload();
      } catch (error) {
        context.showNotice(error.message, true);
        add.disabled = false;
      }
    };
    controls.append(select, add);
    root.append(controls);

    const table = FTManagerAccessTable.create(context, {
      headers: ["账户", "机构", "角色", "状态", "操作"],
      searchPlaceholder: "搜索白名单用户",
      empty: "当前服务器没有白名单用户",
      searchText: item => [
        item.alias, item.username, item.organization_id, item.role,
      ].join(" "),
      cells: item => [
        `${item.alias || ""} · ${item.username || ""}`,
        item.organization_id || "",
        item.role === "super_admin" ? context.t("超级管理员") : context.t("普通用户"),
        item.enabled && item.account_active
          ? context.t("已启用") : context.t("已停用或账户不可用"),
        (ctx, entry) => {
          const button = document.createElement("button");
          button.className = "secondary";
          button.textContent = ctx.t("从白名单移除");
          button.disabled = !entry.enabled;
          button.onclick = async () => {
            button.disabled = true;
            try {
              await ctx.api("/api/admin/public-visitor-allowlist", {
                method: "DELETE",
                body: JSON.stringify({username: entry.username}),
              });
              ctx.showNotice(ctx.t("白名单已更新"));
              await reload();
            } catch (error) {
              ctx.showNotice(error.message, true);
              button.disabled = false;
            }
          };
          return button;
        },
      ],
    });
    table.setRows(entries);
    root.append(table.root);
    return root;
  }

  function deviceView(context, payload, reload) {
    const root = section(
      context,
      "已认证设备",
      "设备记录来自 control_devices；撤销会立即对共享 PostgreSQL 的所有 Manager 生效。",
    );
    const records = Array.isArray(payload.devices) ? payload.devices : [];
    const table = FTManagerAccessTable.create(context, {
      headers: ["设备", "用户", "客户端", "网络记录", "状态", "操作"],
      searchPlaceholder: "搜索认证设备",
      empty: "当前没有已认证设备",
      searchText: item => [
        item.device_name, item.device_id, item.username, item.client_name,
        item.client_type, item.enrollment_ip, item.last_seen_ip,
      ].join(" "),
      cells: item => [
        `${item.device_name || context.t("白名单设备")} · ${item.device_id || ""}`,
        item.username || "",
        item.client_name || item.client_type || context.t("未知客户端"),
        `${context.t("登记 IP")}: ${item.enrollment_ip || context.t("未记录")} · ${context.t("最近访问 IP")}: ${item.last_seen_ip || context.t("未记录")}`,
        item.enabled ? context.t("已启用") : context.t("已撤销"),
        (ctx, entry) => {
          if (!entry.enabled) return "";
          const button = document.createElement("button");
          button.className = "secondary";
          button.textContent = ctx.t("撤销设备");
          button.onclick = async () => {
            button.disabled = true;
            try {
              await ctx.api("/api/admin/access-control/devices/revoke", {
                method: "POST", body: JSON.stringify({device_id: entry.device_id}),
              });
              ctx.showNotice(ctx.t("设备已撤销"));
              await reload();
            } catch (error) {
              ctx.showNotice(error.message, true);
              button.disabled = false;
            }
          };
          return button;
        },
      ],
    });
    table.setRows(records);
    root.append(table.root);
    return root;
  }

  async function show(context, body, selected = "allowlist") {
    if (context.session?.role !== "super_admin") {
      body.append(section(
        context,
        "需要超级管理员",
        "只有超级管理员可以管理访客白名单和已认证设备。",
      ));
      return;
    }
    let payload;
    try {
      payload = await context.api("/api/admin/access-control");
    } catch (error) {
      const unavailable = section(
        context,
        "读取失败",
        "中央控制数据库不可用；白名单和设备管理不会使用本地陈旧副本。",
      );
      const detail = document.createElement("small");
      detail.textContent = error.message || "";
      unavailable.append(detail);
      body.append(unavailable);
      return;
    }
    if (!current(context)) return;
    const refresh = async () => {
      const latest = await context.api("/api/admin/access-control");
      if (!current(context)) return;
      body.replaceChildren(
        selected === "devices"
          ? deviceView(context, latest, refresh)
          : allowlistView(context, latest, refresh),
      );
    };
    body.append(
      selected === "devices"
        ? deviceView(context, payload, refresh)
        : allowlistView(context, payload, refresh),
    );
  }

  window.FTManagerAccessControl = Object.freeze({show});
})();
