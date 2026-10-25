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

  function quotaGroupLabel(context, group) {
    return context.t({
      "output:data": "测试任务生成物（数据）",
      "output:image": "测试任务生成物（图片）",
      "output:historical": "测试任务生成物（历史未分类）",
      "input:factor": "因子数据",
      "input:strategy": "策略数据",
      "input:product": "产品分类与产品组数据",
      "input:other": "其他任务提交数据",
      "profile:research_reports": "研究报告",
      "profile:profile_uploads": "研究身份上传文件",
      "profile:profile_workspaces": "研究身份工作区",
      "protected:factors": "因子目录元数据",
      "protected:product_groups": "产品组目录元数据",
      "protected:other": "其他研究资料元数据",
    }[group] || group);
  }

  async function quota(context, body) {
    body.append(pageHeader(context.t("存储配额"), context.t("跨服务器汇总与按任务清理"), "externaldrive"));
    if (!context.session) {
      body.append(card(context.t("存储配额"), [["需要登录", "登录后查看个人配额", "不可用"]]));
      return;
    }
    const overview = document.createElement("section"); overview.className = "settings-section quota-overview";
    const heading = document.createElement("div"); heading.className = "quota-overview-heading";
    const headline = document.createElement("strong");
    const actions = document.createElement("div"); actions.className = "quota-overview-actions";
    const refreshButton = FTUI.refreshButton(context, () => refresh());
    const autoButton = FTUI.actionButton(context.t("自动删除可清理类别"),
      () => { void clearScope(); });
    actions.append(refreshButton, autoButton);
    heading.append(headline, actions);
    const bar = document.createElement("div"); bar.className = "quota-segments";
    bar.setAttribute("role", "progressbar"); bar.setAttribute("aria-valuemin", "0");
    const status = document.createElement("p"); status.className = "quota-status";
    overview.append(heading, bar, status);
    const tableSection = document.createElement("section"); tableSection.className = "settings-section quota-categories";
    const tableMount = document.createElement("div");
    tableSection.append(tableMount);
    body.append(overview, tableSection);
    headline.textContent = context.t("正在读取配额…");
    status.textContent = context.t("正在读取最近一次完整计量记录");
    tableMount.textContent = context.t("正在读取占用分类…");

    const dialog = window.FTUI.dialogRoot(context); dialog.className = "quota-dialog";
    const dialogCard = document.createElement("div"); dialogCard.className = "dialog-card wide";
    const dialogHead = document.createElement("div"); dialogHead.className = "quota-dialog-heading";
    const dialogTitle = document.createElement("h2");
    const closeButton = FTUI.iconButton(context, "xmark", "关闭", () => dialog.close());
    dialogHead.append(dialogTitle, closeButton);
    const dialogBody = document.createElement("div");
    dialogCard.append(dialogHead, dialogBody); dialog.append(dialogCard);
    body.append(dialog);
    let servers = [], profile = null, pending = [], quotaSize = 0, quotaKnown = false;
    let refreshVersion = 0;
    let liveLoading = false, liveFailed = false;
    const groupColors = {"output:data": "#2775dc", "output:image": "#7455c4",
      "output:historical": "#527dad",
      "input:factor": "#e4a529", "input:strategy": "#39a56d",
      "input:product": "#d36161", "input:other": "#8a8f98",
      "profile:research_reports": "#25a28b",
      "profile:profile_uploads": "#cf754b",
      "profile:profile_workspaces": "#a354af"};
    const queryServer = (serverID, params = {}) => {
      const query = new URLSearchParams(params);
      if (serverID) query.set("server_id", serverID);
      return context.api(`/api/jobs/storage?${query}`);
    };
    const deleteServer = (serverID, preview, params = {}) => {
      const query = new URLSearchParams({cleanup: "eligible",
        expected_count: String(preview.artifact_count),
        expected_bytes: String(preview.bytes), expected_token: String(preview.token), ...params});
      if (serverID) query.set("server_id", serverID);
      return context.api(`/api/jobs/artifacts?${query}`, {method: "DELETE"});
    };
    async function clearScope(group = "") {
      const targets = servers.map(server => ({server,
        preview: group && group !== "output:historical"
          ? (server.data.cleanup_business_groups || []).find(item => item.group === group)
          : server.data.cleanup_preview,
      })).filter(item => !item.server.snapshot && group !== "output:historical" &&
        Number(item.preview?.artifact_count) > 0);
      const offline = group && group !== "output:historical" ? [] : servers.filter(server =>
        server.snapshot && Number(server.data.output_bytes) > 0 &&
        !pending.some(item => item.server_id === server.id &&
          ["pending", "executing"].includes(item.status)));
      if (!targets.length && !offline.length) return;
      const count = targets.reduce((sum, item) => sum + Number(item.preview.artifact_count), 0) +
        offline.reduce((sum, server) => sum + Number(server.data.output_count || 0), 0);
      const bytes = targets.reduce((sum, item) => sum + Number(item.preview.bytes), 0) +
        offline.reduce((sum, server) => sum + Number(server.data.output_bytes), 0);
      const label = group ? quotaGroupLabel(context, group) : context.t("全部可删除类别");
      if (!window.confirm(`${context.t("删除整类")} ${label}：${count} ${context.t("项生成物")}` +
          `，${quotaBytes(bytes)}？\n${offline.length ? context.t("离线服务器将安排上线后删除，立即从逻辑配额扣除；执行前可取消。") + "\n" : ""}` +
          context.t("报告中的任务结果查看器可能失效；提交输入与基础数据保留。"))) return;
      let deleted = 0, queued = 0; const failures = [];
      for (const {server, preview} of targets) {
        try {
          const result = await deleteServer(server.id, preview, group ? {group} : {});
          deleted += Number(result.deleted_artifacts || 0);
          if (result.failed_files) failures.push(`${server.id}: ${result.failed_files} ${context.t("个文件未移除")}`);
        } catch (error) { failures.push(`${server.id}: ${error.message}`); }
      }
      for (const server of offline) {
        try {
          const request = await context.api("/api/storage/deferred-job-cleanup", {
            method: "POST", body: JSON.stringify({
              server_id: server.id, expected_bytes: server.data.output_bytes,
              expected_count: server.data.output_count,
              observed_at: server.observedAt,
            }),
          });
          pending = [request, ...pending.filter(item => item.server_id !== server.id)];
          queued++;
        } catch (error) { failures.push(`${server.id}: ${error.message}`); }
      }
      context.showNotice(`${context.t("已删除")} ${deleted} ${context.t("项")}` +
        (queued ? `；${context.t("已安排离线清理")} ${queued} ${context.t("台服务器")}` : "") +
        (failures.length ? `；${failures.join("；")}` : ""), Boolean(failures.length));
      if (queued) render();
      void refresh();
    }

    async function openJobs(group) {
      dialogTitle.textContent = `${quotaGroupLabel(context, group)} · ${context.t("测试任务")}`;
      dialogBody.replaceChildren(); dialog.showModal();
      let offsets = Object.fromEntries(servers.filter(server => !server.snapshot)
        .map(server => [server.id, 0]));
      const done = new Set();
      let jobs = [], hasMore = false;
      const list = document.createElement("div");
      const more = FTUI.actionButton(context.t("加载更多任务"), () => { void load(); });
      dialogBody.append(list, more);
      const render = () => {
        const rows = jobs.map(({serverID, job}) => {
          const destination = `/jobs/${encodeURIComponent(job.job_id)}?server_id=${encodeURIComponent(serverID)}`;
          const link = document.createElement("a");
          link.href = destination;
          link.textContent = `${job.job_kind || context.t("测试任务")} · ${job.job_id}`;
          link.onclick = event => {
            event.preventDefault();
            dialog.close();
            context.navigate(destination);
          };
          const remove = FTUI.iconButton(context, "trash", "删除此任务的全部生成物", async () => {
            try {
              const detail = await queryServer(serverID, {job_id: job.job_id});
              const preview = detail.job_cleanup_preview;
              if (!Number(preview?.artifact_count)) { await refresh(); return; }
              if (!window.confirm(`${context.t("删除任务生成物")} ${job.job_id}：` +
                  `${quotaBytes(preview.bytes)}？\n${context.t("提交输入与任务摘要保留，报告中的结果查看器可能失效。")}`)) return;
              await deleteServer(serverID, preview, {job_id: job.job_id});
              context.showNotice(context.t("任务生成物已删除"));
              dialog.close(); await refresh();
            } catch (error) { context.showNotice(error.message, true); }
          });
          remove.disabled = !["succeeded", "failed", "cancelled"].includes(job.job_status);
          return [link, serverID, quotaBytes(job.bytes), job.job_status, remove];
        });
        list.replaceChildren(FTUI.table([
          context.t("任务"), context.t("存储服务器"), context.t("本类占用"),
          context.t("状态"), context.t("操作"),
        ], rows).shell);
        more.hidden = !hasMore;
      };
      const load = async () => {
        more.disabled = true;
        const pending = servers.filter(server => !server.snapshot && !done.has(server.id));
        const pages = await Promise.allSettled(pending.map(server =>
          queryServer(server.id, {group, limit: 100, offset: offsets[server.id]})));
        hasMore = false;
        pages.forEach((result, index) => {
          const server = pending[index];
          if (result.status !== "fulfilled") {
            hasMore = true;
            context.showNotice(`${server.id}: ${result.reason.message}`, true); return;
          }
          const page = result.value;
          const batch = page.jobs || [];
          jobs.push(...batch.map(job => ({serverID: server.id, job})));
          offsets[server.id] += batch.length;
          if (offsets[server.id] < Number(page.job_count || 0)) hasMore = true;
          else done.add(server.id);
        });
        more.disabled = false; render();
      };
      await load();
    }

    function openHistoricalOutputs() {
      const snapshots = servers.filter(server => server.snapshot &&
        Number(server.data.output_bytes) > 0);
      dialogTitle.textContent = context.t("测试任务生成物 · 最近一次记录");
      const explanation = document.createElement("p");
      explanation.textContent = context.t(
        "离线服务器的输出可安排上线后删除。待执行期间只从逻辑配额中扣除，文件仍在原服务器；执行开始前可取消。服务器上线后会重新核对清单，若与历史记录不符则停止删除并恢复计费。",
      );
      const rows = snapshots.map(server => {
        const request = pending.find(item => item.server_id === server.id &&
          ["pending", "executing"].includes(item.status));
        const action = request
          ? FTUI.iconButton(context, "xmark", request.status === "pending"
            ? "取消待删除" : "正在执行，无法取消", async () => {
            if (request.status !== "pending") return;
            try {
              await context.api(`/api/storage/deferred-job-cleanup/${request.request_id}`,
                {method: "DELETE"});
              pending = pending.filter(item => item.request_id !== request.request_id);
              dialog.close(); render(); void refresh();
            } catch (error) { context.showNotice(error.message, true); }
          })
          : FTUI.iconButton(context, "trash", "上线后删除此服务器的生成物", async () => {
            if (!window.confirm(`${context.t("安排上线后删除")} ${server.id} · ` +
                `${quotaBytes(server.data.output_bytes)}？\n` +
                context.t("待执行期间逻辑配额立即释放；执行前可取消。报告中的任务结果查看器可能失效。"))) return;
            try {
              const request = await context.api("/api/storage/deferred-job-cleanup", {
                method: "POST", body: JSON.stringify({
                  server_id: server.id,
                  expected_bytes: server.data.output_bytes,
                  expected_count: server.data.output_count,
                  observed_at: server.observedAt,
                }),
              });
              pending = [request, ...pending.filter(item => item.server_id !== server.id)];
              dialog.close(); render(); void refresh();
            } catch (error) { context.showNotice(error.message, true); }
          });
        if (request?.status === "executing") action.disabled = true;
        return [server.id, quotaBytes(server.data.output_bytes),
          server.data.output_count || "—", server.observedAt || "—",
          request ? context.t(request.status === "pending"
            ? "待执行 · 不计配额" : "执行中 · 不计配额") : context.t("计入配额"), action];
      });
      dialogBody.replaceChildren(explanation, FTUI.table([
        context.t("存储服务器"), context.t("占用"),
        context.t("生成物数"), context.t("最近计量时间"),
        context.t("状态"), context.t("操作"),
      ], rows).shell);
      dialog.showModal();
    }

    function render() {
      if (!current(context)) return;
      const categories = new Map();
      const add = (group, bytes, count, observedAt = "", credit = 0) => {
        if (!Number(bytes || 0) && !Number(count || 0)) return;
        const item = categories.get(group) || {group, bytes: 0, billedBytes: 0, count: 0,
          lastObserved: []};
        item.bytes += Number(bytes || 0);
        item.billedBytes += Math.max(0, Number(bytes || 0) - Number(credit || 0));
        item.count += Number(count || 0);
        if (observedAt) item.lastObserved.push(observedAt);
        categories.set(group, item);
      };
      servers.forEach(server => {
        let credit = pending.filter(item => item.server_id === server.id &&
          ["pending", "executing"].includes(item.status)).reduce((sum, item) =>
          sum + Number(item.credit_bytes || 0), 0);
        const groups = server.data.business_groups || [];
        groups.forEach(item => {
          const deducted = item.quota_group.startsWith("output:")
            ? Math.min(credit, Number(item.bytes || 0)) : 0;
          add(item.quota_group, item.bytes, item.job_count,
            server.observedAt, deducted);
          credit -= deducted;
        });
        if (server.snapshot) {
          add("output:historical", server.data.output_bytes,
            server.data.output_count, server.observedAt,
            Math.min(credit, Number(server.data.output_bytes || 0)));
          add("input:other", server.data.input_bytes,
            server.data.input_count, server.observedAt);
        }
      });
      const protectedMetadata = profile?.protected_metadata || {};
      for (const [key, group] of [["factors", "input:factor"],
        ["product_groups", "input:product"], ["strategies", "input:strategy"],
        ["other", "protected:other"]]) {
        if (protectedMetadata[key]) add(group, protectedMetadata[key].bytes,
          protectedMetadata[key].item_count);
      }
      const profileServers = new Map();
      (profile?.profile_snapshots || []).forEach(server => {
        if (server.inventory) profileServers.set(server.storage_server_id, server);
      });
      (profile?.cross_server?.servers || []).forEach(server => {
        if (!server.inventory) return;
        const previous = profileServers.get(server.storage_server_id);
        const observed = value => {
          const raw = value?.inventory?.observed_at;
          return typeof raw === "number" ? raw * 1000 : Date.parse(raw || "") || 0;
        };
        if (!previous || observed(server) >= observed(previous))
          profileServers.set(server.storage_server_id, server);
      });
      profileServers.forEach(server => {
        Object.entries(server.inventory.categories || {}).forEach(([key, value]) =>
          add(`profile:${key}`, value.bytes, value.file_count,
            server.status === "current" ? "" : server.inventory.observed_at));
      });
      const measured = [...categories.values()].reduce((sum, item) => sum + item.billedBytes, 0);
      const pendingBytes = [...categories.values()].reduce((sum, item) =>
        sum + item.bytes - item.billedBytes, 0);
      const percent = quotaSize > 0 ? 100 * measured / quotaSize : 0;
      const partial = !profile || !profile.protected_metadata;
      headline.textContent = `${quotaBytes(measured)} / ${quotaBytes(quotaSize)}` +
        ` · ${partial ? context.t("至少") + " " : ""}${percent.toFixed(1)}%`;
      status.textContent = (measured > quotaSize
        ? `${context.t("已核实用量已超额")} ${quotaBytes(measured - quotaSize)}。`
        : "") + (partial ? context.t("部分存储类别暂时无法计量。") : "") +
        (liveLoading ? context.t("正在更新实时用量…") :
          liveFailed ? context.t("部分实时读取失败，显示最近一次记录。") : "") +
        (pendingBytes ? `${context.t("待删除但仍占磁盘：")} ${quotaBytes(pendingBytes)}。` : "");
      bar.replaceChildren();
      bar.classList.toggle("quota-over-limit", quotaSize > 0 && measured > quotaSize);
      bar.setAttribute("aria-valuemax", String(quotaSize || 1));
      bar.setAttribute("aria-valuenow", String(measured));
      bar.setAttribute("aria-valuetext", `${quotaBytes(measured)} / ${quotaBytes(quotaSize)}`);
      let usedWidth = 0;
      const widthBase = Math.max(quotaSize, measured);
      [...categories.values()].filter(item => item.billedBytes).forEach(item => {
        const width = widthBase > 0 ? Math.max(0, Math.min(100 - usedWidth,
          100 * item.billedBytes / widthBase)) : 0;
        if (!width) return;
        const segment = document.createElement("span");
        segment.style.width = `${width}%`;
        segment.style.background = groupColors[item.group] || "#8a8f98";
        segment.title = `${quotaGroupLabel(context, item.group)} · ${quotaBytes(item.billedBytes)}`;
        bar.append(segment); usedWidth += width;
      });
      autoButton.disabled = !servers.some(server =>
        server.snapshot ? Number(server.data.output_bytes) > 0 &&
          !pending.some(item => item.server_id === server.id &&
            ["pending", "executing"].includes(item.status))
          : Number(server.data.cleanup_preview?.artifact_count) > 0);
      const rows = [...categories.values()].sort((a, b) => b.bytes - a.bytes).map(item => {
        const label = document.createElement("span"); label.className = "quota-category-label";
        const swatch = document.createElement("i");
        swatch.style.background = groupColors[item.group] || "#8a8f98";
        label.append(swatch, document.createTextNode(quotaGroupLabel(context, item.group)));
        if (item.lastObserved.length) label.title = `${context.t("包含最近一次记录：")} ${item.lastObserved.join("、")}`;
        const controls = document.createElement("span"); controls.className = "quota-row-actions";
        if (item.group.startsWith("output:")) {
          if (item.group === "output:historical") {
            controls.append(FTUI.iconButton(context, "list.bullet.clipboard",
              "查看最近一次占用记录", openHistoricalOutputs));
            controls.append(FTUI.iconButton(context, "trash",
              "删除整个类别", () => { void clearScope("output:historical"); }));
          }
          if (servers.some(server => !server.snapshot && (server.data.business_groups || [])
              .some(candidate => candidate.quota_group === item.group))) {
            controls.append(FTUI.iconButton(context, "list.bullet.clipboard", "查看测试任务", () => {
              void openJobs(item.group).catch(error => context.showNotice(error.message, true));
            }));
          }
          if (servers.some(server => (server.data.cleanup_business_groups || []).some(
              candidate => candidate.group === item.group && candidate.artifact_count))) {
            controls.append(FTUI.iconButton(context, "trash", "删除整个类别", () => {
              void clearScope(item.group);
            }));
          }
        } else controls.textContent = context.t("受保护");
        const size = item.billedBytes === item.bytes ? quotaBytes(item.bytes)
          : `${quotaBytes(item.billedBytes)} / ${quotaBytes(item.bytes)} ${context.t("物理占用")}`;
        return [label, size, item.lastObserved.length
          ? context.t("含最近一次占用记录") : context.t("当前测量"),
          item.count || "—", controls];
      });
      tableMount.replaceChildren(FTUI.table([
        context.t("类别"), context.t("占用"), context.t("计量范围"),
        context.t("任务或文件数"), context.t("操作"),
      ], rows).shell);
    }
    async function refresh() {
      const version = ++refreshVersion;
      const isCurrent = () => current(context) && version === refreshVersion;
      const firstPaint = !profile && !servers.length;
      liveLoading = true; liveFailed = false; refreshButton.disabled = true;
      if (firstPaint) {
        try {
          const snapshot = await context.api("/api/storage/profile-inventory?snapshot=1");
          if (!isCurrent()) return;
          profile = snapshot;
          quotaSize = Number(snapshot.quota_bytes || 0);
          quotaKnown = true;
          servers = (snapshot.job_snapshots || []).map(row => ({
            id: row.storage_server_id, data: row, snapshot: true,
            observedAt: row.observed_at,
          }));
          pending = snapshot.deferred_output_cleanups || [];
          if (servers.length || (snapshot.profile_snapshots || []).length ||
              Object.values(snapshot.protected_metadata || {}).some(row => Number(row.bytes))) {
            render();
          }
        } catch (_) {
          // A missing control-store snapshot does not prevent live inventory.
        }
      }
      if (!isCurrent()) return;
      const profileRequest = context.api("/api/storage/profile-inventory")
        .then(value => {
          if (!isCurrent()) return;
          profile = value;
          if (quotaKnown) render();
        })
        .catch(() => { if (isCurrent()) liveFailed = true; });
      const pendingRequest = context.api("/api/storage/deferred-job-cleanup")
        .then(value => { if (isCurrent()) { pending = value.requests || []; if (quotaKnown) render(); } })
        .catch(() => { if (isCurrent()) liveFailed = true; });
      const jobsRequest = context.api("/api/jobs/storage").then(async root => {
        if (!isCurrent()) return;
        quotaSize = Number(root.quota_bytes ?? quotaSize);
        quotaKnown = true;
        const ids = [...new Set((root.servers || [])
          .map(item => String(item.storage_server_id || ""))
          .concat(String(root.storage_server_id || "")).filter(Boolean))];
        servers = ids.map(id => {
          if (id === root.storage_server_id) return {id, data: root, snapshot: false};
          const data = (root.servers || []).find(row => row.storage_server_id === id);
          return data ? {id, data, snapshot: true, observedAt: data.observed_at} : null;
        }).filter(Boolean);
        render();
        await Promise.allSettled(servers.filter(server => server.snapshot).map(async server => {
          try {
            const data = await queryServer(server.id);
            if (!isCurrent() || data.storage_server_id !== server.id) return;
            const index = servers.findIndex(item => item.id === server.id);
            if (index < 0) return;
            servers[index] = {id: server.id, data, snapshot: false};
            render();
          } catch (_) {
            if (isCurrent()) liveFailed = true;
          }
        }));
      }).catch(error => {
        if (!isCurrent()) return;
        liveFailed = true;
        context.showNotice(error.message, true);
      });
      await Promise.allSettled([profileRequest, jobsRequest, pendingRequest]);
      if (!isCurrent()) return;
      liveLoading = false; refreshButton.disabled = false;
      if (quotaKnown) render();
      else {
        headline.textContent = context.t("暂时无法读取配额");
        status.textContent = context.t("请稍后重试");
      }
    }
    void refresh().catch(error => context.showNotice(error.message, true));
  }

  async function server(context, body) {
    body.append(pageHeader(context.t("服务器"), context.t("配置 Manager 与当前 TradeResearch 服务端口"), "server.rack"));
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
    body.append(card(context.t("TradeResearch 服务端口"), [
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
      [context.t("更新来源"), context.t("由当前 TradeResearch 服务返回并经 7998 转发"), release.url || context.t("TradeResearch 服务")],
    ]));
  }

  window.FTSettings = {show};
})();
