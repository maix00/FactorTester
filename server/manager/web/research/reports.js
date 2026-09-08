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

  async function fetchRows(context, scope) {
    const result = await context.api(
      `/api/research/reports?scope=${encodeURIComponent(scope)}`,
    );
    return (result.reports || result.items || []).map(item => ({
      ...item,
      source: "research_catalog",
      build_source: item.build_source || "client",
      href: reportRoute(item),
    }));
  }

  function ownerDisplay(context, item) {
    const owner = String(item.owner_ref || item.owner_username || "").trim();
    const profile = String(item.profile_ref || item.profile_id || "").trim();
    const parts = owner.split("@").filter(Boolean);
    const alias = String(item.owner_alias || (parts.length >= 2 ? parts[1] : owner)).trim();
    const institution = String(item.owner_institution || "").trim();
    const label = [alias || context.t("未知"), institution ? `· ${institution}` : ""]
      .filter(Boolean).join(" ") + (profile ? `（${profile}）` : "");
    const value = document.createElement("span");
    value.className = "research-report-owner";
    value.textContent = label;
    if (owner && owner !== alias) value.title = owner;
    return value;
  }

  function researchDisplay(context, item) {
    const research = item?.research || {};
    const title = String(research.title || item?.research_title || "").trim();
    return title || context.t("未关联研究");
  }

  function table(context, rows, state, scope, root) {
    const view = FTUI.pagedTable(
      [
        context.t("报告"), context.t("所属研究"), context.t("用户（Profile）"),
        context.t("构建来源"), context.t("访问范围"), context.t("更新时间"),
      ],
      rows.map(item => [
        item.title || item.name || item.filename || context.t("未命名研究报告"),
        researchDisplay(context, item),
        ownerDisplay(context, item),
        buildSource(context, item),
        FTResearchVisibility.control(context, item, {
          kind: "report", onSaved: () => renderScope(context, root, false),
        }),
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
      row.addEventListener("click", () => context.navigate(pageRows[index].href, {
        researchTitle: pageRows[index].research?.title || pageRows[index].research_title || "",
      }));
    });
    view.shell.classList.add("research-report-table");
    return view.shell;
  }

  function visibility(context, value) {
    const labels = {
      private: "仅自己", superiors: "分享给上级",
      authorized: "指定用户可见", public: "全体用户共享",
    };
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
    return ["superiors", "authorized", "public"].includes(visibility)
      ? "shared" : "not_shared";
  }

  async function renderScope(context, root, embedded) {
    if (!root || !current(context)) return;
    const state = stateFor(context);
    const scope = state.scope;
    const content = root.querySelector(".research-report-scope-content");
    content.replaceChildren(FTUI.loading(context.t("正在读取研究报告…")));
    try {
      const rows = await fetchRows(context, scope);
      if (!current(context)) return;
      content.replaceChildren(rows.length
        ? table(context, rows, state, scope, root)
        : FTUI.empty(
          context.t(scope === "shared" ? "暂无共享研究报告" : "暂无研究报告"),
          context.t("研究报告会按来源显示在这里"),
        ));
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
    const state = root[key] || {
      selectedReportID: "", selectedBranches: {}, reading: {},
    };
    state.selectedBranches ||= {};
    state.reading ||= {};
    root[key] = state;
    context.pageState?.register?.(`research-reports:${key}`, {
      capture: () => ({selected_report_id: state.selectedReportID}),
      restore: value => {
        if (value?.selected_report_id) state.selectedReportID = value.selected_report_id;
      },
      describe: () => ({
        page: "research-report", research_id: key,
        selected_report_id: state.selectedReportID, fields: [],
      }),
    });
    return state;
  }

  function reportRoute(item, researchID = "") {
    const explicit = String(item?.href || "").trim();
    let route = explicit;
    const reference = publicationID(item);
    const linkedResearchID = String(
      researchID || item?.research_id || item?.research?.research_id || "",
    ).trim();
    if (!route) route = reference
      ? `/research/${encodeURIComponent(reference)}` : "";
    if (!route || !linkedResearchID) return route;
    const url = new URL(route, location.origin);
    url.searchParams.set("research_id", linkedResearchID);
    if (item?.owner_ref) url.searchParams.set("owner_ref", item.owner_ref);
    return `${url.pathname}${url.search}${url.hash}`;
  }

  function reportIdentity(item) {
    return String(item?.report_id || item?.source_ref || item?.publication_id || "").trim();
  }

  function publicationID(item) {
    const selectedKind = String(item?.selected_branch?.source_kind || "").trim();
    const reference = String(
      item?.source_ref || item?.publication_id || item?.report_id || "",
    ).trim();
    if (!reference || /^(local|server):/.test(reference)) return reference;
    // A publication id is already the canonical server projection key.  The
    // parent report may still say build_source=client after migration; using
    // that stale value here would incorrectly turn the projection into a
    // local reference.
    if (selectedKind === "publication" || item?.source_kind === "publication") {
      return reference;
    }
    if (item?.build_source === "client") return `local:${reference}`;
    if (item?.build_source === "server_agent") return `server:${reference}`;
    return reference;
  }

  function selectedBranch(item, state) {
    const branches = Array.isArray(item?.branches) ? item.branches : [];
    const reportID = reportIdentity(item);
    const selectedID = state.selectedBranches?.[reportID] || "";
    return branches.find(branch => branch.publication_id === selectedID)
      || branches.find(branch => branch.selected)
      || branches[0]
      || null;
  }

  function selectedSource(item, state) {
    const branch = selectedBranch(item, state);
    return branch?.publication_id
      ? {
        ...item,
        source_kind: branch.source_kind,
        source_ref: branch.publication_id,
        publication_id: branch.publication_id,
        selected_branch: branch,
      }
      : item;
  }

  function installTabActions(mount, actions) {
    const detail = mount.closest(".research-root-detail");
    const tabs = detail?.querySelector(".research-detail-tabs");
    if (!tabs) return false;
    tabs.querySelector(".research-report-tab-actions")?.remove();
    actions.classList.add("research-report-tab-actions");
    tabs.append(actions);
    return true;
  }

  function reportActions(context, researchID, selected, rerender, canManage) {
    const actions = document.createElement("span");
    actions.className = "research-report-actions";
    if (canManage) {
      actions.append(FTUI.iconButton(
        context, "plus", "新建研究报告",
        () => void createReportDialog(context, researchID, rerender),
      ));
    }
    const settingsTarget = selected?.selected_branch?.publication_id
      ? {...selected, ...selected.selected_branch,
        publication_id: selected.selected_branch.publication_id}
      : selected;
    if (settingsTarget?.access?.can_manage === true || selected?.can_manage === true) {
      actions.append(FTUI.iconButton(
        context, "gearshape", "研究报告设置",
        () => FTResearchReportSettings.open(context, settingsTarget, rerender),
      ));
    }
    if (selected?.access?.can_manage === true && selected?.can_delete === true) {
      actions.append(FTUI.iconButton(
        context, "trash", "删除研究报告", async () => {
          if (!window.confirm(context.t("确定删除这个研究报告空间吗？"))) return;
          try {
            await context.api(
              `/api/research/${encodeURIComponent(researchID)}`
                + `/reports/${encodeURIComponent(reportIdentity(selected))}`,
              {method: "DELETE"},
            );
            await rerender();
          } catch (error) {
            context.showNotice?.(error.message || String(error), true);
          }
        },
      ));
    }
    return actions;
  }

  async function createReportDialog(context, researchID, rerender) {
    const profiles = await FTPageAgentProfiles.forResearch(context, researchID);
    if (!profiles.length) {
      context.showNotice?.(context.t("请先在“研究身份”中添加一个 Profile"), true);
      return;
    }
    const dialog = document.createElement("dialog");
    dialog.className = "ft-dialog research-visibility-dialog";
    const card = document.createElement("div");
    card.className = "dialog-card";
    const heading = document.createElement("h2");
    heading.textContent = context.t("新建研究报告");
    const title = document.createElement("input");
    title.placeholder = context.t("研究报告标题");
    const profile = document.createElement("select");
    profiles.forEach(item => {
      const option = document.createElement("option");
      option.value = String(item.profile_id || "");
      option.textContent = String(item.display_name || item.profile_id || "");
      profile.append(option);
    });
    const actions = document.createElement("div");
    actions.className = "dialog-actions";
    const cancel = context.button(context.t("取消"), () => dialog.close());
    cancel.classList.add("secondary");
    const create = context.button(context.t("创建"), async () => {
      if (!title.value.trim()) {
        title.focus();
        return;
      }
      create.disabled = true;
      try {
        await context.api(`/api/research/${encodeURIComponent(researchID)}/reports`, {
          method: "POST",
          body: JSON.stringify({
            title: title.value.trim(), profile_ref: profile.value,
            visibility: "private",
          }),
        });
        dialog.close();
        await rerender();
      } catch (error) {
        context.showNotice?.(error.message || String(error), true);
        create.disabled = false;
      }
    });
    create.classList.add("primary");
    actions.append(cancel, create);
    card.append(heading, title, profile, actions);
    dialog.append(card);
    dialog.addEventListener("close", () => dialog.remove(), {once: true});
    document.body.append(dialog);
    dialog.showModal();
    title.focus();
  }

  function reportInfoLine(
    context, researchID, rows, selected, state, rerender, canManage,
  ) {
    const line = document.createElement("div");
    line.className = "research-report-info-line";
    const picker = document.createElement("select");
    picker.setAttribute("aria-label", context.t("研究报告"));
    rows.forEach(item => {
      const option = document.createElement("option");
      option.value = reportIdentity(item);
      option.textContent = item.title || item.report_id || context.t("未命名研究报告");
      option.selected = option.value === reportIdentity(selected);
      picker.append(option);
    });
    picker.addEventListener("change", () => {
      state.selectedReportID = picker.value;
      void rerender();
    });
    line.append(picker);
    const branches = Array.isArray(selected?.branches) ? selected.branches : [];
    if (branches.length > 1) {
      const branch = selectedBranch(selected, state);
      const branchPicker = document.createElement("select");
      branchPicker.className = "branch-picker";
      branchPicker.setAttribute("aria-label", context.t("研究路径"));
      branches.forEach(item => {
        const option = document.createElement("option");
        option.value = item.publication_id || "";
        option.textContent = item.title || item.branch_ref || context.t("研究路径");
        option.selected = option.value === branch?.publication_id;
        branchPicker.append(option);
      });
      branchPicker.addEventListener("change", () => {
        state.selectedBranches[reportIdentity(selected)] = branchPicker.value;
        void rerender();
      });
      line.append(branchPicker);
    }
    const metadata = document.createElement("div");
    metadata.className = "research-report-info-metadata";
    [
      buildSource(context, selected),
      visibility(context, selected.visibility),
      FTUI.formatDate(selected.updated_at || selected.created_at),
    ].filter(Boolean).forEach(value => {
      const item = document.createElement("span");
      item.textContent = value;
      metadata.append(item);
    });
    const actions = reportActions(
      context, researchID, selectedSource(selected, state), rerender, canManage,
    );
    actions.prepend(FTUI.iconButton(
      context, "safari", "在独立页面打开",
      () => context.navigate(reportRoute(selectedSource(selected, state), researchID)),
    ));
    line.append(metadata);
    line.__reportActions = actions;
    return line;
  }

  async function renderReportBody(context, mount, item, state) {
    if (item?.build_source === "workspace" && !item?.source_ref) {
      mount.replaceChildren(FTUI.empty(
        context.t("研究报告尚未撰写"),
        context.t("绑定的 Profile 可以在这个报告空间中创建分支并撰写正文"),
      ));
      return;
    }
    const id = publicationID(item);
    if (!id) {
      mount.replaceChildren(FTUI.empty(
        context.t("无法读取研究报告"), context.t("缺少研究报告来源标识"),
      ));
      return;
    }
    mount.replaceChildren(FTUI.loading(context.t("正在读取研究报告正文…")));
    try {
      await window.FTStaticLoader?.loadGroups?.(["report"]);
      if (!current(context)) return;
      const source = FTReportSource.create(id, context.api, {ownerRef: item.owner_ref});
      const value = await source.load();
      if (!current(context)) return;
      const reading = state.reading[id] || {selectedChapterID: "", disclosures: {}};
      state.reading[id] = reading;
      const layout = document.createElement("div");
      layout.className = "report-layout research-embedded-report-layout";
      const rail = document.createElement("nav");
      rail.className = "chapter-rail";
      const body = document.createElement("div");
      body.className = "report-mount";
      layout.append(body);
      mount.replaceChildren(layout, rail);
      const transferContext = {api: context.api, t: context.t};
      FTReportRenderer.render(value, body, {
        chapterRail: rail,
        loadChapter: source.chapterLazy ? source.loadChapter : null,
        loadComponent: source.loadComponent,
        componentContentLazy: () => source.componentLazy,
        setChapterMetadata: source.setChapterMetadata,
        openLocalResource: (resourceID, label) =>
          FTReportEntry.openLocal(
            id, resourceID, label, value.access, context, source.localResourceIndex,
          ),
        localResourcePath: source.localResourcePath,
        openReference: (target, label) => FTReportEntry.openReference(target, context, label),
        nativeReference: Boolean(window.webkit?.messageHandlers?.researchReference),
        publicationID: id,
        reportAssetPath: source.isOwnerLocal ? source.reportAssetPath : null,
        loadReportAsset: source.isOwnerLocal ? null : assetRef =>
          FTResearchObjectTransfer.blob(
            transferContext, id, "research_asset", source.assetID(assetRef),
          ),
        loadLocalResource: source.isOwnerLocal ? null : resourceID =>
          FTResearchObjectTransfer.blob(
            transferContext, id, "research_local_resource", resourceID,
          ),
        selectedChapterID: reading.selectedChapterID,
        setSelectedChapter: chapterID => { reading.selectedChapterID = chapterID; },
        disclosureState: reading.disclosures,
        setDisclosureState: (componentID, open) => {
          reading.disclosures[componentID] = Boolean(open);
        },
      });
    } catch (error) {
      if (current(context)) mount.replaceChildren(FTUI.empty(
        context.t("无法读取研究报告"), error?.message || String(error),
      ));
    }
  }

  async function renderForResearch(context, mount, researchID, options = {}) {
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
      if (!rows.length) {
        const actions = reportActions(
          context, id, null,
          () => renderForResearch(context, mount, id, options),
          options.canManage === true,
        );
        if (!installTabActions(mount, actions)) {
          const toolbar = document.createElement("div");
          toolbar.className = "research-report-info-line";
          toolbar.append(actions);
          root.append(toolbar);
        }
        root.append(FTUI.empty(
          context.t("暂无研究报告"), context.t("点击加号新建研究报告"),
        ));
        mount.replaceChildren(root);
        return;
      }
      const selected = rows.find(item => reportIdentity(item) === state.selectedReportID)
        || rows[0];
      state.selectedReportID = reportIdentity(selected);
      const body = document.createElement("div");
      body.className = "research-report-embedded-body";
      const infoLine = reportInfoLine(
        context, id, rows, selected, state,
        () => renderForResearch(context, mount, id, options),
        options.canManage === true,
      );
      root.append(infoLine, body);
      mount.replaceChildren(root);
      if (!installTabActions(mount, infoLine.__reportActions)) {
        infoLine.append(infoLine.__reportActions);
      }
      await renderReportBody(context, body, selectedSource(selected, state), state);
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
