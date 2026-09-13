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
    return FTUI.userDisplay(account?.username, account?.alias);
  }

  function allowlistView(context, payload, reload) {
    const root = section(
      context,
      "公网访客白名单",
      "管理可在公网访客模式登录的用户。",
    );
    const enabled = new Set();
    const mutate = async (method, username, button) => {
      if (button.disabled) return;
      button.disabled = true;
      try {
        await context.api("/api/admin/public-visitor-allowlist", {
          method, body: JSON.stringify({username}),
        });
        context.showNotice(context.t("白名单已更新"));
        await reload();
      } catch (error) {
        context.showNotice(error.message, true);
        button.disabled = false;
      }
    };
    const candidates = FTManagerAccessTable.create(context, {
      headers: ["账户", "机构", "角色", "状态", "操作"],
      searchPlaceholder: "搜索用户（用户名、别名、机构）",
      empty: "没有符合条件的用户",
      refresh: reload,
      searchText: item => [item.username, item.alias, item.organization_id].join(" "),
      cells: item => [
        accountLabel(context, item), item.organization_id || "",
        item.role === "super_admin" ? context.t("超级管理员") : context.t("普通用户"),
        enabled.has(item.username) ? context.t("已加入白名单") : context.t("未加入白名单"),
        () => {
          const included = enabled.has(item.username);
          const button = FTUI.iconButton(context, included ? "xmark" : "plus",
            included ? "从白名单移除" : "添加到白名单",
            () => mutate(included ? "DELETE" : "POST", item.username, button));
          button.disabled = !included && item.active === false;
          return button;
        },
      ],
    });
    root.append(candidates.root);
    root.update = latest => {
      const entries = Array.isArray(latest.visitor_allowlist) ? latest.visitor_allowlist : [];
      enabled.clear();
      entries.filter(item => item.enabled).forEach(item => enabled.add(item.username));
      const accounts = new Map(entries.map(item => [item.username, item]));
      for (const item of latest.users || []) accounts.set(item.username, {...accounts.get(item.username), ...item});
      candidates.setRows([...accounts.values()]);
    };
    root.update(payload);
    return root;
  }

  function deviceView(context, payload, reload) {
    const root = section(
      context,
      "已认证设备",
      "设备记录来自 control_devices；撤销会立即对共享 PostgreSQL 的所有 Manager 生效。",
    );
    const table = FTManagerAccessTable.create(context, {
      headers: ["设备", "用户", "客户端", "网络记录", "状态", "操作"],
      searchPlaceholder: "搜索认证设备",
      refresh: reload,
      empty: "当前没有已认证设备",
      searchText: item => [
        item.device_name, item.device_id, item.username, item.client_name,
        item.client_type, item.enrollment_ip, item.last_seen_ip,
      ].join(" "),
      cells: item => [
        `${item.device_name || context.t("白名单设备")} · ${item.device_id || ""}`,
        FTUI.userDisplay(item.username, item.alias),
        item.client_name || item.client_type || context.t("未知客户端"),
        `${context.t("登记 IP")}: ${item.enrollment_ip || context.t("未记录")} · ${context.t("最近访问 IP")}: ${item.last_seen_ip || context.t("未记录")}`,
        item.enabled ? context.t("已启用") : context.t("已撤销"),
        (ctx, entry) => {
          if (!entry.enabled) return "";
          const button = FTUI.iconButton(ctx, "xmark", "撤销设备", async () => {
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
          });
          return button;
        },
      ],
    });
    root.update = latest => table.setRows(latest.devices || []);
    root.update(payload);
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
      view.update(latest);
    };
    const view = selected === "devices"
      ? deviceView(context, payload, refresh)
      : allowlistView(context, payload, refresh);
    body.append(view);
  }

  window.FTManagerAccessControl = Object.freeze({show});
})();
