(() => {
  const catalog = () => window.FTFactorCatalog;

  async function list(context, page = "families", requestedScope = "public") {
    context.activeNav("factors");
    context.setHeading(context.t("因子库"), "FactorTester");
    context.toolbar.append(window.FTFactorList.headerTabs(context, page));
    context.content.replaceChildren(FTUI.loading(context.t("正在读取因子库…")));
    let data = await catalog().load(context, {
      library: page !== "sets", sets: page === "sets",
    });
    if (!catalog().isCurrent(context)) return;
    const root = document.createElement("div");
    root.className = "library-page";
    const familyScope = window.FTFactorList.normalizeFamilyScope(
      requestedScope, data.visitor,
    );
    if (page === "families") {
      root.append(window.FTFactorList.familyScopeTabs(
        context, familyScope, data.visitor,
      ));
    } else if (!data.visitor) {
      root.append(window.FTFactorList.subjectScopeTabs(
        context, page, familyScope,
      ));
    }
    const controls = document.createElement("div");
    controls.className = "factor-catalog-controls";
    const search = document.createElement("input");
    search.type = "search";
    search.className = "toolbar-search factor-catalog-search";
    search.placeholder = window.FTFactorList.searchPlaceholder(
      context, page, familyScope,
    );
    search.setAttribute("aria-label", search.placeholder);
    controls.append(searchControl(context, search));
    let groupLoad = null;
    const group = FTFactorGroupFilter.create(
      context, data.groups, ["*"], () => resetAndRender(), {
        onOpen: () => {
          if (data.groupsLoaded || groupLoad) return groupLoad;
          groupLoad = catalog().load(context, {
            groups: true, library: page !== "sets",
          }).then(next => {
            data = next;
            group.setItems(data.groups);
            if (catalog().isCurrent(context)) render();
          }).catch(error => {
            groupLoad = null;
            context.showNotice?.(error.message || context.t("产品组读取失败"), true);
          });
          return groupLoad;
        },
      },
    );
    controls.append(group.element);
    const owner = familyScope === "subordinates"
      ? subordinateFilter(context, data, page, () => resetAndRender()) : null;
    if (owner) controls.append(owner.element);
    root.append(controls);
    const results = document.createElement("div");
    results.className = "library-results";
    root.append(results);
    context.content.replaceChildren(root);

    context.toolbar.append(
      FTUI.refreshButton(context, async () => {
        await catalog().load(context, {
          refresh: true,
          library: page !== "sets",
          sets: true,
          groups: true,
        });
        if (!catalog().isCurrent(context)) return;
        await list(context, page, familyScope);
      }),
    );
    const canModify = Boolean(context.session) && (
      page === "factors" && familyScope === "mine"
      || page === "sets" && familyScope === "mine"
      || page === "families" && (
        familyScope === "mine"
        || familyScope === "public" && context.session.role === "super_admin"
      )
    );
    const canAddFactor = Boolean(context.session) && page === "families";
    if (canModify) {
      const label = page === "factors"
        ? context.t("新增因子")
        : page === "sets"
          ? context.t("新增因子集合")
          : context.t("新增因子家族");
      const publicMode = page === "families" && familyScope === "public"
        ? "&visibility=public" : "";
      const path = page === "factors"
        ? "/factors/factor/new?mode=create"
        : page === "sets"
          ? "/factors/set/new?mode=create"
        : `/factors/family/new?mode=create${publicMode}`;
      context.toolbar.append(window.FTFactorList.iconButton(
        context, label, "plus", () => context.navigate(path),
        "factor-catalog-add-action",
      ));
    }
    let tablePage = 1;
    const render = () => window.FTFactorList.render(context, data, results, {
      page,
      scope: familyScope,
      query: search.value.trim().toLowerCase(),
      groupRefs: group.values,
      ownerUsernames: owner?.values ?? ["*"],
      tablePage,
      onPageChange: value => { tablePage = value; render(); },
      canModify,
      canAddFactor,
      onTransfer: page === "families" && canModify && context.session?.role === "super_admin"
        ? item => transferItem(context, familyScope, item) : null,
      onDelete: item => removeItem(context, page, familyScope, item),
      onEdit: item => editItem(context, page, familyScope, item),
      onAddFactor: page === "families"
        ? item => addFactor(context, item)
        : null,
    });
    function resetAndRender() { tablePage = 1; render(); }
    let searchTimer;
    search.addEventListener("input", () => {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(() => {
        if (catalog().isCurrent(context)) resetAndRender();
      }, 100);
    });
    render();
  }

  function editItem(context, page, scope, item) {
    const ref = page === "families"
      ? item?.family_ref || item?.factor_family_alias || item?.factor_family_name
      : page === "sets"
        ? item?.target_ref || item?.set_ref
        : item?.factor_ref || item?.factor_alias;
    if (!ref) {
      context.showNotice?.(context.t("找不到可编辑的引用"), true);
      return;
    }
    const path = page === "families"
      ? `/factors/family/${encodeURIComponent(ref)}?mode=edit`
        + (scope === "public" ? "&visibility=public" : "")
      : page === "sets"
        ? `/factors/set/${encodeURIComponent(ref)}?mode=edit`
        : `/factors/factor/${encodeURIComponent(ref)}?mode=edit`;
    context.navigate(path);
  }

  function addFactor(context, item) {
    const familyRef = item?.family_ref || item?.factor_family_alias
      || item?.factor_family_name;
    if (!familyRef) {
      context.showNotice?.(context.t("找不到因子家族引用"), true);
      return;
    }
    const query = new URLSearchParams({
      mode: "create",
      family_ref: familyRef,
    });
    context.navigate(`/factors/factor/new?${query.toString()}`);
  }

  async function removeItem(context, page, scope, item) {
    if (page === "sets") {
      const targetRef = String(item?.target_ref || item?.set_ref || "").trim();
      if (!targetRef || !window.confirm(context.t("确认删除该因子集合？"))) return;
      try {
        await context.api(
          `/api/factor-library/factor-sets?target_ref=${encodeURIComponent(targetRef)}`,
          {method: "DELETE"},
        );
        context.showNotice?.(context.t("已删除"));
        await catalog().load(context, {refresh: true, sets: true});
        if (catalog().isCurrent(context)) list(context, page, scope);
      } catch (error) {
        context.showNotice?.(error.message || context.t("删除失败"), true);
      }
      return;
    }
    const familyAlias = String(
      item?.factor_family_alias || item?.factor_family_name || "",
    ).trim();
    const label = String(
      page === "families" ? modelFamilyLabel(item) : item?.factor_alias || "",
    ).trim();
    if (!familyAlias) return;
    const factorCount = page === "families"
      ? Math.max(0, Number(item?.factor_count || 0)) : 0;
    let impact = null;
    if (page === "families") {
      try { impact = await confirmFamilyChange(context, scope === "public" ? "public" : "custom", familyAlias, label); }
      catch (error) {context.showNotice?.(error.message, true); return;}
    }
    const confirmed = page === "families" ? Boolean(impact) : window.confirm(
      context.t("确认删除“%@”？").replace("%@", label || familyAlias));
    if (!confirmed) return;
    const endpoint = page === "families"
      ? scope === "public"
        ? `/api/factor-library/families/public/${encodeURIComponent(familyAlias)}`
        : `/api/factor-library/families/custom/${encodeURIComponent(familyAlias)}`
      : `/api/factor-library/configurations/${encodeURIComponent(familyAlias)}`
        + `?factor_alias=${encodeURIComponent(item.factor_alias || "")}`
        + `&scope_key=${encodeURIComponent(item.scope_key || item.product_group || "default")}`;
    try {
      await context.api(endpoint + (impact ? `?revision=${encodeURIComponent(impact.revision)}` : ""), {
        method: "DELETE",
        ...(page === "families" ? {} : {body: JSON.stringify({})}),
      });
      context.showNotice?.(context.t("已删除"));
      await catalog().load(context, {
        refresh: true, library: page !== "sets", sets: page === "sets", groups: true,
      });
      if (catalog().isCurrent(context)) list(context, page, scope);
    } catch (error) {
      context.showNotice?.(error.message || context.t("删除失败"), true);
    }
  }

  async function confirmFamilyChange(context, kind, alias, label, transfer = false) {
    const impact = await context.api(`/api/factor-library/families/${kind}/${encodeURIComponent(alias)}/impact`);
    return await confirmFamilyDeletion(context, label || alias, impact.factor_count, impact, transfer) ? impact : null;
  }

  async function transferItem(context, scope, item) {
    const kind = scope === "public" ? "public" : "custom";
    const alias = item.factor_family_alias || item.factor_family_name;
    try {
      const impact = await confirmFamilyChange(context, kind, alias, modelFamilyLabel(item), true);
      if (!impact) return;
      await context.api(`/api/factor-library/families/${kind}/${encodeURIComponent(alias)}/transfer`,
        {method: "POST", body: JSON.stringify({revision: impact.revision})});
      context.showNotice?.(context.t("归属已转换，集合历史已记录"));
      await catalog().load(context, {refresh: true, library: true, sets: true});
      if (catalog().isCurrent(context)) await list(context, "families", scope === "public" ? "mine" : "public");
    } catch (error) {context.showNotice?.(error.message || context.t("转换失败"), true);}
  }

  function confirmFamilyDeletion(context, label, factorCount, impact = {}, transfer = false) {
    return new Promise(resolve => {
      const dialog = document.createElement("dialog");
      const card = document.createElement("form");
      card.method = "dialog";
      card.className = "dialog-card factor-family-delete-card";
      const title = document.createElement("h2");
      title.textContent = context.t(transfer ? "转换因子家族归属" : "删除因子家族");
      const message = document.createElement("p");
      message.textContent = context.t(transfer ? "确认转换“%@”？" : "确认删除“%@”？").replace("%@", label);
      card.append(title, message);
      if (factorCount > 0 || impact.factor_sets?.length) {
        const warning = document.createElement("p");
        warning.className = "form-error factor-family-delete-warning";
        warning.setAttribute("role", "alert");
        warning.textContent = context.t(
          `影响 ${factorCount} 个已登记因子、${impact.factor_sets?.length || 0} 个因子集合。${transfer ? "保留本人的参数并重新登记，其他用户的相关登记将移除。" : "相关因子登记将移除。"}集合会生成新版本并记录成员变化，历史记录和测试快照保留。`,
        );
        card.append(warning);
      }
      if (impact.registrations?.length) card.append(FTUI.table(
        [context.t("用户"), context.t("因子数")], impact.registrations.map(row => [row.username, row.factor_count]),
      ).shell);
      if (impact.factor_sets?.length) card.append(FTUI.table(
        [context.t("用户"), context.t("受影响集合"), context.t("移除或替换成员数")],
        impact.factor_sets.map(row => [row.username, row.alias, row.affected_factor_refs.length]),
      ).shell);
      const actions = document.createElement("div");
      actions.className = "dialog-actions";
      const cancel = FTUI.actionButton(
        context.t("取消"), () => dialog.close("cancel"), {variant: "secondary"},
      );
      cancel.type = "button";
      const confirm = FTUI.actionButton(
        context.t(transfer ? "确认转换并处理依赖" : factorCount > 0 ? "删除家族及因子" : "删除"),
        () => dialog.close("confirm"), {
          variant: factorCount > 0 ? "danger" : "warning",
        },
      );
      confirm.type = "button";
      actions.append(cancel, confirm);
      card.append(actions);
      dialog.append(card);
      dialog.addEventListener("close", () => {
        const accepted = dialog.returnValue === "confirm";
        dialog.remove();
        resolve(accepted);
      }, {once: true});
      document.body.append(dialog);
      if (typeof dialog.showModal === "function") dialog.showModal();
      else dialog.setAttribute("open", "");
    });
  }

  function modelFamilyLabel(item) {
    return item?.factor_family_name || item?.factor_family_alias
      || item?.family_ref || "";
  }

  function searchControl(context, search) {
    const section = document.createElement("section");
    section.className = "ft-multi-select-filter factor-catalog-search-control";
    const heading = document.createElement("div");
    heading.className = "ft-multi-select-heading";
    const title = document.createElement("h2");
    title.textContent = context.t("搜索");
    heading.append(title);
    section.append(heading, search);
    return section;
  }

  function subordinateFilter(context, data, page, onChange) {
    const values = page === "sets"
      ? (data.setScopes?.subordinates || [])
      : (data.familyScopes?.subordinates?.[
        page === "families" ? "families" : "factors"
      ] || []);
    const owners = new Map();
    values.forEach(item => {
      const username = String(item?.owner_username || "").trim();
      if (!username) return;
      owners.set(username, String(item?.owner_alias || username));
    });
    return FTMultiSelectFilter.create(context, {
      title: context.t("按下级用户筛选"),
      className: "factor-subordinate-filter",
      menuClass: "factor-subordinate-filter-menu",
      searchPlaceholder: context.t("搜索下级用户"),
      items: [
        {value: "*", label: context.t("全部下级用户"), exclusive: true},
        ...[...owners].map(([value, label]) => ({value, label, description: value})),
      ],
      selected: ["*"],
      onChange,
    });
  }

  window.FTFactorCatalogList = Object.freeze({list, confirmFamilyChange});
})();
