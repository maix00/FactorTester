(() => {
  const scopes = [
    {id: "mine", title: "本人研究"},
    {id: "subordinates", title: "下级用户研究"},
    {id: "shared", title: "公开（给我的）研究"},
  ];
  const detailTabs = [
    {id: "details", title: "详情"},
    {id: "reports", title: "研究报告"},
    {id: "profiles", title: "研究身份"},
    {id: "workspaces", title: "研究工作区"},
    {id: "evidence", title: "证据"},
  ];
  const pageSize = 20;

  function current(context) {
    return context.isRouteCurrent?.() !== false;
  }

  function rootState(context) {
    const state = context.tabSession.researchCatalog || {
      scope: context.session ? "mine" : "shared",
      pages: {},
    };
    state.pages ||= {};
    if (!context.session) state.scope = "shared";
    if (!scopes.some(item => item.id === state.scope)) state.scope = "mine";
    context.tabSession.researchCatalog = state;
    context.pageState?.register?.("research-root", {
      capture: () => ({scope: state.scope, pages: state.pages}),
      restore: value => {
        if (scopes.some(item => item.id === value?.scope)) state.scope = value.scope;
        if (value?.pages && typeof value.pages === "object") state.pages = value.pages;
      },
      describe: () => ({page: "research-root", section: state.scope, fields: []}),
    });
    return state;
  }

  function detailState(context) {
    const state = context.tabSession.researchDetail || {
      activeTab: "details",
      pages: {},
    };
    state.pages ||= {};
    if (!detailTabs.some(item => item.id === state.activeTab)) state.activeTab = "details";
    context.tabSession.researchDetail = state;
    context.pageState?.register?.("research-detail", {
      capture: () => ({activeTab: state.activeTab, pages: state.pages}),
      restore: value => {
        if (detailTabs.some(item => item.id === value?.activeTab)) state.activeTab = value.activeTab;
        if (value?.pages && typeof value.pages === "object") state.pages = value.pages;
      },
      describe: () => ({page: "research-detail", section: state.activeTab, fields: []}),
    });
    return state;
  }

  function accessLabel(context, item) {
    const basis = item?.access?.access_basis || item?.visibility || "private";
    return context.t({
      owner: "所有者", member: "成员", research: "研究共享",
      public: "公开", authorized: "授权用户", private: "仅自己", none: "无",
    }[basis] || basis);
  }

  function scopeTabs(context, state, root) {
    const nav = document.createElement("nav");
    nav.className = "research-root-scopes";
    nav.setAttribute("aria-label", context.t("研究范围"));
    scopes.forEach(definition => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `research-root-scope${state.scope === definition.id ? " active" : ""}`;
      button.textContent = context.t(definition.title);
      button.setAttribute("aria-current", state.scope === definition.id ? "page" : "false");
      button.disabled = !context.session && definition.id !== "shared";
      button.addEventListener("click", () => {
        if (button.disabled || state.scope === definition.id) return;
        state.scope = definition.id;
        state.pages[definition.id] = 1;
        const url = new URL(location.href);
        url.searchParams.set("section", "researches");
        url.searchParams.set("research_scope", definition.id);
        url.searchParams.delete("research_id");
        context.updateActiveTab?.({path: `${url.pathname}${url.search}`});
        history.replaceState({}, "", `${url.pathname}${url.search}`);
        void renderRootContent(context, root);
      });
      nav.append(button);
    });
    return nav;
  }

  function listTable(context, rows, state, root) {
    const scope = state.scope;
    const view = FTUI.pagedTable(
      [context.t("研究"), context.t("所有者"), context.t("可见性"), context.t("更新时间")],
      rows.map(item => [
        item.title || item.research_id,
        item.owner_ref || context.t("未知"),
        accessLabel(context, item),
        FTUI.formatDate(item.updated_at || item.created_at),
      ]),
      {
        page: state.pages[scope] || 1,
        pageSize,
        pageLabel: (page, total) => `${page} / ${total}`,
        totalLabel: total => `${context.t("共")} ${total} ${context.t("个")}`,
        onPageChange: page => {
          state.pages[scope] = page;
          void renderRootContent(context, root);
        },
      },
    );
    const pageRows = rows.slice(view.start, view.start + view.pageSize);
    [...view.body.rows].forEach((row, index) => {
      row.dataset.href = "true";
      row.addEventListener("click", () => {
        const item = pageRows[index];
        if (!item?.research_id) return;
        context.navigate(`/researches/${encodeURIComponent(item.research_id)}`, {
          parentFolder: "research",
          parentResearchID: item.research_id,
          title: item.title || item.research_id,
        });
      });
    });
    view.shell.classList.add("research-root-table");
    return view.shell;
  }

  async function renderRootContent(context, root) {
    const state = rootState(context);
    const content = root.querySelector(".research-root-content");
    if (!content) return;
    content.replaceChildren(FTUI.loading(context.t("正在读取研究…")));
    try {
      const value = await context.api(
        `/api/research?scope=${encodeURIComponent(state.scope)}`,
      );
      if (!current(context)) return;
      const rows = Array.isArray(value.researches) ? value.researches : [];
      content.replaceChildren(rows.length
        ? listTable(context, rows, state, root)
        : FTUI.empty(
          context.t("暂无研究"),
          context.t("当前范围内还没有 Research 根对象"),
        ));
    } catch (error) {
      if (current(context)) content.replaceChildren(
        FTUI.empty(context.t("无法读取"), error.message || String(error)),
      );
    }
  }

  async function renderList(context, mount) {
    const state = rootState(context);
    const requested = new URLSearchParams(location.search).get("research_scope");
    if (scopes.some(item => item.id === requested) && context.session) state.scope = requested;
    const root = document.createElement("div");
    root.className = "research-root-page";
    root.append(scopeTabs(context, state, root));
    const content = document.createElement("div");
    content.className = "research-root-content";
    root.append(content);
    mount.replaceChildren(root);
    await renderRootContent(context, root);
  }

  function detailTabsView(context, state, root, researchID) {
    const nav = document.createElement("nav");
    nav.className = "research-detail-tabs";
    nav.setAttribute("aria-label", context.t("研究详情"));
    detailTabs.forEach(definition => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `research-detail-tab${state.activeTab === definition.id ? " active" : ""}`;
      button.textContent = context.t(definition.title);
      button.setAttribute("aria-current", state.activeTab === definition.id ? "page" : "false");
      button.addEventListener("click", () => {
        if (state.activeTab === definition.id) return;
        state.activeTab = definition.id;
        const url = new URL(location.href);
        url.searchParams.set("research_tab", definition.id);
        context.updateActiveTab?.({path: `${url.pathname}${url.search}`});
        history.replaceState({}, "", `${url.pathname}${url.search}`);
        nav.querySelectorAll("button").forEach(item => {
          const active = item === button;
          item.classList.toggle("active", active);
          item.setAttribute("aria-current", active ? "page" : "false");
        });
        void renderDetailPane(context, root, researchID, root.__researchValue);
      });
      nav.append(button);
    });
    return nav;
  }

  function simpleTable(context, headers, rows, state, pageKey, renderAgain) {
    if (!rows.length) return FTUI.empty(context.t("暂无记录"));
    const view = FTUI.pagedTable(headers, rows, {
      page: state.pages[pageKey] || 1,
      pageSize,
      pageLabel: (page, total) => `${page} / ${total}`,
      totalLabel: total => `${context.t("共")} ${total} ${context.t("个")}`,
      onPageChange: page => {
        state.pages[pageKey] = page;
        void renderAgain();
      },
    });
    return view.shell;
  }

  function detailOverview(context, value) {
    const table = FTUI.table(
      [context.t("字段"), context.t("值")],
      [
        [context.t("研究标识"), value.research_id],
        [context.t("所有者"), value.owner_ref],
        [context.t("可见性"), accessLabel(context, value)],
        [context.t("状态"), value.status],
        [context.t("创建时间"), FTUI.formatDate(value.created_at)],
        [context.t("更新时间"), FTUI.formatDate(value.updated_at)],
      ],
    );
    const description = document.createElement("p");
    description.className = "research-detail-description";
    description.textContent = value.description || context.t("无说明");
    const section = document.createElement("section");
    section.className = "research-detail-section";
    section.append(description, table.shell);
    return section;
  }

  function registerResearchAssistance(context, research) {
    if (!context.session) return null;
    let profileListPromise = null;
    const resolveProfiles = () => {
      profileListPromise ||= FTPageAgentProfiles.forResearch(
        context, research.research_id,
      );
      return profileListPromise;
    };
    return FTPageAssistance.register(context, {
      navigation: () => ({
        schema_version: 1,
        root_id: "page",
        nodes: {
          page: {
            id: "page", kind: "research", label: research.title || "研究",
            summary: research.description || "", children: [],
          },
        },
      }),
      schema: () => ({type: "object", readOnly: true}),
      exportDocument: () => ({
        schema_version: 1,
        document_kind: "research_context",
        research_id: research.research_id,
      }),
      validate: () => {},
      importDocument: () => {
        throw new Error(context.t("研究内容通过研究工作流修改"));
      },
    }, {
      pageKind: "research",
      researchID: research.research_id,
      resolveProfiles,
      resolveProfile: async () => (
        (await resolveProfiles())[0] || FTPageAgentProfiles.self(context)
      ),
      view: () => ({
        research_id: research.research_id,
        section: detailState(context).activeTab,
      }),
    });
  }

  async function childTable(context, root, researchID, value, kind) {
    const state = detailState(context);
    const pane = root.querySelector(".research-detail-pane");
    const endpoint = `/api/research/${encodeURIComponent(researchID)}/${kind}`;
    pane.replaceChildren(FTUI.loading(context.t("正在读取…")));
    try {
      // The embedded report renderer owns its own lazy request, table state,
      // and independent-open action.  Do not fetch the same report list here
      // first; that doubled the payload and made the tab appear slow.
      if (kind === "reports") {
        await FTResearchReports.renderForResearch(
          context, pane, researchID, {title: value.title},
        );
        return;
      }
      const response = await context.api(endpoint);
      if (!current(context)) return;
      if (kind === "members") {
        pane.replaceChildren(simpleTable(
          context,
          [context.t("用户"), "Profile", context.t("角色"), context.t("状态")],
          (response.members || []).map(item => [
            item.principal_ref, item.profile_ref, item.role, item.status,
          ]),
          state,
          "profiles",
          () => childTable(context, root, researchID, value, kind),
        ));
        return;
      }
      if (kind === "workspaces") {
        pane.replaceChildren(simpleTable(
          context,
          ["Profile", context.t("工作区"), context.t("状态"), context.t("更新时间")],
          (response.workspaces || []).map(item => [
            item.profile_ref, item.title || item.workspace_id, item.status,
            FTUI.formatDate(item.updated_at),
          ]),
          state,
          "workspaces",
          () => childTable(context, root, researchID, value, kind),
        ));
        return;
      }
      pane.replaceChildren(simpleTable(
        context,
        [context.t("证据"), context.t("报告"), context.t("Job"), context.t("用途")],
        (response.evidence_links || []).map(item => [
          item.evidence_ref, item.report_id || "—", item.job_id || "—", item.purpose || "—",
        ]),
        state,
        "evidence",
        () => childTable(context, root, researchID, value, kind),
      ));
    } catch (error) {
      if (current(context)) pane.replaceChildren(
        FTUI.empty(context.t("无法读取"), error.message || String(error)),
      );
    }
  }

  async function renderDetailPane(context, root, researchID, value) {
    const state = detailState(context);
    const pane = root.querySelector(".research-detail-pane");
    if (!pane || !value) return;
    if (state.activeTab === "details") {
      pane.replaceChildren(detailOverview(context, value));
      return;
    }
    const kind = {
      reports: "reports", profiles: "members", workspaces: "workspaces", evidence: "evidence",
    }[state.activeTab];
    if (kind) await childTable(context, root, researchID, value, kind);
  }

  async function renderDetail(context, mount, researchID) {
    const id = String(researchID || "").trim();
    if (!id) return renderList(context, mount);
    mount.replaceChildren(FTUI.loading(context.t("正在读取研究详情…")));
    try {
      const value = (await context.api(
        `/api/research/${encodeURIComponent(id)}`,
      )).research;
      if (!current(context)) return;
      const state = detailState(context);
      const requested = new URLSearchParams(location.search).get("research_tab");
      if (detailTabs.some(item => item.id === requested)) state.activeTab = requested;
      context.updateActiveTab?.({
        title: value.title || id,
        parentFolder: "research",
        parentResearchID: id,
      });
      const root = document.createElement("div");
      root.className = "research-detail-page";
      root.__researchValue = value;
      const header = document.createElement("header");
      header.className = "research-detail-header";
      const back = context.button(context.t("返回研究"), () => {
        context.navigate("/research?section=researches");
      }, context.t("返回研究列表"));
      back.className = "secondary";
      const title = document.createElement("h2");
      title.textContent = value.title || id;
      const meta = document.createElement("p");
      meta.className = "secondary";
      meta.textContent = `${context.t("所有者")}: ${value.owner_ref || "—"} · ${context.t("可见性")}: ${accessLabel(context, value)}`;
      header.append(back, title, meta);
      root.append(header, detailTabsView(context, state, root, id));
      const pane = document.createElement("div");
      pane.className = "research-detail-pane";
      root.append(pane);
      mount.replaceChildren(root);
      registerResearchAssistance(context, value);
      await renderDetailPane(context, root, id, value);
    } catch (error) {
      if (current(context)) mount.replaceChildren(
        FTUI.empty(context.t("无法读取"), error.message || String(error)),
      );
    }
  }

  async function render(context, mount, researchID = "") {
    return researchID ? renderDetail(context, mount, researchID) : renderList(context, mount);
  }

  window.FTResearchCatalog = Object.freeze({render, detail: renderDetail});
})();
