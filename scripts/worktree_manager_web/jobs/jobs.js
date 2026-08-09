(() => {
  const text = value => value == null ? "" : String(value);
  const scalar = value => value == null || ["string", "number", "boolean"].includes(typeof value);
  const date = value => value ? FTUI.formatDate(value) : "";

  function statusTitle(value, context) {
    const title = {
      succeeded: "成功", failed: "失败", running: "运行中", queued: "排队中",
      planning: "规划中", cancelled: "已取消", paused: "已暂停",
      submitted: "已提交", created: "已创建",
    }[value];
    return title ? context.t(title) : value || context.t("未知");
  }

  function statusPill(value, context) {
    const pill = document.createElement("span");
    const normalized = String(value || "unknown").toLowerCase().replace(/[^a-z0-9_-]/g, "-");
    pill.className = `job-status ${normalized || "unknown"}`;
    pill.textContent = statusTitle(value, context);
    return pill;
  }

  function kindTitle(value, context) {
    const title = {
      ic: "IC 测试", ic_test: "IC 测试", "ic-test": "IC 测试",
      backtest: "回测", group_backtest: "回测", test: "测试",
    }[String(value || "").toLowerCase()];
    return title ? context.t(title) : value || context.t("测试");
  }

  function jobPort(value) {
    const port = Number(value);
    return Number.isInteger(port) && port > 0 ? port : null;
  }

  function displayProfile(job, context) {
    const profile = job.server_context?.profile || job.profile || "";
    const owner = job.owner || job.server_context?.owner || "";
    if (owner && profile) return `${owner}（${profile}）`;
    return profile || owner || context.t("未知");
  }

  const pageSize = 20;
  const scopeDefinitions = [
    {id: "server", title: "服务器任务"},
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
    if (existing && existing.byScope && existing.identityKey === identity) return existing;
    // The server feed is the default for both anonymous and authenticated
    // visits.  Private scopes remain available as explicit account tabs, and
    // a pending private tab survives the login round-trip.
    const initial = "server";
    const value = {
      identityKey: identity,
      activeScope: initial,
      byScope: {
        mine: freshScopeState(),
        subordinates: freshScopeState(),
        server: freshScopeState(),
      },
    };
    context.tabSession.jobLists = value;
    return value;
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
        state.activeScope = definition.id;
        // Let the API return its structured requires_login view.  The tab
        // itself stays a plain scope selector and never opens the modal.
        context.tabSession.pendingJobScope = definition.id;
        list(context, null, definition.id);
      });
      root.append(button);
    });
    return root;
  }

  function installScopeToolbar(context, state, scope) {
    context.toolbar.replaceChildren(
      scopeTabs(context, state),
      context.button("↻", () => list(context, null, scope), context.t("刷新任务列表")),
    );
  }

  async function fetchPage(context, state, scope, targetPage) {
    const page = Math.max(1, Math.min(1000, Number(targetPage) || 1));
    const scoped = state.byScope[scope];
    if (!scoped) throw new Error(context.t("不支持的任务范围"));
    if (scope !== "server") {
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

  async function list(context, requestedPage = null, requestedScope = null) {
    const isCurrent = () => context.isRouteCurrent?.() !== false;
    if (!isCurrent()) return;
    FTJobProgress.stopProgress();
    context.activeNav("jobs"); context.setHeading(context.t("测试任务"));
    context.content.replaceChildren(FTUI.loading(context.t("正在读取跨端口任务…")));
    const state = scopeState(context);
    const pendingScope = context.tabSession.pendingJobScope;
    // A fresh anonymous visit must always show the public server feed.  The
    // selected private scope is only retained while the user is actively
    // viewing its in-page login-required state; otherwise a previous click
    // could leave the whole jobs module stuck on an empty private view.
    const defaultAnonymousScope = !context.session && !requestedScope && !pendingScope
      ? "server" : null;
    const scope = requestedScope || pendingScope || defaultAnonymousScope || state.activeScope;
    if (pendingScope && context.session && (!requestedScope || pendingScope === requestedScope)) {
      delete context.tabSession.pendingJobScope;
    }
    state.activeScope = scope;
    const scoped = state.byScope[scope];
    installScopeToolbar(context, state, scope);
    // A module revisit and a scope switch are explicit refreshes.  Do not
    // reuse an anonymous public page after login, or an older first page when
    // new jobs have arrived since the last visit.
    if (requestedPage == null) {
      Object.assign(scoped, freshScopeState());
    }
    const requested = Math.max(1, Math.min(1000, Number(requestedPage == null ? 1 : requestedPage) || 1));
    let payload;
    try {
      payload = await fetchPage(context, state, scope, requested);
    } catch (error) {
      if (!isCurrent()) return;
      const root = document.createElement("div"); root.className = "jobs-page";
      if (scope === "server") root.append(publicScopeNote(context));
      const failure = FTUI.empty(context.t("任务列表读取失败"), text(error.message || error));
      failure.append(context.button(
        context.t("重试"), () => list(context, null, scope), context.t("重新读取任务列表"),
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
    const result = FTUI.table([context.t("任务"), context.t("端口"), context.t("时间"), context.t("状态"), context.t("Profile"), context.t("生成物")], jobs.map(job => [
      `${kindTitle(job.kind, context)} · ${job.job_id}`, jobPort(job.port) || context.t("未知"), date(job.updated_at), statusPill(job.status, context), displayProfile(job, context), job.artifact_count || 0,
    ]));
    [...result.body.rows].forEach((row, index) => {
      const job = jobs[index]; row.dataset.href = "true";
      const port = jobPort(job.port);
      const path = port ? `/jobs/${port}/${encodeURIComponent(job.job_id)}` : `/jobs/${encodeURIComponent(job.job_id)}`;
      row.addEventListener("click", () => context.navigate(path));
    });
    result.shell.classList.add("job-list-table");
    root.append(result.shell, pagination(context, scoped, scope, page, Boolean(payload.has_more), Number(payload.total_pages || 1), Number(payload.total || 0)));
    context.content.replaceChildren(root);
  }

  window.FTJobs = {
    list, text, scalar, date, table, statusPill, kindTitle, jobPort,
  };
})();
