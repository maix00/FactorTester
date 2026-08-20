(() => {
  // List formatting is shared by the list and detail page, but the list
  // controller owns pagination, scope state, and navigation only.
  const {
    artifactCell, date, displayProfile, formatBytes, jobPort, kindTitle,
    scalar, serverLabel, statusPill, table, taskCell, taskHash, taskTitle, text,
  } = FTJobListFormat;

  const pageSize = 20;
  // A submission can finish while the pinned task-list tab is cached in a
  // different tab session.  This process-local generation invalidates those
  // caches without forcing every visit to fan out across every server.
  let cacheGeneration = 0;
  const scopeDefinitions = [
    {id: "server", title: "服务器任务"},
    {id: "cross-server", title: "跨服务器任务"},
    {id: "mine", title: "本账号任务"},
    {id: "subordinates", title: "下级用户任务"},
  ];

  function sessionKey(context) {
    if (!context.session) return "anonymous";
    return `${context.session.username || ""}:${context.session.role || "user"}`;
  }

  function freshScopeState() {
    return {
      page: 1, pages: {}, cursors: [""], lastPage: 1,
      total: 0, totalPages: 1, users: [], username: "",
    };
  }

  function scopeState(context) {
    const existing = context.tabSession.jobLists;
    const identity = sessionKey(context);
    if (existing && existing.byScope && existing.identityKey === identity
        && existing.cacheGeneration === cacheGeneration) return existing;
    // The server feed is the default for both anonymous and authenticated
    // visits.  Private scopes remain available as explicit account tabs, and
    // a pending private tab survives the login round-trip.
    const initial = "server";
    const value = {
      identityKey: identity,
      cacheGeneration,
      activeScope: initial,
      byScope: {
        mine: freshScopeState(),
        subordinates: freshScopeState(),
        server: freshScopeState(),
        "cross-server": freshScopeState(),
      },
    };
    context.tabSession.jobLists = value;
    return value;
  }

  function invalidate() {
    cacheGeneration += 1;
  }

  function publicScopeNote(context, payload = null) {
    const note = document.createElement("p");
    note.className = "job-scope-note";
    const fullServerView = payload && typeof payload.public === "boolean"
      ? payload.public === false
      : Boolean(context.session?.capabilities?.manager
        || context.session?.role === "super_admin");
    note.textContent = !context.session
      ? context.t("未登录时仅显示服务器公开任务（最多 20 个）")
      : fullServerView
      ? context.t("管理员可查看服务器全部任务")
      : context.t("服务器任务仅显示最新 20 个");
    return note;
  }

  function scopeTabs(context, state) {
    const root = document.createElement("div"); root.className = "job-scope-tabs";
    scopeDefinitions.forEach(definition => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "job-scope-tab";
      if (definition.id === state.activeScope) button.classList.add("selected");
      button.textContent = context.t(definition.title);
      button.title = button.textContent;
      button.addEventListener("click", () => {
        // Keep the selected scope in the URL.  This preserves an intentional
        // private scope through the login round-trip; reopening the pinned
        // 测试 feature itself defaults to the separate 测试类型 tab.
        context.navigate(`/jobs?scope=${encodeURIComponent(definition.id)}`);
      });
      root.append(button);
    });
    return root;
  }

  function installScopeToolbar(context, state, scope) {
    context.toolbar.replaceChildren(
      FTTestPageTabs.render(context, "tasks"),
      context.button(
        "↻", () => list(context, null, scope, {forceRefresh: true}),
        context.t("刷新任务列表"),
      ),
    );
  }

  async function fetchPage(context, state, scope, targetPage, options = {}) {
    const page = Math.max(1, Math.min(1000, Number(targetPage) || 1));
    const scoped = state.byScope[scope];
    if (!scoped) throw new Error(context.t("不支持的任务范围"));
    if (scope !== "server") {
      if (!options.forceRefresh && scoped.pages[page]) {
        return {...scoped.pages[page], page};
      }
      const query = new URLSearchParams({
        scope, limit: String(pageSize), page: String(page),
      });
      if (scope === "subordinates" && scoped.username) {
        query.set("username", scoped.username);
      }
      const payload = await context.api(`/api/jobs?${query.toString()}`);
      scoped.pages[page] = payload;
      scoped.page = Number(payload.page || page);
      scoped.total = Number(payload.total || 0);
      scoped.totalPages = Number(payload.total_pages || 1);
      scoped.users = Array.isArray(payload.users) ? payload.users : scoped.users;
      return {...payload, page: scoped.page};
    }
    let resolvedPage = page;
    for (let number = 1; number <= page; number += 1) {
      if (scoped.pages[number]) continue;
      const cursor = scoped.cursors[number - 1] || "";
      const query = new URLSearchParams({
        scope: "server", limit: String(pageSize), page: String(number),
      });
      if (cursor) query.set("cursor", cursor);
      const payload = await context.api(`/api/jobs?${query.toString()}`);
      scoped.pages[number] = payload;
      scoped.cursors[number] = String(payload.next_cursor || "");
      scoped.lastPage = number;
      scoped.total = Number(payload.total || 0);
      scoped.totalPages = Number(payload.total_pages || 1);
      if (!payload.has_more && number < page) {
        resolvedPage = number;
        break;
      }
    }
    return {
      ...(scoped.pages[resolvedPage] || scoped.pages[scoped.lastPage] || {
        jobs: [], has_more: false, next_cursor: null,
      }),
      page: resolvedPage,
      total: scoped.total,
      total_pages: scoped.totalPages,
    };
  }

  function userPicker(context, state, payload) {
    const root = document.createElement("div"); root.className = "job-user-picker";
    const label = document.createElement("label");
    label.textContent = context.t("选择下级用户");
    const select = document.createElement("select");
    const placeholder = document.createElement("option");
    placeholder.value = ""; placeholder.textContent = context.t("请选择");
    select.append(placeholder);
    const users = Array.isArray(payload.users) && payload.users.length ? payload.users : (state.users || []);
    users.forEach(user => {
      const option = document.createElement("option");
      option.value = user.username;
      option.textContent = user.title && user.title !== user.username
        ? `${user.title}（${user.username}）` : user.username;
      option.selected = user.username === state.username;
      select.append(option);
    });
    select.addEventListener("change", () => {
      state.username = select.value;
      state.page = 1; state.pages = {};
      list(context, 1, "subordinates");
    });
    label.append(select); root.append(label);
    if (!users.length) {
      const note = document.createElement("p");
      note.className = "job-scope-note";
      note.textContent = context.t("当前账户没有可查看的下级用户");
      root.append(note);
    }
    return root;
  }

  function pagination(context, state, scope, page, hasMore, totalPages, total) {
    const root = document.createElement("div"); root.className = "job-pagination";
    const previous = context.button(context.t("上一页"), () => list(context, page - 1, scope), context.t("上一页"));
    previous.disabled = page <= 1;
    const label = document.createElement("span"); label.className = "job-page-label";
    const pageText = context.t("第 %lld / %lld 页")
      .replace("%lld", String(page)).replace("%lld", String(Math.max(1, totalPages || 1)));
    const totalText = context.t("共 %lld 个任务，每页 %lld 个")
      .replace("%lld", String(total || 0)).replace("%lld", String(pageSize));
    label.textContent = `${pageText} · ${totalText}`;
    const next = context.button(context.t("下一页"), () => list(context, page + 1, scope), context.t("下一页"));
    next.disabled = !hasMore;
    const divider = document.createElement("span"); divider.className = "job-pagination-divider";
    divider.textContent = "";
    const caption = document.createElement("span"); caption.className = "job-pagination-caption";
    caption.textContent = context.t("跳转");
    const input = document.createElement("input"); input.type = "number"; input.min = "1"; input.max = "1000";
    input.value = String(page); input.placeholder = context.t("页码"); input.setAttribute("aria-label", context.t("页码"));
    const jump = context.button(context.t("确定"), () => list(context, Number(input.value) || page, scope), context.t("跳转"));
    input.addEventListener("keydown", event => {
      if (event.key === "Enter") jump.click();
    });
    root.append(previous, label, next, divider, caption, input, jump);
    return root;
  }

  async function list(
    context, requestedPage = null, requestedScope = null, options = {},
  ) {
    const isCurrent = () => context.isRouteCurrent?.() !== false;
    if (!isCurrent()) return;
    FTJobProgress.stopProgress();
    context.activeNav("jobs"); context.setHeading(context.t("测试"));
    context.content.replaceChildren(FTUI.loading(context.t("正在读取跨端口任务…")));
    const state = scopeState(context);
    const urlScope = new URLSearchParams(location.search).get("scope");
    const declaredScope = scopeDefinitions.some(item => item.id === urlScope)
      ? urlScope : null;
    const scope = requestedScope || declaredScope || "server";
    state.activeScope = scope;
    const scoped = state.byScope[scope];
    installScopeToolbar(context, state, scope);
    // Keep a populated scope when navigating away and back.  The old code
    // discarded it before every request, turning every tab switch into a
    // cold federation fan-out.  The toolbar remains the explicit refresh
    // control and clears the cached page through this flag.
    if (options.forceRefresh) {
      Object.assign(scoped, freshScopeState());
    }
    const requested = Math.max(1, Math.min(1000, Number(requestedPage == null ? 1 : requestedPage) || 1));
    let payload;
    try {
      payload = await fetchPage(
        context, state, scope, requested, options,
      );
    } catch (error) {
      if (!isCurrent()) return;
      const root = document.createElement("div"); root.className = "jobs-page";
      if (scope === "server") root.append(publicScopeNote(context));
      root.append(scopeTabs(context, state));
      const failure = FTUI.empty(context.t("任务列表读取失败"), text(error.message || error));
      failure.append(context.button(
        context.t("重试"),
        () => list(context, null, scope, {forceRefresh: true}),
        context.t("重新读取任务列表"),
      ));
      if (scope === "subordinates") {
        root.append(userPicker(context, scoped, {users: scoped.users}));
      }
      root.append(failure);
      if (scope === "subordinates") {
        root.append(pagination(
          context, scoped, scope, scoped.page || 1, false,
          scoped.totalPages || 1, scoped.total || 0,
        ));
      }
      context.content.replaceChildren(root);
      return;
    }
    if (!isCurrent()) return;
    const root = document.createElement("div"); root.className = "jobs-page";
    if (scope === "server") root.append(publicScopeNote(context, payload));
    root.append(scopeTabs(context, state));
    if (payload.requires_login) {
      root.append(context.loginRequiredView());
      context.content.replaceChildren(root); return;
    }
    if (scope === "subordinates") {
      // Keep the selected-user control mounted for every page, including an
      // empty result.  The query is part of the list state and must not be
      // discarded when the user changes page or receives no rows.
      root.append(userPicker(context, scoped, payload));
    }
    if (scope === "subordinates" && payload.selection_required) {
      const note = FTUI.empty(context.t("请选择下级用户"), context.t("选择后加载该用户的任务"));
      root.append(note);
      root.append(pagination(context, scoped, scope, 1, false, 1, 0));
      context.content.replaceChildren(root); return;
    }
    const page = payload.page || requested;
    scoped.page = page;
    const jobs = payload.jobs || [];
    if (!jobs.length) {
      root.append(FTUI.empty(
        page > 1 ? context.t("没有更多测试任务") : context.t("暂无测试任务"),
        context.t("Web、CLI 与研究 Agent 提交的任务都会在这里显示"),
      ));
      root.append(pagination(context, scoped, scope, page, Boolean(payload.has_more), Number(payload.total_pages || 1), Number(payload.total || 0)));
      context.content.replaceChildren(root);
      return;
    }
   const result = FTUI.table([context.t("任务"), context.t("服务器"), context.t("端口"), context.t("时间"), context.t("状态"), context.t("Profile"), context.t("生成物"), context.t("提交物")], jobs.map(job => [
      taskCell(job, context), serverLabel(job, context), jobPort(job.execution_port) || jobPort(job.port) || context.t("未知"), date(job.updated_at), statusPill(job.status, context), displayProfile(job, context), artifactCell(job, "output", context), artifactCell(job, "input", context),
    ]));
    [...result.body.rows].forEach((row, index) => {
      const job = jobs[index]; row.dataset.href = "true";
      const port = jobPort(job.execution_port) || jobPort(job.port);
      const serverID = String(
        job.execution_server_id || job.server_id || "",
      ).trim();
      // The storage owner is always part of the detail route.  Even a
      // legacy-looking local server id must be preserved so a stopped worker
      // port cannot become the artifact lookup authority.
      const target = serverID
        ? "?server_id=" + encodeURIComponent(serverID) : "";
      const path = port
        ? `/jobs/${port}/${encodeURIComponent(job.job_id)}${target}`
        : `/jobs/${encodeURIComponent(job.job_id)}${target}`;
      row.addEventListener("click", () => context.navigate(path));
    });
    result.shell.classList.add("job-list-table");
    root.append(result.shell, pagination(context, scoped, scope, page, Boolean(payload.has_more), Number(payload.total_pages || 1), Number(payload.total || 0)));
    context.content.replaceChildren(root);
  }

  window.FTJobs = {
    invalidate, list, text, scalar, date, table, statusPill, kindTitle, jobPort,
    formatBytes, taskCell, taskHash, taskTitle,
  };
})();
