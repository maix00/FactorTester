(() => {
  const model = () => window.FTFactorModel;

  function factorAlias(value) {
    return String(value?.factor_alias || value?.alias || "");
  }

  function factorRef(value) {
    return String(value?.factor_ref || value?.ref || "");
  }

  function factorMatches(value, targetRef) {
    const target = String(targetRef || "");
    return String(value?.factor_ref || "") === target
      || String(value?.ref || "") === target
      || String(value?.factor_alias || "") === target
      || String(value?.alias || "") === target;
  }

  // An object row is editable by its owner (or super admin); catalog
  // projections deliberately do not carry a can_edit flag on factor rows.
  // An in-place temporary object was created by this test session, so it is
  // editable regardless of library ownership metadata.
  function editableBySession(context, value) {
    if (!context.session) return false;
    if (context.testObjectTemporary === true) return true;
    if (value?.can_edit === true) return true;
    if (context.session.role === "super_admin") return true;
    const owner = String(
      value?.owner_username || value?.owner_alias || "",
    ).trim();
    return Boolean(owner) && owner === String(context.session.username || "");
  }

  async function factorDetail(
    context, data, targetRef, mode = "view", nativeRequest, options = {},
  ) {
    if (mode === "create" || mode === "edit") {
      return FTFactorEditor.render(context, data, targetRef, mode, options);
    }
    let factor = (context.testObjectTemporary || context.testObjectSnapshot)
      && context.testObjectInitialValue
      ? context.testObjectInitialValue
      : data.factors.find(item => factorMatches(item, targetRef));
    if (!factor) {
      throw new Error(context.t("因子不存在或当前端口无法解析该引用"));
    }
    // Factor instances do not own a source panel. Keep source retrieval lazy;
    // the family header help opens the exact frozen revision on demand.
    factor = window.FTFactorDisplayEnrichment?.enrichFactorForDisplay(data, factor)
      || factor;
    factor = model().withSourceMetadata(factor);
    // 查看模式：factor 携带的两类公式字段
    //   math_expr        = 因子家族_LATEX模板_（\textcolor{red}{alias} 占位，未叠加）
    //   resolved_math_expr = 后端_叠加后_的完整公式（参数替换+嵌套因子展开）
    // 查看模式只渲染后端生成的 resolved_math_expr。math_expr 是编辑器的
    // 参数模板；查看页绝不能用 JS previewExpression 补算，否则不同服务端的
    // 参数组合、Resample 和 $Rev 会出现不一致。
    factor.factor_source_version = factor.family_formula_fingerprint
      ? `公式版本 · ${factor.family_formula_fingerprint.slice(0, 12)}`
      : "未固定公式版本";
    const alias = factorAlias(factor);
    const frozenRef = factorRef(factor) || targetRef;
    // The eyebrow is the object-kind scope, uniform with other detail pages
    // (因子家族/产品组/策略库…).  The owning family name stays visible in
    // the summary block instead of occupying the header eyebrow.
    context.setHeading(alias || context.t("因子详情"), context.t("因子"));
    context.toolbar?.append(context.button(context.t("查看因子序列"), () => {
      context.navigate(`/factor-series?factor_ref=${encodeURIComponent(frozenRef)}`);
    }, context.t("使用冻结因子配置运行序列查看任务")));
    if (!factor.historical_member && editableBySession(context, factor)) {
      // Same-tab authoring: the shared mode-actions component derives the edit
      // URL from the current location (same pathname → same detail tab).
      window.FTObjectModeActions?.mount?.(context, {
        mode: "view",
        onEdit: true,
        editLabel: "编辑",
        editHelp: "编辑因子",
      });
    }
    context.updateActiveTab?.({title: alias || context.t("因子详情")});
    const root = document.createElement("div");
    root.className = window.FTFactorDetailShared.pageClass("view", "factor-page");
    const top = document.createElement("div");
    top.className = "factor-detail-top";
    top.append(window.FTFactorDetailShared.summary(
      context, factor, {instance: true, resolvedOnly: true},
    ));
    root.append(top);
    const provenance = window.FTFactorDetailShared.provenance(context, factor);
    const parameters = window.FTFactorDetailShared.parameterTable(
      context, factor, {preview: false},
    );
    const jobs = objectJobs(context, "factor", frozenRef, factor);
    const tabs = window.FTObjectDetailTabs.create(context, {
      objectKind: "factor",
      mode: "view",
      overrides: {
        source: {hidden: !factor.historical_member},
        parameters: {hidden: !parameters},
        identity: {hidden: !provenance},
        jobs: {onActivate: jobs.load},
      },
      panels: {
        overview: FTUI.table(
          [context.t("字段"), context.t("值")], FTUI.fieldRows(factor),
        ).shell,
        source: factor.historical_member ? window.FTFactorDetailShared.source(context, factor) : null,
        parameters,
        identity: provenance,
        jobs: jobs.mount,
      },
    });
    root.append(tabs.root);
    context.content.replaceChildren(root);
  }

  async function familyDetail(
    context, data, targetRef, mode = "view", options = {},
  ) {
    let family = data.families.find(item => item.family_ref === targetRef
      || item.factor_family_alias === targetRef);
    if (mode === "create" || mode === "edit") {
      if (mode === "edit" && !family) {
        throw new Error(context.t("因子家族不存在或当前端口无法解析该引用"));
      }
      return FTFactorEditor.render(
        context,
        data,
        family?.family_ref || targetRef,
        mode,
        {
          familyMode: true,
          publicMode: options.publicMode === true
            || family?.factor_kind === "public"
            || family?.source === "public",
        },
      );
    }
    if (!family) throw new Error(context.t("因子家族不存在或当前端口无法解析该引用"));
    // A test-local family (created inline in a test editor, never persisted)
    // has no server version history: render its carried frozen value directly
    // instead of attempting a catalog round-trip for "current" source.
    const localView = (context.testObjectTemporary || context.testObjectSnapshot)
      && context.testObjectInitialValue;
    if (!localView) family = await withCurrentFamilySource(context, family);
    const baseFamily = family;
    const canSelectVersion = !localView && Boolean(
      baseFamily.family_ref || baseFamily.factor_family_alias,
    );
    context.setHeading(model().familyName(baseFamily), context.t("因子家族"));
    context.updateActiveTab?.({title: model().familyName(baseFamily)});
    const publicFamily = baseFamily.factor_kind === "public"
      || baseFamily.source === "public";
    // In-place temporary families (created in a test editor) are editable by
    // the owning session regardless of library ownership metadata.
    const canEdit = context.testObjectTemporary === true || (
      Boolean(context.session) && (
        publicFamily
          ? context.session.role === "super_admin"
          : baseFamily.can_edit === true
            || String(baseFamily.owner_username || "") === String(
              context.session.username || "",
            )
      )
    );
    if (canEdit && !context.testObjectViewOnly) {
      // Same-tab authoring: the shared mode-actions component derives the edit
      // URL from the current location (keeps visibility=public etc. and the
      // pathname, so the same family tab swaps in place).
      window.FTObjectModeActions?.mount?.(context, {
        mode: "view",
        onEdit: true,
        editLabel: "编辑",
        editHelp: "编辑因子家族",
      });
      context.toolbar?.append(context.button(context.t("删除"), async () => {
        const alias = baseFamily.factor_family_alias || baseFamily.factor_family_name;
        if (!window.FTFactorCatalogList?.confirmFamilyChange) {
          await window.FTStaticLoader.loadGroups(["factor-catalog-list"]);
        }
        const impact = await window.FTFactorCatalogList.confirmFamilyChange(
          context, publicFamily ? "public" : "custom", alias, alias);
        if (!impact) return;
        const endpoint = publicFamily
          ? `/api/factor-library/families/public/${encodeURIComponent(alias)}`
          : `/api/factor-library/families/custom/${encodeURIComponent(alias)}`;
        try {
          await context.api(`${endpoint}?revision=${encodeURIComponent(impact.revision)}`, {method: "DELETE"});
          context.showNotice?.(context.t("已删除"));
          if (FTTabReturn.returnToSource(context)) return;
          context.closeTab?.(context.tabID);
          context.navigate(publicFamily
            ? "/factors/families?scope=public"
            : "/factors/families?scope=mine");
        } catch (error) {
          context.showNotice?.(error.message || context.t("删除失败"), true);
        }
      }, context.t("删除此因子家族")));
    }
    let selectedVersion = "";
    let sourceVersions = null;
    let renderSequence = 0;

    const renderFamily = displayFamily => {
      const root = document.createElement("div");
      root.className = window.FTFactorDetailShared.pageClass(
        "view", "factor-family-page",
      );
      const top = document.createElement("div");
      top.className = "factor-detail-top";
      if (canSelectVersion) {
        top.append(sourceVersionHistory(
          context, baseFamily, {
            payload: sourceVersions,
            selected: selectedVersion || "__current__",
            onLoaded: payload => { sourceVersions = payload; },
            onChange: selected => { void selectVersion(selected); },
          },
        ));
      }
      top.append(window.FTFactorDetailShared.summary(context, displayFamily));
      root.append(top);
      const provenance = window.FTFactorDetailShared.provenance(
        context, displayFamily,
      );
      const members = (data.factors || []).filter(item =>
        baseFamily.factor_refs?.includes(item.factor_ref)
      );
      const view = FTUI.table(
        [context.t("因子"), context.t("来源"), context.t("所有者")],
        members.map(item => [
          item.factor_alias,
          context.t(item.factor_kind === "public" ? "公共" : "用户"),
          FTUI.userDisplay(item.owner_ref || item.owner_username, model().owner(item)),
        ]),
      );
      linkRows(view, members, item =>
        `/factors/factor/${encodeURIComponent(item.factor_ref)}`, context,
      );
      const parameters = window.FTFactorDetailShared.parameterTable(
        context, displayFamily, {showValue: false},
      );
      const jobs = objectJobs(
        context, "family", baseFamily.family_ref || targetRef, baseFamily,
      );
      const tabs = window.FTObjectDetailTabs.create(context, {
        objectKind: "family",
        mode: "view",
        overrides: {
          parameters: {hidden: !parameters},
          members: {hidden: !members.length},
          identity: {hidden: !provenance},
          jobs: {onActivate: jobs.load},
        },
        panels: {
          overview: FTUI.table(
            [context.t("字段"), context.t("值")], FTUI.fieldRows(displayFamily),
          ).shell,
          source: window.FTFactorDetailShared.source(context, displayFamily),
          parameters,
          members: view.shell,
          identity: provenance,
          jobs: jobs.mount,
        },
      });
      root.append(tabs.root);
      context.content.replaceChildren(root);
    };

    const selectVersion = async selected => {
      const fingerprint = selected === "__current__" ? "" : String(selected || "");
      selectedVersion = fingerprint;
      const sequence = ++renderSequence;
      if (!fingerprint) {
        renderFamily(baseFamily);
        return;
      }
      context.content.replaceChildren(FTUI.loading(
        context.t("正在读取源码版本…"),
      ));
      try {
        const payload = await window.FTFactorDetailShared.loadSourceVersion(
          context, baseFamily, fingerprint,
        );
        if (sequence !== renderSequence || context.isRouteCurrent?.() === false) return;
        renderFamily({
          ...baseFamily,
          ...payload,
          family_formula_fingerprint:
            payload.family_formula_fingerprint || fingerprint,
          source_unavailable_reason: "",
        });
      } catch (_) {
        if (sequence !== renderSequence || context.isRouteCurrent?.() === false) return;
        renderFamily({
          ...baseFamily,
          family_formula_fingerprint: fingerprint,
          source_code: "",
          source_unavailable_reason: window.FTFactorDetailShared.sourceUnavailableText(
            context,
          ),
        });
      }
    };

    renderFamily(baseFamily);
  }

  function sourceVersionHistory(context, value, options = {}) {
    const root = document.createElement("section");
    root.className = "factor-source-version-history";
    const status = document.createElement("small");
    status.className = "factor-source-version-status";
    const control = document.createElement("div");
    control.className = "factor-source-version-control";
    const selected = options.selected || "__current__";
    const mountPicker = () => {
      const picker = window.FTFactorDetailShared.versionPicker(context, value, {
        ...options,
        selected,
        onLoaded: payload => {
          status.textContent = payload?.available === false
            ? context.t("当前服务器没有可用的源码版本历史") : "";
          options.onLoaded?.(payload);
        },
        onError: error => {
          status.textContent = window.FTFactorDetailShared.sourceUnavailableText(context);
          options.onError?.(error);
        },
      });
      control.replaceChildren(picker.element);
    };
    if (window.FTTestObjectPicker?.create || window.FTMultiSelectFilter?.create) {
      mountPicker();
    } else {
      const button = context.button(context.t("选择源码版本"), async () => {
        if (button.disabled) return;
        button.disabled = true;
        status.textContent = context.t("正在加载源码版本选择器…");
        try {
          await window.FTStaticLoader?.loadGroups?.(["catalog-selection-core"]);
          if (context.isRouteCurrent?.() === false) return;
          mountPicker();
          status.textContent = "";
        } catch (_) {
          button.disabled = false;
          status.textContent = context.t("源码版本选择器加载失败");
        }
      }, context.t("选择要查看的因子家族源码版本"));
      button.classList.add("secondary");
      control.append(button);
    }
    root.append(
      window.FTFactorDetailShared.fieldRow(context, context.t("源码版本"), control),
      status,
    );
    return root;
  }

  async function withCurrentFamilySource(context, value) {
    if (value?.source_code) return value;
    const options = window.FTFactorDetailShared.sourceOptions(value);
    if (!["custom", "public"].includes(options.sourceKind)) return value;
    try {
      const payload = await window.FTFactorDetailShared.loadSourceVersion(
        context, value, "current",
      );
      return {
        ...value,
        ...payload,
        source_unavailable_reason: "",
      };
    } catch (_) {
      return {
        ...value,
        source_code: "",
        source_unavailable_reason: window.FTFactorDetailShared.sourceUnavailableText(
          context,
        ),
      };
    }
  }

  async function setDetail(context, data, targetRef, nativeRequest) {
    const selected = data.sets.find(item =>
      item.target_ref === targetRef || item.set_ref === targetRef
    );
    const frozenRef = targetRef.startsWith("factor-set:v2:")
      ? targetRef
      : selected?.target_ref;
    if (!frozenRef) {
      throw new Error(context.t("该因子集合尚未冻结，不能打开稳定详情"));
    }
    context.content.replaceChildren(FTUI.loading(context.t("正在解析因子集合…")));
    const first = context.testObjectTemporary && context.testObjectInitialValue
      ? {factor_set: context.testObjectInitialValue}
      : await loadSetPage(context, selected, frozenRef, 0, nativeRequest);
    const value = first.factor_set || first || {};
    if (context.isRouteCurrent?.() === false) return;
    const fallbackTitle = context.testObjectTemporary ? "因子候选" : "因子集合";
    context.setHeading(value.title_zh || context.t(fallbackTitle), context.t(fallbackTitle));
    context.updateActiveTab?.({title: value.title_zh || context.t(fallbackTitle)});
    // Same-tab authoring entry: the shared component mounts the pencil
    // action that swaps this tab to the set editor.
    const setEditable = value.registration_active !== false && (selected?.can_edit === true
      || editableBySession(context, selected || value));
    if (setEditable) {
      window.FTObjectModeActions?.mount?.(context, {
        mode: "view",
        onEdit: true,
        editLabel: "编辑",
        editHelp: "编辑因子集合",
      });
    }
    const root = document.createElement("div");
    root.className = window.FTFactorDetailShared.pageClass(
      "view", "factor-set-page",
    );
    const memberMount = document.createElement("section");
    memberMount.className = "factor-set-members";
    const sourceRows = factorSetSourceRows(context, value);
    const provenance = window.FTFactorDetailShared.provenance(context, value);
    const jobs = objectJobs(context, "set", frozenRef, value);
    const history = document.createElement("section");
    let historyLoaded = false;
    async function loadHistory(offset = 0) {
      if (historyLoaded && offset === 0) return;
      const query = new URLSearchParams({target_ref: frozenRef, offset: String(offset), limit: "50",
        owner_username: selected?.owner_username || value.owner_username || ""});
      try {
        const payload = await context.api(`/api/factor-library/factor-sets/history?${query}`);
        if (context.isRouteCurrent?.() === false) return;
        const page = payload.history;
        const rows = page.items.map(event => [
          event.member.alias, context.t(event.action === "added" ? "新增成员" : "移除成员"),
          new Date(event.occurred_at * 1000).toLocaleString(),
        ]);
        const table = FTUI.table([context.t("因子"), context.t("变化"), context.t("时间")], rows);
        linkRows(table, page.items, event => {
          const params = new URLSearchParams({history_set: frozenRef,
            set_owner: selected?.owner_username || value.owner_username || ""});
          return `/factors/factor/${encodeURIComponent(event.member.ref)}?${params}`;
        }, context);
        history.replaceChildren(table.shell);
        if (!rows.length) history.append(document.createTextNode(context.t("暂无可追溯的成员变化记录")));
        const nav = document.createElement("div");
        if (offset > 0) nav.append(context.button(context.t("上一页"), () => loadHistory(Math.max(0, offset - 50))));
        if (page.has_more) nav.append(context.button(context.t("下一页"), () => loadHistory(page.next_offset)));
        history.append(nav);
        historyLoaded = true;
      } catch (error) {
        history.textContent = error.message || context.t("读取历史失败");
      }
    }
    const tabs = window.FTObjectDetailTabs.create(context, {
      objectKind: "set",
      mode: "view",
      overrides: {
        history: {hidden: context.testObjectTemporary === true || selected?.visibility === "local", onActivate: () => loadHistory()},
        sources: {hidden: !sourceRows.length},
        identity: {hidden: !provenance},
        jobs: {onActivate: jobs.load},
      },
      panels: {
        overview: FTUI.table(
          [context.t("字段"), context.t("值")], FTUI.fieldRows(value),
        ).shell,
        members: memberMount,
        history,
        sources: sourceRows.length ? FTUI.table(
          [context.t("字段"), context.t("值")], sourceRows,
        ).shell : null,
        identity: provenance,
        jobs: jobs.mount,
      },
    });
    root.append(tabs.root);
    context.content.replaceChildren(root);
    const members = [];
    await appendSetPage(
      context, selected, frozenRef, first, members, memberMount, nativeRequest,
    );
  }

  function factorSetSourceRows(context, value) {
    const rows = [];
    if (Object.prototype.hasOwnProperty.call(value || {}, "source_factors")) {
      rows.push([
        context.t("来源因子"),
        referenceLinks(context, value.source_factors, "factor"),
      ]);
    }
    if (Object.prototype.hasOwnProperty.call(value || {}, "source_factor_sets")) {
      rows.push([
        context.t("来源因子集合"),
        referenceLinks(context, value.source_factor_sets, "set"),
      ]);
    }
    return rows;
  }

  function objectJobs(context, objectKind, objectRef, value) {
    const item = value || {};
    return window.FTFactorObjectJobs.create(context, {
      objectKind,
      objectRef: String(objectRef || ""),
      familyFormulaFingerprint: String(
        item.family_formula_fingerprint || "",
      ),
      selfFormulaFingerprint: String(
        item.self_formula_fingerprint || "",
      ),
      ownerRef: String(
        item.factor_owner_ref || item.owner_ref || "",
      ),
      alias: objectKind === "family" ? String(
        item.factor_family_alias || item.factor_family_name || item.family_alias || "",
      ) : "",
    });
  }

  function referenceLinks(context, raw, kind) {
    const root = document.createElement("span");
    root.className = "factor-set-source-links";
    const items = Array.isArray(raw) ? raw.filter(item => item?.target_ref) : [];
    if (!items.length) {
      root.textContent = context.t("无");
      return root;
    }
    items.forEach((item, index) => {
      if (index) {
        const separator = document.createElement("span");
        separator.textContent = "、";
        root.append(separator);
      }
      const path = `/factors/${kind}/${encodeURIComponent(item.target_ref)}`;
      const link = document.createElement("a");
      link.href = path;
      link.className = "catalog-source-family-link";
      link.textContent = item.label || item.target_ref;
      link.addEventListener("click", event => {
        event.preventDefault();
        navigateReference(context, kind, item, path);
      });
      root.append(link);
    });
    return root;
  }

  async function appendSetPage(
    context, selected, frozenRef, payload, members, mount, nativeRequest,
  ) {
    const page = payload.factor_set || payload || {};
    members.push(...(Array.isArray(page.related_references)
      ? page.related_references : []));
    const view = FTUI.table(
      [context.t("因子"), context.t("冻结引用")],
      members.map(item => [item.label || item.title_zh, item.target_ref]),
    );
    linkRows(view, members, item =>
      `/factors/factor/${encodeURIComponent(item.target_ref)}`, context,
      (item, path) => navigateReference(context, "factor", item, path),
    );
    mount.replaceChildren(view.shell);
    if (!page.has_more) return;
    const more = context.button(context.t("加载更多"), async () => {
      more.disabled = true;
      const next = await loadSetPage(
        context, selected, frozenRef, page.next_offset, nativeRequest,
      );
      if (context.isRouteCurrent?.() === false) return;
      await appendSetPage(
        context, selected, frozenRef, next, members, mount, nativeRequest,
      );
    }, context.t("加载更多集合成员"));
    more.className = "secondary";
    mount.append(more);
  }

  async function loadSetPage(context, selected, targetRef, offset, nativeRequest) {
    if (selected?.visibility === "local") {
      return nativeRequest("members", {target_ref: targetRef, offset, limit: 100});
    }
    const query = new URLSearchParams({
      target_ref: targetRef,
      offset: String(offset),
      limit: "100",
    });
    if (selected?.owner_username) {
      query.set("owner_username", selected.owner_username);
    }
    return context.api(`/api/factor-library/factor-sets/detail?${query}`);
  }

  function linkRows(view, items, path, context, onNavigate = null) {
    [...view.body.rows].forEach((row, index) => {
      row.dataset.href = "true";
      row.addEventListener("click", () => {
        const item = items[index];
        const target = path(item);
        if (onNavigate) onNavigate(item, target);
        else context.navigate(target);
      });
    });
  }

  function navigateReference(context, kind, item, path) {
    if (kind === "factor" && context.openFactor) {
      context.openFactor({
        ...item,
        ref: String(item?.target_ref || ""),
        alias: String(item?.label || item?.title_zh || ""),
      });
      return;
    }
    context.navigate(path);
  }

  window.FTFactorDetails = Object.freeze({factorDetail, familyDetail, setDetail});
})();
