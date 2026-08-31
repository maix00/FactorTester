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
    factor = await withSource(context, factor);
    factor = model().withSourceMetadata(factor);
    factor.factor_source_version = factor.family_formula_fingerprint
      ? `公式版本 · ${factor.family_formula_fingerprint.slice(0, 12)}`
      : "未固定公式版本";
    const alias = factorAlias(factor);
    const frozenRef = factorRef(factor) || targetRef;
    context.setHeading(alias || context.t("因子详情"), model().familyName(factor));
    context.toolbar?.append(context.button(context.t("查看因子序列"), () => {
      context.navigate(`/factor-series?factor_ref=${encodeURIComponent(frozenRef)}`);
    }, context.t("使用冻结因子配置运行序列查看任务")));
    if (factor.can_edit && context.session && !context.testObjectViewOnly) {
      context.toolbar?.append(context.button(context.t("编辑"), () => {
        context.navigate(FTTabReturn.withSource(
          `/factors/factor/${encodeURIComponent(alias || frozenRef)}?mode=edit`,
          context, {kind: "factor", ref: alias || frozenRef},
        ));
      }, context.t("在独立标签页编辑因子")));
    }
    context.updateActiveTab?.({title: alias || context.t("因子详情")});
    const root = document.createElement("div");
    root.className = window.FTFactorDetailShared.pageClass("view", "factor-page");
    const top = document.createElement("div");
    top.className = "factor-detail-top";
    top.append(window.FTFactorDetailShared.summary(context, factor));
    root.append(top);
    const provenance = window.FTFactorDetailShared.provenance(context, factor);
    const parameters = window.FTFactorDetailShared.parameterTable(context, factor);
    const jobs = objectJobs(context, "factor", frozenRef, factor);
    const tabs = window.FTObjectDetailTabs.create(context, {
      objectKind: "factor",
      mode: "view",
      overrides: {
        parameters: {hidden: !parameters},
        identity: {hidden: !provenance},
        jobs: {onActivate: jobs.load},
      },
      panels: {
        overview: FTUI.table(
          [context.t("字段"), context.t("值")], FTUI.fieldRows(factor),
        ).shell,
        source: window.FTFactorDetailShared.source(context, factor),
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
    family = await withCurrentFamilySource(context, family);
    const baseFamily = family;
    context.setHeading(model().familyName(baseFamily), context.t("因子家族"));
    context.updateActiveTab?.({title: model().familyName(baseFamily)});
    const publicFamily = baseFamily.factor_kind === "public"
      || baseFamily.source === "public";
    const canEdit = Boolean(context.session) && (
      publicFamily
        ? context.session.role === "super_admin"
        : baseFamily.can_edit === true
          || String(baseFamily.owner_username || "") === String(
            context.session.username || "",
          )
    );
    if (canEdit && !context.testObjectViewOnly) {
      const editQuery = publicFamily
        ? "?mode=edit&visibility=public" : "?mode=edit";
      context.toolbar?.append(context.button(context.t("编辑"), () => {
        context.navigate(FTTabReturn.withSource(
          `/factors/family/${encodeURIComponent(family.family_ref)}${editQuery}`,
          context, {kind: "family", ref: family.family_ref},
        ));
      }, context.t("在独立标签页编辑因子家族")));
      context.toolbar?.append(context.button(context.t("删除"), async () => {
        if (!window.confirm(context.t("确认删除该因子家族？"))) return;
        const alias = baseFamily.factor_family_alias || baseFamily.factor_family_name;
        const endpoint = publicFamily
          ? `/api/factor-library/families/public/${encodeURIComponent(alias)}`
          : `/api/factor-library/families/custom/${encodeURIComponent(alias)}`;
        try {
          await context.api(endpoint, {method: "DELETE"});
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
      top.append(window.FTFactorDetailShared.sourceVersionHistory(
        context, baseFamily, {
          payload: sourceVersions,
          selected: selectedVersion || "__current__",
          onLoaded: payload => { sourceVersions = payload; },
          onChange: selected => { void selectVersion(selected); },
        },
      ));
      top.append(window.FTFactorDetailShared.summary(context, displayFamily));
      root.append(top);
      const provenance = window.FTFactorDetailShared.provenance(
        context, displayFamily,
      );
      const members = data.factors.filter(item =>
        baseFamily.factor_refs?.includes(item.factor_ref)
      );
      const view = FTUI.table(
        [context.t("因子"), context.t("来源"), context.t("所有者")],
        members.map(item => [
          item.factor_alias,
          context.t(item.factor_kind === "public" ? "公共" : "用户"),
          model().owner(item),
        ]),
      );
      linkRows(view, members, item =>
        `/factors/factor/${encodeURIComponent(item.factor_ref)}`, context,
      );
      const parameters = window.FTFactorDetailShared.parameterTable(
        context, displayFamily,
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

  async function withSource(context, value) {
    const fingerprint = String(value?.family_formula_fingerprint || "").trim();
    const options = window.FTFactorDetailShared.sourceOptions(value);
    // A frozen source carried by a local/temporary object is authoritative. A
    // catalog projection without source must instead resolve the exact server
    // snapshot; it must never silently fall back to today's family source.
    if (fingerprint && value?.source_code) return value;
    if (fingerprint && ["custom", "public"].includes(options.sourceKind)) {
      try {
        const payload = await window.FTFactorDetailShared.loadSourceVersion(
          context, value, fingerprint,
        );
        const valueParams = window.FTFactorDetailShared.parameterRows(value);
        const sourceParams = window.FTFactorDetailShared.parameterRows(payload);
        const params = valueParams.length ? valueParams : sourceParams;
        return {
          ...value,
          ...payload,
          family_formula_fingerprint:
            payload.family_formula_fingerprint || fingerprint,
          source_unavailable_reason: "",
          ...(params.length ? {params, factor_params: params} : {}),
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
    if (value?.source_code || !context.session) return value;
    const family = value.factor_family_alias || value.family_alias
      || model().familyName(value);
    if (!family) return value;
    try {
      const detail = await window.FTFactorDetailShared.loadSourceVersion(
        context, value, "current", {familyID: family},
      );
      const valueParams = window.FTFactorDetailShared.parameterRows(value);
      const detailParams = window.FTFactorDetailShared.parameterRows(detail);
      // A registered factor carries its concrete parameter values; the
      // source-detail response carries the family's parameter definitions.
      // Keep the former when present so opening a factor detail page never
      // replaces the saved factor values with family defaults.
      const params = valueParams.length ? valueParams : detailParams;
      return {
        ...value,
        ...detail,
        // A source-detail transport may legitimately omit derived metadata.
        // Never let an empty response erase the formula already present in
        // the catalog projection.
        math_expr: detail.math_expr || value.math_expr || "",
        source_code: detail.source_code || value.source_code || "",
        ...(params.length ? {params, factor_params: params} : {}),
      };
    } catch (_) {
      return value;
    }
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
    const root = document.createElement("div");
    root.className = window.FTFactorDetailShared.pageClass(
      "view", "factor-set-page",
    );
    const memberMount = document.createElement("section");
    memberMount.className = "factor-set-members";
    const sourceRows = factorSetSourceRows(context, value);
    const provenance = window.FTFactorDetailShared.provenance(context, value);
    const jobs = objectJobs(context, "set", frozenRef, value);
    const tabs = window.FTObjectDetailTabs.create(context, {
      objectKind: "set",
      mode: "view",
      overrides: {
        sources: {hidden: !sourceRows.length},
        identity: {hidden: !provenance},
        jobs: {onActivate: jobs.load},
      },
      panels: {
        overview: FTUI.table(
          [context.t("字段"), context.t("值")], FTUI.fieldRows(value),
        ).shell,
        members: memberMount,
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
