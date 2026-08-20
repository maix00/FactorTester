(() => {
  const model = () => window.FTFactorModel;

  async function factorDetail(context, data, targetRef, mode = "view", nativeRequest) {
    if (mode === "create" || mode === "edit") {
      return FTFactorEditor.render(context, data, targetRef, mode);
    }
    let factor = context.testObjectTemporary && context.testObjectInitialValue
      ? context.testObjectInitialValue
      : data.factors.find(item => (
        item.factor_ref === targetRef || item.factor_alias === targetRef
      ));
    const frozen = factor ? null : model().decodeFrozenFactorRef(targetRef);
    if (!factor && !frozen) {
      throw new Error(context.t("因子不存在或当前端口无法解析该引用"));
    }
    if (!factor) factor = projectedFactor(data.factors, frozen);
    if (factor && frozen) factor = frozenProjection(factor, frozen);
    if (!factor) factor = await localFactor(frozen, nativeRequest);
    factor = model().withSourceMetadata(factor);
    factor.factor_source_version = factor.factor_git_commit
      ? `历史源码版本 · ${factor.factor_git_commit}`
      : "当前因子家族最新源码";
    context.setHeading(factor.factor_alias || context.t("因子详情"), model().familyName(factor));
    const factorRef = factor.factor_ref || targetRef;
    context.toolbar?.append(context.button(context.t("查看因子序列"), () => {
      context.navigate(`/factor-series?factor_ref=${encodeURIComponent(factorRef)}`);
    }, context.t("使用冻结因子配置运行序列查看任务")));
    if (factor.can_edit && context.session && !context.testObjectViewOnly) {
      context.toolbar?.append(context.button(context.t("编辑"), () => {
        context.navigate(FTTabReturn.withSource(
          `/factors/factor/${encodeURIComponent(factor.factor_alias || factorRef)}?mode=edit`,
          context, {kind: "factor", ref: factor.factor_alias || factorRef},
        ));
      }, context.t("在独立标签页编辑因子")));
    }
    context.updateActiveTab?.({title: factor.factor_alias || context.t("因子详情")});
    const root = document.createElement("div");
    root.className = "detail-stack";
    root.append(window.FTFactorDetailShared.summary(context, factor));
    root.append(FTUI.table(
      [context.t("字段"), context.t("值")], FTUI.fieldRows(factor),
    ).shell);
    if (Array.isArray(factor.params) && factor.params.length) {
      root.append(FTUI.table(
        [context.t("参数"), context.t("值")],
        factor.params.map(item => [
          item.alias,
          item.redacted ? context.t("已隐藏") : item.value,
        ]),
      ).shell);
    }
    context.content.replaceChildren(root);
  }

  function projectedFactor(factors, frozen) {
    const candidates = (Array.isArray(factors) ? factors : []).filter(item => (
      item.factor_alias === frozen.alias
      && model().familyName(item) === frozen.family
    ));
    if (candidates.length <= 1) return candidates[0] || null;
    const ownerID = String(frozen.ownerRef || "").split(":").at(-1);
    return candidates.find(item => [
      item.owner_username, item.profile_id, item.owner_ref,
    ].some(value => value === ownerID || value === frozen.ownerRef)) || null;
  }

  function frozenProjection(factor, frozen) {
    return {
      ...factor,
      factor_ref: frozen.factorRef,
      factor_owner_ref: frozen.ownerRef,
      factor_family_ref: frozen.family,
      factor_git_commit: frozen.gitCommit,
      factor_params: frozen.params,
      git_commit: frozen.gitCommit,
      git_blob: frozen.gitBlob,
      relative_path: frozen.relativePath,
      params: frozen.params,
    };
  }

  async function localFactor(frozen, nativeRequest) {
    let family = {};
    try {
      family = await nativeRequest("family", {
        owner_ref: frozen.ownerRef,
        git_commit: frozen.gitCommit,
        family: frozen.family,
      });
    } catch (_) {}
    return {
      ...family,
      factor_ref: frozen.factorRef,
      factor_alias: frozen.alias,
      factor_family_alias: frozen.family,
      factor_family_name: frozen.family,
      factor_owner_ref: frozen.ownerRef,
      factor_family_ref: frozen.family,
      factor_git_commit: frozen.gitCommit,
      factor_params: frozen.params,
      owner_alias: frozen.ownerRef,
      owner_ref: frozen.ownerRef,
      git_commit: frozen.gitCommit,
      git_blob: frozen.gitBlob,
      relative_path: frozen.relativePath,
      params: frozen.params,
      factor_kind: "local",
    };
  }

  async function familyDetail(context, data, targetRef) {
    const family = data.families.find(item => item.family_ref === targetRef);
    if (!family) throw new Error(context.t("因子家族不存在或当前端口无法解析该引用"));
    context.setHeading(model().familyName(family), context.t("因子家族"));
    context.updateActiveTab?.({title: model().familyName(family)});
    const root = document.createElement("div");
    root.className = "detail-stack";
    root.append(window.FTFactorDetailShared.summary(context, family));
    root.append(FTUI.table(
      [context.t("字段"), context.t("值")], FTUI.fieldRows(family),
    ).shell);
    const members = data.factors.filter(item =>
      family.factor_refs?.includes(item.factor_ref)
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
    root.append(view.shell);
    context.content.replaceChildren(root);
  }

  async function setDetail(context, data, targetRef, nativeRequest) {
    const selected = data.sets.find(item =>
      item.target_ref === targetRef || item.set_ref === targetRef
    );
    const frozenRef = targetRef.startsWith("factor-set:v1:")
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
    root.className = "detail-stack";
    root.append(FTUI.table(
      [context.t("字段"), context.t("值")], factorSetFieldRows(context, value),
    ).shell);
    const memberMount = document.createElement("section");
    memberMount.className = "factor-set-members";
    root.append(memberMount);
    context.content.replaceChildren(root);
    const members = [];
    await appendSetPage(
      context, selected, frozenRef, first, members, memberMount, nativeRequest,
    );
  }

  function factorSetFieldRows(context, value) {
    const rows = FTUI.fieldRows(value);
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
        context.navigate(path);
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
    return context.api(
      `/api/catalog/factor-sets/detail?target_ref=${encodeURIComponent(targetRef)}&offset=${offset}&limit=100`,
    );
  }

  function linkRows(view, items, path, context) {
    [...view.body.rows].forEach((row, index) => {
      row.dataset.href = "true";
      row.addEventListener("click", () => context.navigate(path(items[index])));
    });
  }

  window.FTFactorDetails = Object.freeze({factorDetail, familyDetail, setDetail});
})();
