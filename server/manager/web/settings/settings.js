(() => {
  const sections = [
    ["account", "账户", "person.crop.circle"], ["server", "服务器", "server.rack"],
    ["federation", "服务器互联", "server.rack"],
    ["control-database", "控制数据库", "externaldrive.connected.to.line.below"],
    ["devices", "我的设备", "checkmark.seal"],
    ["quota", "存储配额", "externaldrive"],
    ["workspace", "工作区", "square.grid.2x2"], ["language", "语言", "globe"],
    ["updates", "客户端更新", "arrow.down.circle"],
  ];

  function visibleSections() { return sections; }

  function current(context) {
    return context.isRouteCurrent?.() !== false;
  }

  async function show(context, selected = "account") {
    context.activeNav("settings"); context.setHeading(context.t("设置"), "FTClient");
    const shell = document.createElement("div"); shell.className = "settings-hub";
    const sidebar = document.createElement("nav"); sidebar.className = "settings-sidebar";
    const body = document.createElement("div"); body.className = "settings-content";
    visibleSections().forEach(([id, title, symbol]) => {
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
      await window.FTStaticLoader?.loadGroups?.(["settings-control-database"]);
      return window.FTSettingsControlDatabase.show(context, body);
    }
    if (selected === "devices") {
      await window.FTStaticLoader?.loadGroups?.(["settings-devices"]);
      return window.FTSettingsDevices.show(context, body);
    }
    if (selected === "quota") {
      await window.FTStaticLoader?.loadGroups?.(["access-table"]);
      return quota(context, body);
    }
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

  function quotaBytes(value) {
    const bytes = Math.max(0, Number(value) || 0);
    if (bytes < 1024) return `${bytes} B`;
    const units = ["KiB", "MiB", "GiB", "TiB"];
    const power = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), 4);
    return `${(bytes / (1024 ** power)).toFixed(2)} ${units[power - 1]}`;
  }

  function quotaCategoryLabel(context, value) {
    const labels = {
      "input:factor_source": "因子源码快照", "input:strategy_source": "策略源码快照",
      "input:product_scope": "产品范围快照", "output:group_execution": "回测执行明细",
      "output:order_audit": "订单审计", "output:strategy_analysis_source": "策略分析明细",
      "output:net_returns": "收益序列", "output:result": "完整结果",
      "output:equity_curve_data": "权益曲线数据", "output:equity_curve_report": "权益曲线图片",
      "output:fee_detail_data": "手续费明细", "output:fee_detail_csv": "手续费明细 CSV",
      "output:report-output-bundle": "报告输出清单",
      "profile:research_reports": "研究报告与草稿", "profile:profile_uploads": "Profile 上传文件",
      "profile:profile_workspaces": "研究身份工作区",
      "protected:factors": "基础因子", "protected:product_groups": "产品组",
    };
    return context.t(labels[value] || value.replace(/^input:/, "提交物 · ").replace(/^output:/, "生成物 · "));
  }

  async function quota(context, body) {
    body.append(pageHeader(context.t("存储配额"), context.t("查看保留的 Job 附件，并预览清理范围"), "externaldrive"));
    if (!context.session) {
      body.append(card(context.t("存储配额"), [["需要登录", "登录后查看个人配额", "不可用"]]));
      return;
    }
    const summary = document.createElement("section"); summary.className = "settings-section";
    const rows = document.createElement("div"); rows.className = "settings-rows";
    const bar = document.createElement("div"); bar.className = "quota-segments";
    bar.setAttribute("role", "img");
    const cleanupButton = document.createElement("button");
    cleanupButton.type = "button";
    cleanupButton.textContent = context.t("一键清理可清理输出");
    let cleanupPreview = {artifact_count: 0, bytes: 0};
    let eligibleCategories = [];
    let cleanupServerId = "";
    const clearOutputs = async (category = "") => {
      const preview = category
        ? eligibleCategories.find(item => item.category === category)
        : cleanupPreview;
      if (!preview || !Number(preview.artifact_count)) return;
      const label = category ? quotaCategoryLabel(context, category) : context.t("所有可清理类别");
      const warning = `${context.t("清理")} ${label}: ${preview.artifact_count} ${context.t("项")}, ${preview.job_count || 0} ${context.t("个任务")}, ${quotaBytes(preview.bytes)}?\n${context.t("仅清理已结束 Job 的输出；如报告挂载这些 Job，实时详情可能无法显示。提交输入、基础因子与产品组不会删除。")}`;
      if (!window.confirm(warning)) return;
      const params = new URLSearchParams({
        cleanup: "eligible", expected_count: String(preview.artifact_count),
        expected_bytes: String(preview.bytes),
        expected_token: String(preview.token || ""),
      });
      if (category) params.set("category", category);
      if (cleanupServerId) params.set("server_id", cleanupServerId);
      try {
        const result = await context.api(`/api/jobs/artifacts?${params}`, {method: "DELETE"});
        context.showNotice(`${context.t("已清理")} ${result.deleted_artifacts} ${context.t("项")}`);
        await refresh();
      } catch (error) {
        context.showNotice(error.message, true);
      }
    };
    cleanupButton.onclick = () => { void clearOutputs(); };
    const categorySection = document.createElement("section"); categorySection.className = "settings-section";
    const categoryHeading = document.createElement("h3"); categoryHeading.textContent = context.t("占用分类");
    const itemsSection = document.createElement("section"); itemsSection.className = "settings-section";
    let selectedCategory = "";
    let offset = 0;
    let categoryTable;
    let itemTable;
    const itemHeading = document.createElement("h3");
    const pager = document.createElement("div"); pager.className = "quota-item-pager";
    const previous = document.createElement("button"); previous.textContent = context.t("上一批");
    const next = document.createElement("button"); next.textContent = context.t("下一批");
    const position = document.createElement("span");
    previous.onclick = () => { offset = Math.max(0, offset - 100); void refreshItems(); };
    next.onclick = () => { offset += 100; void refreshItems(); };
    pager.append(previous, position, next);
    const refreshItems = async () => {
      if (!selectedCategory) return;
      const params = new URLSearchParams({category: selectedCategory, limit: "100", offset: String(offset)});
      const data = await context.api(`/api/jobs/storage?${params}`);
      if (!current(context)) return;
      itemHeading.textContent = `${quotaCategoryLabel(context, selectedCategory)} · ${data.item_count || 0} ${context.t("项")}`;
      itemTable.setRows(data.items || []);
      previous.disabled = offset === 0;
      next.disabled = offset + 100 >= (data.item_count || 0);
      position.textContent = `${Math.min(offset + 1, data.item_count || 0)}–${Math.min(offset + 100, data.item_count || 0)}`;
    };
    const refresh = async () => {
      const [jobResult, profileResult] = await Promise.allSettled([
        context.api("/api/jobs/storage"),
        context.api("/api/storage/profile-inventory"),
      ]);
      if (jobResult.status !== "fulfilled") throw jobResult.reason;
      const data = jobResult.value;
      const profile = profileResult.status === "fulfilled" ? profileResult.value : null;
      if (!current(context)) return;
      const usage = Number(data.usage_bytes || 0);
      const quotaSize = Number(data.quota_bytes || 0);
      const profileStatus = profile
        ? `${quotaBytes(profile.bytes)} · ${context.t("本服务器")} ${profile.storage_server_id}`
        : context.t("计量暂不可用");
      rows.replaceChildren(
        row(context.t("Job 附件"), context.t("全部存储服务器的活跃附件"),
          `${quotaBytes(usage)} / ${quotaBytes(quotaSize)}${data.over_quota ? context.t(" · 已超额") : ""}`),
        row(context.t("报告与 Profile 工作区"), context.t("仅计量本服务器；尚未纳入 Job 配额，其他服务器待统一计量"), profileStatus),
        row(context.t("基础因子与产品组"), context.t("受保护的业务资料；当前尚未纳入此 Job 配额，不能在此删除"), context.t("待计量 · 受保护")),
      );
      bar.replaceChildren();
      let percentage = 0;
      const colors = ["#2775dc", "#7455c4", "#e4a529", "#39a56d", "#d36161"];
      const displayedCategories = [...(data.categories || [])];
      cleanupPreview = data.cleanup_preview || {artifact_count: 0, bytes: 0};
      eligibleCategories = data.cleanup_categories || [];
      cleanupServerId = String(data.storage_server_id || "");
      cleanupButton.disabled = !Number(cleanupPreview.artifact_count);
      cleanupButton.title = `${cleanupPreview.artifact_count} ${context.t("项")} · ${quotaBytes(cleanupPreview.bytes)}`;
      if (Number(data.unattributed_bytes || 0) > 0) displayedCategories.push({
        category: "other_servers", role: "remote", bytes: data.unattributed_bytes,
        artifact_count: "—",
      });
      displayedCategories.push(
        {category: "protected:factors", role: "protected", measured: false},
        {category: "protected:product_groups", role: "protected", measured: false},
      );
      if (profile) {
        for (const [category, item] of Object.entries(profile.categories || {})) {
          displayedCategories.push({category: `profile:${category}`, role: "profile",
            bytes: item.bytes, artifact_count: item.file_count,
            quota_included: false});
        }
      }
      displayedCategories.forEach((entry, index) => {
        if (quotaSize <= 0 || entry.measured === false || entry.quota_included === false) return;
        const width = Math.min(100 - percentage, 100 * Number(entry.bytes || 0) / quotaSize);
        if (width <= 0) return;
        const segment = document.createElement("span");
        segment.style.width = `${width}%`;
        segment.style.background = entry.role === "remote" ? "#8a8f98" : colors[index % colors.length];
        segment.title = `${entry.role === "remote" ? context.t("其他服务器附件") : quotaCategoryLabel(context, entry.category)} · ${quotaBytes(entry.bytes)}`;
        bar.append(segment); percentage += width;
      });
      bar.setAttribute("aria-label", `${context.t("Job 附件配额占用")} ${Math.round(usage / Math.max(1, quotaSize) * 100)}%`);
      categoryTable.setRows(displayedCategories.map((entry, index) => ({
        ...entry, color: entry.role === "protected" ? "#8a8f98" :
          entry.role === "remote" ? "#8a8f98" : colors[index % colors.length],
        percent: quotaSize && entry.quota_included !== false
          ? 100 * Number(entry.bytes || 0) / quotaSize : null,
      })));
      if (selectedCategory) await refreshItems();
    };
    categoryTable = FTManagerAccessTable.create(context, {
      headers: ["类别", "占用", "配额占比", "数量", "操作"], searchPlaceholder: "筛选类别",
      empty: "暂无保留附件", refresh,
      searchText: item => `${item.category} ${quotaCategoryLabel(context, item.category)}`,
      cells: item => [() => {
        const label = document.createElement("span"); label.className = "quota-category-label";
        const swatch = document.createElement("i"); swatch.style.background = item.color;
        const name = document.createElement("span");
        name.textContent = item.role === "remote" ? context.t("其他服务器附件") : quotaCategoryLabel(context, item.category);
        label.append(swatch, name); return label;
      }, item.measured === false ? context.t("待计量") : quotaBytes(item.bytes),
        item.percent === null || item.measured === false ? "未计入" : `${item.percent.toFixed(1)}%`,
        item.artifact_count ?? "—", () => {
          if (item.role !== "output") return context.t(
            item.role === "protected" || item.role === "input" ? "受保护" :
              item.role === "profile" ? "由所属页面管理" : "请在来源服务器查看");
          const actions = document.createElement("span");
          actions.append(FTUI.iconButton(context, "list.bullet", "查看附件", () => {
            selectedCategory = item.category; offset = 0;
            void refreshItems().catch(error => context.showNotice(error.message, true));
          }));
          if (eligibleCategories.some(entry => entry.category === item.category)) {
            actions.append(FTUI.iconButton(context, "trash", "清理此类别的已结束 Job 输出", () => {
              void clearOutputs(item.category);
            }));
          }
          return actions;
        }],
    });
    itemTable = FTManagerAccessTable.create(context, {
      headers: ["任务", "附件", "大小", "操作"], searchPlaceholder: "筛选当前批次",
      empty: "此类别暂无附件", refresh: refreshItems,
      searchText: item => `${item.job_id} ${item.name}`,
      cells: item => [item.job_id, item.name, quotaBytes(item.size_bytes), () => {
        if (item.role !== "output") return context.t("受保护");
        return FTUI.iconButton(context, "trash", "删除此输出附件", async () => {
          const message = `${context.t("删除附件")} ${item.name} (${quotaBytes(item.size_bytes)})?\n${context.t("如果研究报告挂载此任务，详细结果可能无法显示；Job 摘要仍保留。")}`;
          if (!window.confirm(message)) return;
          const path = `/api/jobs/${encodeURIComponent(item.job_id)}/artifacts/${encodeURIComponent(item.name)}`;
          try {
            await context.api(path, {method: "DELETE"});
            context.showNotice(context.t("附件已删除"));
            await refresh();
          } catch (error) {
            context.showNotice(error.message, true);
          }
        });
      }],
    });
    summary.append(rows, bar, cleanupButton);
    categorySection.append(categoryHeading, categoryTable.root);
    itemsSection.append(itemHeading, itemTable.root, pager);
    body.append(summary, categorySection, itemsSection);
    await refresh();
  }

  async function server(context, body) {
    body.append(pageHeader(context.t("服务器"), context.t("配置 Manager 与当前 FactorTester 服务端口"), "server.rack"));
    const [ports, manifest] = await Promise.all([
      context.api("/api/jobs/ports"),
      context.api("/api/test-authoring/modules/group_test"),
    ]);
    if (!current(context)) return;
    // Settings only needs backend-declared field metadata.  Do not load the
    // entire test run workbench just to look up this one service-port field.
    const servicePort = (manifest?.run_fields || []).find(item => (
      item?.key === "service_port"
    ));
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
      context.t("客户端继续使用 7998/7997；服务器通过 WireGuard 17998/17997 互联"),
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
    const bootstrapURL = document.createElement("input");
    bootstrapURL.className = "inline-setting"; bootstrapURL.type = "url";
    bootstrapURL.placeholder = "http://10.77.0.2:17998/api/federation/register";
    bootstrapURL.value = config.bootstrap_url || "";
    const endpoint = document.createElement("input");
    endpoint.className = "inline-setting"; endpoint.type = "url";
    endpoint.placeholder = "https://client-visible-host:7998";
    endpoint.value = config.public_endpoint || "";
    const token = document.createElement("input");
    token.className = "inline-setting"; token.type = "password";
    token.autocomplete = "new-password";
    token.placeholder = config.registration_token_configured
      ? context.t("已配置 · 留空保持不变") : context.t("引导登记令牌");
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
          bootstrap_url: bootstrapURL.value.trim(),
          public_endpoint: endpoint.value.trim(),
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
      [context.t("启用互联"), context.t("开启后本机通过 WireGuard 17998 向引导服务器登记；关闭后停止心跳"), enabled],
      [context.t("引导服务器地址"), context.t("只需填写一台已授权服务器的 WireGuard 17998 注册接口；其他节点由服务器目录发现"), bootstrapURL],
      [context.t("客户端控制地址"), context.t("提供给 Web、Swift 与 CLI 的 7998 地址；不用于服务器间字节流"), endpoint],
      [context.t("登记令牌"), context.t("与引导 Manager 预共享的一次性或受限登记令牌"), token],
      [context.t("心跳间隔（秒）"), context.t("只用于向引导 Manager 登记续租；跨服务器任务列表按需查询"), interval],
      [context.t("对外提供的服务端口"), context.t("自动登记当前在线的所有服务端口；新建 issue worktree 并启动后会自动出现在互联节点目录"), ports],
      [context.t("状态"), context.t("当前 Manager 互联状态"), status],
      [context.t("跨服务器任务"), context.t("打开任务列表的“跨服务器任务”选项卡时，经 WireGuard 17998 并行查询各节点"), syncStatus],
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
      : context.t("访客模式语言仅保存在当前浏览器，不同步用户账户");
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
