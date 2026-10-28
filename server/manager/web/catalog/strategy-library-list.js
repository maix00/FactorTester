(() => {
  const scopes = [
    ["public", "公共策略"],
    ["mine", "我的自定义策略"],
    ["subordinates", "下级自定义策略"],
  ];
  const visibilityValues = ["private", "shared", "public"];

  async function render(context, requestedScope = "public", requestedKind = "strategy_family") {
    const scope = scopes.some(item => item[0] === requestedScope)
      ? requestedScope : "mine";
    const objectKind = scope === "public"
      ? (requestedKind === "strategy" ? "strategy" : "strategy_family") : "strategy";
    context.activeNav("strategies");
    context.setHeading(context.t("策略库"), context.t("策略库"));
    if (scope === "mine") context.toolbar.append(FTUI.iconButton(
      context, "plus", "新增策略", () => context.navigate("/strategies/new?mode=create"),
      {className: "strategy-library-add-action"},
    ));
    context.content.replaceChildren(FTUI.loading(context.t("正在读取策略库…")));
    const query = context.tabSession.strategyLibraryList || {page: 1, query: ""};
    context.tabSession.strategyLibraryList = query;
    query.objectKind = objectKind;
    query.requestID = Number(query.requestID || 0) + 1;
    const requestID = query.requestID;
    let value;
    try {
      value = await FTStrategyLibraryRuntime.list(context, {
        scope, objectKind, page: query.page, query: query.query,
      });
    } catch (error) {
      if (query.requestID !== requestID) return;
      context.content.replaceChildren(FTUI.empty(
        context.t("无法读取策略库"), error.message || String(error),
      ));
      return;
    }
    if (context.isRouteCurrent?.() === false || query.requestID !== requestID) return;
    const root = document.createElement("section");
    root.className = "library-page strategy-library-page";
    root.append(scopeTabs(context, scope));
    if (scope === "public") root.append(objectTabs(context, objectKind));
    const controls = document.createElement("div");
    controls.className = "strategy-library-controls";
    const search = document.createElement("input");
    search.type = "search";
    search.value = query.query || "";
    search.placeholder = context.t("搜索策略名称或引用");
    search.setAttribute("aria-label", search.placeholder);
    controls.append(search);
    controls.append(FTUI.refreshButton(context, async () => {
      await context.api('/api/catalog/refresh', {method: 'POST'});
      await render(context, scope, objectKind);
    }));
    root.append(controls);
    const mount = document.createElement("div");
    mount.className = "strategy-library-results";
    root.append(mount);
    context.content.replaceChildren(root);
    const redraw = nextPage => {
      query.page = nextPage || 1;
      query.query = search.value.trim();
      void render(context, scope, objectKind);
    };
    search.addEventListener("input", () => {
      clearTimeout(search._strategySearchTimer);
      search._strategySearchTimer = setTimeout(() => redraw(1), 250);
    });
      mount.append(table(context, value, scope, redraw, objectKind));
  }

  function scopeTabs(context, active) {
    const nav = document.createElement("nav");
    nav.className = "research-section-tabs strategy-library-scope-tabs";
    nav.setAttribute("aria-label", context.t("策略库范围"));
    for (const [id, label] of scopes) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `research-section-tab${id === active ? " active" : ""}`;
      button.textContent = context.t(label);
      button.setAttribute("aria-current", id === active ? "page" : "false");
      button.addEventListener("click", () => {
        context.tabSession.strategyLibraryList = {page: 1, query: ""};
        context.navigate(`/strategies?scope=${id}${id === "public" ? "&kind=strategy_family" : ""}`);
      });
      nav.append(button);
    }
    return nav;
  }

  function objectTabs(context, active) {
    const nav = document.createElement("nav");
    nav.className = "research-section-tabs strategy-library-object-tabs";
    nav.setAttribute("aria-label", context.t("公共策略库对象类型"));
    for (const [id, label] of [["strategy_family", "策略家族"], ["strategy", "策略"]]) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `research-section-tab${id === active ? " active" : ""}`;
      button.textContent = context.t(label);
      button.setAttribute("aria-current", id === active ? "page" : "false");
      button.addEventListener("click", () => {
        context.tabSession.strategyLibraryList = {...context.tabSession.strategyLibraryList, page: 1};
        context.navigate(`/strategies?scope=public&kind=${encodeURIComponent(id)}`);
      });
      nav.append(button);
    }
    return nav;
  }

  function table(context, value, scope, redraw, objectKind = "strategy") {
    const items = Array.isArray(value?.items) ? value.items : [];
    if (!items.length) return FTUI.empty(
      context.t(scope === "public" ? "暂无公共策略模板"
        : scope === "mine" ? "暂无我的自定义策略" : "暂无下级自定义策略"),
      context.t("策略库中还没有符合条件的策略"),
    );
    const rows = items.map(item => scope === "public" && objectKind === "strategy_family" ? [
      nameCell(context, item),
      (item.strategy_refs || []).length,
      (item.configuration_schema?.fields || []).map(field => field.label).join("、") || "—",
      item.family_revision_ref || "—",
      context.t("公共 · 只读"),
      context.t("供配置页生成策略参数表单"),
    ] : scope === "public" ? [
      nameCell(context, item),
      familyName(value?.families, item.family_ref),
      ({
        cross_sectional_group: context.t("因子横截面分组策略"),
        threshold: context.t("因子阈值策略"),
      })[item.kind] || item.kind || "—",
      (item.factor_roles || []).map(role => role.label || role.key).join("、") || "—",
      item.version ? `r${item.version}` : "—",
      context.t("内置 · 只读"),
      context.t("可供回测配置选择"),
    ] : [
      nameCell(context, item),
      FTUI.userDisplay(item.owner_ref, item.owner_alias),
      item.current_revision?.entrypoint || "—",
      hooks(item),
      revision(item),
      visibility(context, item, redraw),
      actions(context, item),
    ]);
    const headers = scope === "public" && objectKind === "strategy_family" ? [
      context.t("策略家族"), context.t("策略实现数"), context.t("注册配置项"),
      context.t("家族版本"), context.t("来源"), context.t("用途"),
    ] : scope === "public" ? [
      context.t("策略"), context.t("所属策略家族"), context.t("策略类型"),
      context.t("因子角色"), context.t("策略版本"),
      context.t("来源"), context.t("用途"),
    ] : [
      context.t("策略"), context.t("所有者"), context.t("策略类型"),
      context.t("Hooks / 因子角色"), context.t("当前版本"),
      context.t("共享范围"), context.t("操作"),
    ];
    return FTUI.pagedTable(headers, rows, {
      remote: true,
      page: Number(value.page) || 1,
      pageSize: Number(value.limit) || 20,
      total: Number(value.total) || items.length,
      pageLabel: (page, total) => `${page} / ${total}`,
      totalLabel: total => `${context.t("共")} ${total} ${context.t("项")}`,
      onPageChange: redraw,
    }).shell;
  }

  function nameCell(context, item) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "strategy-library-link";
    button.textContent = item.name || item.strategy_ref || item.template_ref || item.family_ref;
    if (item.object_kind === "strategy_family" || item.library_kind === "factor_strategy_template") {
      button.disabled = true;
      button.title = context.t("公共策略家族由回测配置选择；版本在提交时冻结");
    } else {
      button.addEventListener("click", () => context.navigate(
        `/strategies/${encodeURIComponent(item.strategy_ref)}`,
      ));
    }
    const cell = document.createElement("span");
    cell.className = "strategy-library-name-cell";
    cell.append(button);
    if (item.description) {
      const detail = document.createElement("small");
      detail.textContent = item.description;
      cell.append(detail);
    }
    return cell;
  }

  function familyName(families, familyRef) {
    const family = (families || []).find(item => item.family_ref === familyRef);
    return family?.name || familyRef || "—";
  }

  function hooks(item) {
    const values = item.current_revision?.hooks || [];
    return Array.isArray(values) ? values.map(value => value.name || value).join("、") || "—" : "—";
  }

  function revision(item) {
    const value = item.current_revision;
    return value?.revision_number ? `r${value.revision_number}` : "—";
  }

  function visibility(context, item, redraw) {
    const select = document.createElement("select");
    visibilityValues.forEach(value => {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = context.t({private: "仅自己", shared: "指定共享", public: "公开"}[value]);
      select.append(option);
    });
    select.value = visibilityValues.includes(item.visibility) ? item.visibility : "private";
    select.disabled = item.access?.can_edit !== true;
    select.addEventListener("change", async () => {
      const previous = item.visibility;
      try {
        await FTStrategyLibraryRuntime.update(context, item.strategy_ref, {
          visibility: select.value,
        });
        item.visibility = select.value;
        context.showNotice?.(context.t("可见性已更新"));
      } catch (error) {
        select.value = previous;
        context.showNotice?.(error.message || context.t("更新失败"), true);
      }
      redraw(1);
    });
    return select;
  }

  function actions(context, item) {
    const root = document.createElement("span");
    root.className = "strategy-library-row-actions";
    root.append(action(context, item, "person.2", "共享", share));
    root.append(action(context, item, "square.and.pencil", "编辑", edit));
    root.append(action(context, item, "trash", "删除", remove, "danger-action"));
    return root;
  }

  function action(context, item, symbol, label, handler, className = "") {
    const button = FTUI.iconButton(context, symbol, label, event => {
      event?.stopPropagation?.();
      void handler(context, item);
    }, {className: `strategy-library-icon-action ${className}`.trim()});
    const capability = label === "共享" ? "can_share"
      : label === "编辑" ? "can_edit" : "can_delete";
    button.disabled = item.access?.[capability] !== true;
    return button;
  }

  async function share(context, item) {
    const target = window.prompt(context.t("请输入共享用户标识"));
    if (!target?.trim()) return;
    try {
      await FTStrategyLibraryRuntime.grant(context, item.strategy_ref, target.trim());
      context.showNotice?.(context.t("已共享策略"));
    } catch (error) {
      context.showNotice?.(error.message || context.t("共享失败"), true);
    }
  }

  function edit(context, item) {
    context.navigate(`/strategies/${encodeURIComponent(item.strategy_ref)}?mode=edit`);
  }

  async function remove(context, item) {
    if (!window.confirm(context.t("确认归档该策略？"))) return;
    try {
      await FTStrategyLibraryRuntime.remove(context, item.strategy_ref);
      context.showNotice?.(context.t("策略已归档"));
      context.navigate("/strategies?scope=mine");
    } catch (error) {
      context.showNotice?.(error.message || context.t("删除失败"), true);
    }
  }

  window.FTStrategyLibraryList = Object.freeze({render});
})();
