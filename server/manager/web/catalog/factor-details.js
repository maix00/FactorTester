(() => {
  const model = () => window.FTFactorModel;

  async function factorDetail(context, data, targetRef, mode = "view", nativeRequest) {
    if (mode === "create" || mode === "edit") {
      return factorEditor(context, data, targetRef, mode);
    }
    let factor = data.factors.find(item => item.factor_ref === targetRef);
    const frozen = factor ? null : model().decodeFrozenFactorRef(targetRef);
    if (!factor && !frozen) {
      throw new Error(context.t("因子不存在或当前端口无法解析该引用"));
    }
    if (!factor) factor = projectedFactor(data.factors, frozen);
    if (factor && frozen) factor = frozenProjection(factor, frozen);
    if (!factor) factor = await localFactor(frozen, nativeRequest);
    context.setHeading(factor.factor_alias || context.t("因子详情"), model().familyName(factor));
    const factorRef = factor.factor_ref || targetRef;
    context.toolbar?.append(context.button(context.t("查看因子序列"), () => {
      context.navigate(`/factor-series?factor_ref=${encodeURIComponent(factorRef)}`);
    }, context.t("使用冻结因子配置运行序列查看任务")));
    if (factor.can_edit && context.session) {
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
    appendSummary(context, root, factor);
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

  async function factorEditor(context, data, targetRef, mode) {
    if (!context.session) throw new Error(context.t("登录后才能编辑因子"));
    let factor = data.factors.find(item => item.factor_ref === targetRef
      || item.factor_alias === targetRef || item.id === targetRef);
    const factorID = factor?.factor_alias || factor?.id || targetRef;
    if (mode === "edit" && !factorID) throw new Error(context.t("因子不存在"));
    let loaded = factor ? {...factor} : {};
    if (mode === "edit") {
      const value = await context.api(
        `/custom-factors/api/get/${encodeURIComponent(factorID)}`,
      );
      loaded = {...loaded, ...(value.factor || {})};
    }
    context.setHeading(
      mode === "create" ? context.t("新增因子") : loaded.factor_alias || loaded.name || factorID,
      context.t("因子详情"),
    );
    context.updateActiveTab?.({
      title: mode === "create" ? context.t("新增因子") : loaded.factor_alias || loaded.name || factorID,
    });
    const form = document.createElement("form");
    form.className = "detail-stack factor-editor-form";
    const title = document.createElement("h2");
    title.textContent = mode === "create" ? context.t("新增因子") : context.t("编辑因子");
    form.append(title);
    const name = textField(context, "因子类名", loaded.name || loaded.factor_alias || "", {
      readOnly: mode === "edit", required: true,
    });
    const chineseName = textField(context, "中文名称", loaded.chinese_name || "");
    const description = textField(context, "说明", loaded.description || "");
    const category = textField(context, "分类", loaded.category || "自编");
    const source = document.createElement("textarea");
    source.rows = 16;
    source.required = true;
    source.placeholder = context.t("填写继承 FactorFamily 的 Python 类源码");
    source.value = loaded.source_code || "";
    form.append(name, chineseName, description, category, field(context.t("Python 源码"), source));
    const status = document.createElement("small");
    status.className = "form-error";
    const actions = document.createElement("div");
    actions.className = "detail-actions";
    const cancel = context.button(context.t("取消"), () => {
      if (!FTTabReturn.returnToSource(context)) {
        context.closeTab?.(context.tabID);
        context.navigate("/factors");
      }
    });
    cancel.type = "button";
    const save = context.button(context.t("保存"), () => form.requestSubmit());
    save.type = "button"; save.className = "primary";
    actions.append(cancel, save);
    form.append(status, actions);
    context.content.replaceChildren(form);
    form.addEventListener("submit", async event => {
      event.preventDefault();
      save.disabled = true; status.textContent = "";
      try {
        const payload = {
          source_code: source.value,
          chinese_name: chineseName.querySelector("input").value.trim(),
          description: description.querySelector("input").value.trim(),
          category: category.querySelector("input").value.trim(),
        };
        const endpoint = mode === "create"
          ? "/custom-factors/api/create"
          : `/custom-factors/api/update/${encodeURIComponent(factorID)}`;
        const value = await context.api(endpoint, {
          method: "POST", body: JSON.stringify(payload),
        });
        const saved = value.factor || {};
        const ref = saved.name || saved.id || factorID;
        if (context.onSaved) {
          context.onSaved({...saved, factor_alias: saved.factor_alias || ref, name: saved.name || ref});
          return;
        }
        if (FTTabReturn.returnToSource(context, {kind: "factor", ref})) return;
        context.closeTab?.(context.tabID);
        context.navigate(`/factors?updated=${Date.now()}`);
      } catch (error) {
        status.textContent = error.message || context.t("因子保存失败");
        save.disabled = false;
      }
    });
  }

  function textField(context, labelText, value, options = {}) {
    const input = document.createElement("input");
    input.value = value || "";
    input.readOnly = options.readOnly === true;
    input.required = options.required === true;
    return field(labelText, input);
  }

  function field(labelText, input) {
    const label = document.createElement("label");
    label.className = "test-object-field";
    const title = document.createElement("b"); title.textContent = labelText;
    label.append(title, input);
    return label;
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
      owner_alias: frozen.ownerRef,
      owner_ref: frozen.ownerRef,
      git_commit: frozen.gitCommit,
      git_blob: frozen.gitBlob,
      relative_path: frozen.relativePath,
      params: frozen.params,
      factor_kind: "local",
    };
  }

  function appendSummary(context, root, value) {
    const expression = model().factorExpression(value);
    if (!expression && !value.description) return;
    const summary = document.createElement("section");
    summary.className = "factor-family-summary";
    if (value.description) {
      const description = document.createElement("p");
      description.textContent = value.description;
      summary.append(description);
    }
    if (expression && window.katex) {
      const heading = document.createElement("h3");
      heading.textContent = context.t("FactorExpr 公式");
      const formula = document.createElement("div");
      formula.className = "factor-family-formula display-math";
      katex.render(expression, formula, {displayMode: true, throwOnError: false});
      summary.append(heading, formula);
    }
    root.append(summary);
  }

  async function familyDetail(context, data, targetRef) {
    const family = data.families.find(item => item.family_ref === targetRef);
    if (!family) throw new Error(context.t("因子家族不存在或当前端口无法解析该引用"));
    context.setHeading(model().familyName(family), context.t("因子家族"));
    context.updateActiveTab?.({title: model().familyName(family)});
    const root = document.createElement("div");
    root.className = "detail-stack";
    appendSummary(context, root, family);
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
    const first = await loadSetPage(context, selected, frozenRef, 0, nativeRequest);
    const value = first.factor_set || first || {};
    if (context.isRouteCurrent?.() === false) return;
    context.setHeading(value.title_zh || context.t("因子集合"), context.t("因子集合"));
    context.updateActiveTab?.({title: value.title_zh || context.t("因子集合")});
    const root = document.createElement("div");
    root.className = "detail-stack";
    root.append(FTUI.table(
      [context.t("字段"), context.t("值")], FTUI.fieldRows(value),
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
