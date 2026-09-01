(() => {
  const scopes = [
    {id: "mine", title: "我的研究"},
    {id: "subordinates", title: "下级用户的研究"},
    {id: "shared", title: "共享研究"},
  ];
  const detailTabs = [
    {id: "details", title: "详情"},
    {id: "reports", title: "研究报告"},
    {id: "evidence", title: "证据"},
    {id: "profiles", title: "研究身份"},
    {id: "workspaces", title: "研究工作区"},
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
      public: "全体用户共享", superiors: "分享给上级",
      authorized: "指定用户可见", private: "仅自己", none: "无",
    }[basis] || basis);
  }

  function scopeTabs(context, state, root) {
    const row = document.createElement("div");
    row.className = "research-root-scope-row";
    const nav = document.createElement("nav");
    nav.className = "research-section-tabs research-root-scopes";
    nav.setAttribute("aria-label", context.t("研究范围"));
    scopes.forEach(definition => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `research-section-tab research-root-scope${state.scope === definition.id ? " active" : ""}`;
      button.dataset.researchScope = definition.id;
      button.textContent = context.t(definition.title);
      button.setAttribute("aria-current", state.scope === definition.id ? "page" : "false");
      button.disabled = !context.session && definition.id !== "shared";
      button.addEventListener("click", () => {
        if (button.disabled || state.scope === definition.id) return;
        state.scope = definition.id;
        state.pages[definition.id] = 1;
        nav.querySelectorAll(".research-root-scope").forEach(item => {
          const active = item.dataset.researchScope === state.scope;
          item.classList.toggle("active", active);
          item.setAttribute("aria-current", active ? "page" : "false");
        });
        addButton.hidden = state.scope !== "mine";
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
    const addButton = FTUI.iconButton(
      context, "plus", "新建研究",
      () => void createResearchDialog(context, root).catch(error => (
        context.showNotice?.(error.message || String(error), true)
      )),
    );
    addButton.classList.add("research-root-add");
    addButton.hidden = state.scope !== "mine" || !context.session;
    row.append(nav, addButton);
    return row;
  }

  function dialogButton(context, title, action, style = "secondary") {
    const button = context.button(context.t(title), action);
    button.classList.add(style);
    return button;
  }

  async function createResearchDialog(context, root) {
    const profiles = await FTPageAgentProfiles.profiles(context);
    const dialog = document.createElement("dialog");
    dialog.className = "ft-dialog research-visibility-dialog";
    const card = document.createElement("div");
    card.className = "dialog-card";
    const heading = document.createElement("h2");
    heading.textContent = context.t("新建研究");
    const title = document.createElement("input");
    title.placeholder = context.t("研究标题");
    const description = document.createElement("textarea");
    description.placeholder = context.t("研究说明（可选）");
    const profile = document.createElement("select");
    [["", context.t("暂不绑定研究身份")], ...profiles.map(item => [
      String(item.profile_id || ""),
      String(item.display_name || item.profile_id || ""),
    ])].forEach(([value, label]) => {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = label;
      profile.append(option);
    });
    const visibility = document.createElement("select");
    [
      ["private", "仅自己"], ["superiors", "分享给上级"],
      ["authorized", "指定用户可见"], ["public", "全体用户共享"],
    ].forEach(([value, label]) => {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = context.t(label);
      visibility.append(option);
    });
    const actions = document.createElement("div");
    actions.className = "dialog-actions";
    const cancel = dialogButton(context, "取消", () => dialog.close());
    const save = dialogButton(context, "创建", async () => {
      const cleanTitle = title.value.trim();
      if (!cleanTitle) {
        title.focus();
        return;
      }
      let authorizedUsers = [];
      if (visibility.value === "authorized") {
        const selected = await FTResearchVisibility.authorizedDialog(context, []);
        if (selected === null) return;
        authorizedUsers = selected;
      }
      save.disabled = true;
      try {
        const response = await context.api("/api/research", {
          method: "POST",
          body: JSON.stringify({
            title: cleanTitle,
            description: description.value.trim(),
            visibility: visibility.value,
            authorized_users: authorizedUsers,
            profile_ref: profile.value,
          }),
        });
        dialog.close();
        const item = response.research;
        context.navigate(`/researches/${encodeURIComponent(item.research_id)}`, {
          parentFolder: "research", parentResearchID: item.research_id,
          title: item.title,
        });
      } catch (error) {
        context.showNotice?.(error.message || String(error), true);
        save.disabled = false;
      }
    }, "primary");
    actions.append(cancel, save);
    card.append(heading, title, description, profile, visibility, actions);
    dialog.append(card);
    dialog.addEventListener("close", () => dialog.remove(), {once: true});
    document.body.append(dialog);
    dialog.showModal();
    title.focus();
  }

  function listTable(context, rows, state, root) {
    const scope = state.scope;
    const view = FTUI.pagedTable(
      [context.t("研究"), context.t("所有者"), context.t("可见性"), context.t("更新时间"), context.t("操作")],
      rows.map(item => {
        const actions = document.createElement("span");
        actions.className = "research-row-actions";
        if (item.can_delete === true) actions.append(FTUI.iconButton(
          context, "trash", "删除研究", async event => {
            event?.stopPropagation?.();
            if (!window.confirm(context.t("确定删除这个研究吗？"))) return;
            try {
              await context.api(
                `/api/research/${encodeURIComponent(item.research_id)}`,
                {method: "DELETE"},
              );
              await renderRootContent(context, root);
            } catch (error) {
              context.showNotice?.(error.message || String(error), true);
            }
          },
        ));
        actions.addEventListener("click", event => event.stopPropagation());
        return [
        item.title || item.research_id,
        item.owner_ref || context.t("未知"),
        FTResearchVisibility.control(context, item, {
          kind: "research", onSaved: () => renderRootContent(context, root),
        }),
        FTUI.formatDate(item.updated_at || item.created_at),
        actions,
      ];
      }),
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
    await FTResearchVisibility.redeemFromLocation(context);
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
    nav.className = "research-section-tabs research-detail-tabs";
    nav.setAttribute("aria-label", context.t("研究详情"));
    detailTabs.forEach(definition => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `research-section-tab research-detail-tab${state.activeTab === definition.id ? " active" : ""}`;
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

  async function addProfileDialog(context, researchID, research, rerender) {
    const [profiles, response] = await Promise.all([
      FTPageAgentProfiles.profiles(context),
      context.api(`/api/research/${encodeURIComponent(researchID)}/members`),
    ]);
    const bound = new Set((response.members || []).map(item => (
      String(item.profile_ref || "").replace(/^profile:/, "")
    )));
    const candidates = profiles.filter(item => !bound.has(
      String(item.profile_id || "").replace(/^profile:/, ""),
    ));
    if (!candidates.length) {
      context.showNotice?.(context.t("当前端没有可添加的研究身份"));
      return;
    }
    const dialog = document.createElement("dialog");
    dialog.className = "ft-dialog research-visibility-dialog";
    const card = document.createElement("div");
    card.className = "dialog-card";
    const heading = document.createElement("h2");
    heading.textContent = context.t("添加研究身份");
    const picker = document.createElement("select");
    candidates.forEach(item => {
      const option = document.createElement("option");
      option.value = String(item.profile_id || "");
      option.textContent = String(item.display_name || item.profile_id || "");
      option.dataset.principal = String(item.owner_ref || research.owner_ref || "");
      picker.append(option);
    });
    const actions = document.createElement("div");
    actions.className = "dialog-actions";
    const cancel = dialogButton(context, "取消", () => dialog.close());
    const save = dialogButton(context, "添加", async () => {
      const option = picker.selectedOptions[0];
      save.disabled = true;
      try {
        const payload = {
          principal_ref: option.dataset.principal || research.owner_ref,
          profile_ref: picker.value,
          role: "contributor",
          status: "active",
        };
        await context.api(`/api/research/${encodeURIComponent(researchID)}/members`, {
          method: "POST", body: JSON.stringify(payload),
        });
        await context.api(`/api/research/${encodeURIComponent(researchID)}/workspaces`, {
          method: "POST",
          body: JSON.stringify({
            principal_ref: payload.principal_ref,
            profile_ref: payload.profile_ref,
            title: `${research.title} / ${payload.profile_ref}`,
          }),
        });
        dialog.close();
        await rerender();
      } catch (error) {
        context.showNotice?.(error.message || String(error), true);
        save.disabled = false;
      }
    }, "primary");
    actions.append(cancel, save);
    card.append(heading, picker, actions);
    dialog.append(card);
    dialog.addEventListener("close", () => dialog.remove(), {once: true});
    document.body.append(dialog);
    dialog.showModal();
  }

  function profileTable(context, researchID, research, members, rerender) {
    const section = document.createElement("section");
    section.className = "research-detail-section";
    const toolbar = document.createElement("div");
    toolbar.className = "research-detail-actions";
    if (research?.access?.can_manage === true) {
      toolbar.append(FTUI.iconButton(
        context, "plus", "添加研究身份",
        () => void addProfileDialog(context, researchID, research, rerender),
      ));
    }
    const table = FTUI.table(
      [context.t("用户"), "Profile", context.t("角色"), context.t("操作")],
      members.map(item => {
        const actions = document.createElement("span");
        if (research?.access?.can_manage === true) {
          actions.append(FTUI.iconButton(
            context, "trash", "移除研究身份", async () => {
              if (!window.confirm(context.t("确定移除这个研究身份吗？"))) return;
              try {
                await context.api(
                  `/api/research/${encodeURIComponent(researchID)}`
                    + `/members/${encodeURIComponent(item.profile_ref)}`,
                  {method: "DELETE"},
                );
                await rerender();
              } catch (error) {
                context.showNotice?.(error.message || String(error), true);
              }
            },
          ));
        }
        return [item.principal_ref, item.profile_ref, item.role, actions];
      }),
    );
    section.append(toolbar, members.length
      ? table.shell
      : FTUI.empty(context.t("暂无研究身份")));
    return section;
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
        await window.FTStaticLoader?.loadGroups?.(["research-reports"]);
        if (!current(context)) return;
        await FTResearchReports.renderForResearch(
          context, pane, researchID, {
            title: value.title,
            canManage: value?.access?.can_manage === true,
          },
        );
        return;
      }
      if (kind === "evidence") {
        const page = state.pages.evidence || 1;
        const response = await context.api(
          `/api/research-evidence/catalog/research/${encodeURIComponent(researchID)}`
          + `?page=${page}&page_size=${pageSize}`,
        );
        if (!current(context)) return;
        const catalog = response.catalog || {};
        const items = catalog.items || [];
        if (!items.length) {
          pane.replaceChildren(FTUI.empty(
            context.t("暂无证据"), context.t("该研究的报告尚未引用 Evidence"),
          ));
          return;
        }
        const table = FTUI.pagedTable([
          context.t("证据"), context.t("类型"), context.t("摘要"),
          context.t("引用报告"), context.t("引用时间"),
        ], items.map(item => [
          item.title_zh || item.evidence_ref, item.evidence_kind || "—",
          item.claim_summary || "—", item.report_count,
          FTUI.formatDate(item.linked_at),
        ]), {
          remote: true, page: catalog.page, pageSize: catalog.page_size,
          total: catalog.total,
          onPageChange: next => {
            state.pages.evidence = next;
            void childTable(context, root, researchID, value, kind);
          },
        });
        [...table.body.rows].forEach((row, index) => {
          const item = items[index];
          row.dataset.href = "true";
          row.addEventListener("click", () => context.navigate(
            `/evidence/${encodeURIComponent(item.evidence_ref)}`,
            {
              title: item.title_zh || context.t("证据"),
              parentFolder: "research",
              parentResearchID: researchID,
            },
          ));
        });
        pane.replaceChildren(table.shell);
        return;
      }
      const response = await context.api(endpoint);
      if (!current(context)) return;
      if (kind === "members") {
        const rerender = () => childTable(context, root, researchID, value, kind);
        pane.replaceChildren(profileTable(
          context, researchID, value, response.members || [], rerender,
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
      reports: "reports", evidence: "evidence",
      profiles: "members", workspaces: "workspaces",
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
      context.setHeading(value.title || id, context.t("研究"));
      const root = document.createElement("div");
      root.className = "research-root-detail research-detail-page";
      root.__researchValue = value;
      root.append(detailTabsView(context, state, root, id));
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
