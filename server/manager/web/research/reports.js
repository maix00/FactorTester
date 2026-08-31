(() => {
  const tabs = [
    {id: "mine", title: "我的研究报告"},
    {id: "subordinates", title: "下级用户的研究报告"},
    {id: "shared", title: "共享研究报告"},
  ];
  const pageSize = 20;

  function current(context) {
    return context.isRouteCurrent?.() !== false;
  }

  function stateFor(context) {
    const state = context.tabSession.researchReports || {
      scope: context.session ? "mine" : "shared",
      pages: {},
    };
    state.pages ||= {};
    if (!context.session && state.scope !== "shared") state.scope = "shared";
    context.tabSession.researchReports = state;
    context.pageState?.register?.("research-report-list", {
      capture: () => ({scope: state.scope, pages: state.pages}),
      restore: value => {
        if (value?.scope) state.scope = value.scope;
        if (value?.pages) state.pages = value.pages;
      },
      describe: () => ({page: "research-reports", section: state.scope, fields: []}),
    });
    return state;
  }

  function tabBar(context, state, embedded) {
    const root = document.createElement("nav");
    root.className = "research-report-tabs";
    root.setAttribute("aria-label", context.t("研究报告范围"));
    tabs.forEach(definition => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `research-report-tab${state.scope === definition.id ? " active" : ""}`;
      button.textContent = context.t(definition.title);
      button.disabled = !context.session && definition.id !== "shared";
      button.addEventListener("click", () => {
        if (button.disabled) return;
        state.scope = definition.id;
        state.pages[definition.id] = 1;
        const url = new URL(location.href);
        url.searchParams.set("section", "reports");
        url.searchParams.set("report_scope", definition.id);
        history.pushState({}, "", `${url.pathname}?${url.searchParams.toString()}`);
        if (embedded && window.webkit?.messageHandlers?.researchNavigation) {
          window.webkit.messageHandlers.researchNavigation.postMessage({
            path: `/research?section=reports&report_scope=${encodeURIComponent(definition.id)}`,
          });
        }
        window.dispatchEvent(new PopStateEvent("popstate"));
      });
      root.append(button);
    });
    return root;
  }

  async function fetchRows(context, scope, embedded) {
    if (scope === "mine") {
      const [serverResult, localResult] = await Promise.allSettled([
        context.api("/api/research-publications/settings"),
        embedded && context.session
          ? context.api("/api/client/research")
          : Promise.reject(new Error("client research is available in the local client")),
      ]);
      const rows = [];
      const publishedByReport = new Map(
        (serverResult.status === "fulfilled" ? serverResult.value.reports || [] : [])
          .filter(item => item?.report_id)
          .map(item => [String(item.report_id), item]),
      );
      if (serverResult.status === "fulfilled") {
        (serverResult.value.reports || []).forEach(item => rows.push({
          ...item,
          source: "server_catalog",
          build_source: item.build_source || "client",
          href: item.href || `/research/${encodeURIComponent(item.publication_id || "")}`,
        }));
      }
      if (localResult.status === "fulfilled") {
        (localResult.value.research || []).forEach(item => rows.push({
          ...item,
          source: "client_local",
          build_source: item.build_source || "client",
          sharing_state: sharingState(
            item,
            publishedByReport.get(String(item.report_id || "")),
          ),
          is_shared: sharingState(
            item,
            publishedByReport.get(String(item.report_id || "")),
          ) === "shared",
          title: item.title || item.local_ref,
          owner_ref: item.profile_name || item.profile_id,
          href: `/research/${encodeURIComponent(`local:${item.local_ref}`)}`,
        }));
      }
      return rows;
    }
    const result = await context.api(`/api/public-research?scope=${encodeURIComponent(scope)}`);
    return (result.reports || []).map(item => ({
      ...item,
      source: "server_catalog",
      build_source: item.build_source || "client",
      href: item.href || `/research/${encodeURIComponent(item.publication_id || "")}`,
    }));
  }

  async function loadClientRelease(context) {
    try {
      return await context.api(context.servicePath("/api/client/releases/beta.json"));
    } catch (_) {
      return null;
    }
  }

  function ownerDisplay(context, item) {
    const owner = String(item.owner_ref || item.owner_username || "").trim();
    const profile = String(item.profile_ref || item.profile_id || "").trim();
    if (owner && profile) return `${owner}（${profile}）`;
    return owner || profile || context.t("未知");
  }

  function table(context, rows, state, scope, root) {
    const view = FTUI.pagedTable(
      [
        context.t("报告"), context.t("用户（Profile）"), context.t("构建来源"),
        context.t("共享状态"), context.t("访问范围"), context.t("更新时间"),
      ],
      rows.map(item => [
        item.title || item.name || item.filename || context.t("未命名研究报告"),
        ownerDisplay(context, item),
        buildSource(context, item),
        sharing(context, item),
        visibility(context, item.visibility),
        FTUI.formatDate(item.updated_at || item.created_at),
      ]),
      {
        page: state.pages[scope] || 1,
        pageSize,
        pageLabel: (page, total) => `${page} / ${total}`,
        totalLabel: total => context.t("共 %lld 个").replace("%lld", String(total)),
        onPageChange: page => {
          state.pages[scope] = page;
          void renderScope(context, root, false);
        },
      },
    );
    const pageRows = rows.slice(view.start, view.start + view.pageSize);
    [...view.body.rows].forEach((row, index) => {
      row.dataset.href = "true";
      row.addEventListener("click", () => context.navigate(pageRows[index].href));
    });
    view.shell.classList.add("research-report-table");
    return view.shell;
  }

  function visibility(context, value) {
    const labels = {private: "仅自己", authorized: "授权用户", public: "公开"};
    return context.t(labels[value] || value || "未知");
  }

  function buildSource(context, item) {
    const labels = {
      client: "客户端构建",
      server_agent: "服务器 Agent 构建",
    };
    return context.t(labels[item.build_source] || "未知");
  }

  function sharing(context, item) {
    return context.t(sharingState(item) === "shared" ? "共享" : "非共享");
  }

  function sharingState(item, publication = null) {
    const value = item?.sharing_state || publication?.sharing_state;
    if (value === "shared" || value === "not_shared") return value;
    if (item?.is_shared === true || publication?.is_shared === true) return "shared";
    const visibility = item?.visibility || publication?.visibility;
    return ["authorized", "public"].includes(visibility)
      ? "shared" : "not_shared";
  }

  async function renderScope(context, root, embedded) {
    if (!root || !current(context)) return;
    const state = stateFor(context);
    const scope = state.scope;
    const content = root.querySelector(".research-report-scope-content");
    content.replaceChildren(FTUI.loading(context.t("正在读取研究报告…")));
    try {
      if (scope === "mine") {
        await window.FTStaticLoader?.loadGroups?.(["research-local"]);
        if (!current(context)) return;
      }
      const [rows, release] = await Promise.all([
        fetchRows(context, scope, embedded),
        scope === "mine" ? loadClientRelease(context) : Promise.resolve(null),
      ]);
      if (!current(context)) return;
      const children = [];
      if (scope === "mine") {
        const download = FTResearchLocal.clientDownload?.(context, release);
        if (download) children.push(download);
      }
      children.push(rows.length
        ? table(context, rows, state, scope, root)
        : FTUI.empty(
          context.t(scope === "shared" ? "暂无共享研究报告" : "暂无研究报告"),
          context.t("研究报告会按来源显示在这里"),
        ));
      content.replaceChildren(...children);
    } catch (error) {
      if (current(context)) content.replaceChildren(
        FTUI.empty(context.t("无法读取"), error.message || String(error)),
      );
    }
  }

  async function render(context, mount, embedded) {
    const root = document.createElement("div");
    root.className = "research-reports-page";
    const state = stateFor(context);
    const requested = new URLSearchParams(location.search).get("report_scope");
    if (tabs.some(item => item.id === requested) && (context.session || requested === "shared")) {
      state.scope = requested;
    }
    root.append(tabBar(context, state, embedded));
    const content = document.createElement("div");
    content.className = "research-report-scope-content";
    root.append(content);
    mount.append(root);
    await renderScope(context, root, embedded);
  }

  function researchReportState(context, researchID) {
    const root = context.tabSession.researchReportLists
      || (context.tabSession.researchReportLists = {});
    const key = String(researchID || "");
    const state = root[key] || {page: 1};
    root[key] = state;
    context.pageState?.register?.(`research-reports:${key}`, {
      capture: () => ({page: state.page}),
      restore: value => {
        if (Number(value?.page) > 0) state.page = Number(value.page);
      },
      describe: () => ({page: "research-reports", research_id: key, fields: []}),
    });
    return state;
  }

  function reportRoute(item, researchID = "") {
    const explicit = String(item?.href || "").trim();
    let route = explicit;
    const reference = String(item?.source_ref || item?.report_id || "").trim();
    if (!route) route = reference
      ? `/research/${encodeURIComponent(reference)}` : "";
    if (!route || !researchID) return route;
    const url = new URL(route, location.origin);
    url.searchParams.set("research_id", researchID);
    return `${url.pathname}${url.search}${url.hash}`;
  }

  function researchReportTable(context, rows, state, mount, researchID) {
    const view = FTUI.pagedTable(
      [
        context.t("研究报告"), context.t("构建来源"),
        context.t("访问范围"), context.t("更新时间"), context.t("操作"),
      ],
      rows.map(item => {
        const action = context.button(
          context.t("独立打开"),
          event => {
            event.stopPropagation();
            const href = reportRoute(item, researchID);
            if (!href) return;
            context.navigate(href, {
              parentFolder: "research",
              parentTabID: context.tabID,
              parentResearchID: researchID,
              title: item.title || item.report_id || context.t("研究报告"),
            });
          },
          context.t("在左栏的当前研究下打开此研究报告"),
        );
        action.className = "secondary research-report-open";
        return [
          item.title || item.report_id || context.t("未命名研究报告"),
          buildSource(context, item),
          visibility(context, item.visibility),
          FTUI.formatDate(item.updated_at || item.created_at),
          action,
        ];
      }),
      {
        page: state.page,
        pageSize,
        pageLabel: (page, total) => `${page} / ${total}`,
        totalLabel: total => context.t("共 %lld 个").replace("%lld", String(total)),
        onPageChange: page => {
          state.page = page;
          void renderForResearch(context, mount, researchID);
        },
      },
    );
    const pageRows = rows.slice(view.start, view.start + view.pageSize);
    [...view.body.rows].forEach((row, index) => {
      row.dataset.href = "true";
      row.addEventListener("click", () => {
        const href = reportRoute(pageRows[index], researchID);
        if (!href) return;
        context.navigate(href, {
          parentFolder: "research",
          parentTabID: context.tabID,
          parentResearchID: researchID,
          title: pageRows[index].title || pageRows[index].report_id,
        });
      });
    });
    view.shell.classList.add("research-report-table", "research-report-table-embedded");
    return view.shell;
  }

  async function renderForResearch(context, mount, researchID, researchMeta = {}) {
    const id = String(researchID || "").trim();
    if (!id) {
      mount.replaceChildren(FTUI.empty(context.t("无法读取"), context.t("缺少 Research 标识")));
      return;
    }
    const state = researchReportState(context, id);
    mount.replaceChildren(FTUI.loading(context.t("正在读取研究报告…")));
    try {
      const value = await context.api(
        `/api/research/${encodeURIComponent(id)}/reports`,
      );
      if (!current(context)) return;
      const rows = Array.isArray(value.reports) ? value.reports : [];
      const root = document.createElement("div");
      root.className = "research-reports-for-research";
      const note = document.createElement("p");
      note.className = "secondary";
      note.textContent = researchMeta.title
        ? `${context.t("属于研究")}: ${researchMeta.title}`
        : context.t("这些研究报告属于当前 Research");
      root.append(note);
      root.append(rows.length
        ? researchReportTable(context, rows, state, mount, id)
        : FTUI.empty(context.t("暂无研究报告"), context.t("可在当前 Research 中登记研究报告")));
      mount.replaceChildren(root);
    } catch (error) {
      if (current(context)) mount.replaceChildren(
        FTUI.empty(context.t("无法读取"), error.message || String(error)),
      );
    }
  }

  window.FTResearchReports = Object.freeze({
    render, renderForResearch, buildSource, sharing,
  });
})();
