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
      if (serverResult.status === "fulfilled") {
        (serverResult.value.reports || []).forEach(item => rows.push({
          ...item,
          source: "server",
          sourceLabel: "服务器",
          href: item.href || `/research/${encodeURIComponent(item.publication_id || "")}`,
        }));
      }
      if (localResult.status === "fulfilled") {
        (localResult.value.research || []).forEach(item => rows.push({
          ...item,
          source: "client",
          sourceLabel: "客户端",
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
      source: scope,
      sourceLabel: scope === "subordinates" ? "下级用户" : "共享",
      href: item.href || `/research/${encodeURIComponent(item.publication_id || "")}`,
    }));
  }

  function ownerDisplay(context, item) {
    const owner = String(item.owner_ref || item.owner_username || "").trim();
    const profile = String(item.profile_ref || item.profile_id || "").trim();
    if (owner && profile) return `${owner}（${profile}）`;
    return owner || profile || context.t("未知");
  }

  function table(context, rows, state, scope, root) {
    const view = FTUI.pagedTable(
      [context.t("报告"), context.t("用户（Profile）"), context.t("来源"), context.t("访问范围"), context.t("更新时间")],
      rows.map(item => [
        item.title || item.name || item.filename || context.t("未命名研究报告"),
        ownerDisplay(context, item),
        context.t(item.sourceLabel),
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

  async function renderScope(context, root, embedded) {
    if (!root || !current(context)) return;
    const state = stateFor(context);
    const scope = state.scope;
    const content = root.querySelector(".research-report-scope-content");
    content.replaceChildren(FTUI.loading(context.t("正在读取研究报告…")));
    try {
      const rows = await fetchRows(context, scope, embedded);
      if (!current(context)) return;
      const children = [];
      if (scope === "mine") {
        const download = FTResearchLocal.clientDownload?.(context, null);
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

  window.FTResearchReports = Object.freeze({render});
})();
