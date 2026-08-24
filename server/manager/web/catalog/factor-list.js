(() => {
  const model = () => window.FTFactorModel;
  function headerTabs(context, active) {
    const tabs = document.createElement("nav");
    tabs.className = "research-section-tabs factor-catalog-tabs";
    tabs.setAttribute("aria-label", context.t("因子库页面"));
    for (const [id, label, path] of [
      ["families", context.t("因子家族"), "/factors/families"],
      ["factors", context.t("因子"), "/factors"],
      ["sets", context.t("因子集合"), "/factors/sets"],
    ]) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `research-section-tab${id === active ? " active" : ""}`;
      button.textContent = label;
      button.setAttribute("aria-current", id === active ? "page" : "false");
      button.addEventListener("click", () => context.navigate(path));
      tabs.append(button);
    }
    return tabs;
  }

  function searchPlaceholder(context, page, scope = "") {
    if (page === "families" && scope === "subordinates") {
      return context.t("搜索下级用户或因子家族");
    }
    if (page === "families") return context.t("搜索因子家族");
    if (page === "sets") return context.t("搜索因子集合");
    return context.t("搜索因子");
  }

  function normalizeFamilyScope(scope, visitor = false) {
    const value = ["public", "mine", "subordinates"].includes(scope)
      ? scope : "public";
    return visitor && value !== "public" ? "public" : value;
  }

  function familyScopeTabs(context, active, visitor = false) {
    const tabs = document.createElement("nav");
    tabs.className = "research-section-tabs factor-family-scope-tabs";
    tabs.setAttribute("aria-label", context.t("因子家族范围"));
    const definitions = [
      ["public", context.t("公共因子家族")],
      ["mine", context.t("我的因子家族")],
      ["subordinates", context.t("下级用户因子家族")],
    ];
    for (const [id, label] of definitions) {
      if (visitor && id !== "public") continue;
      const button = document.createElement("button");
      button.type = "button";
      button.className = `research-section-tab${id === active ? " active" : ""}`;
      button.textContent = label;
      button.setAttribute("aria-current", id === active ? "page" : "false");
      button.addEventListener("click", () => context.navigate(
        `/factors/families?scope=${encodeURIComponent(id)}`,
      ));
      tabs.append(button);
    }
    return tabs;
  }

  function subjectScopeTabs(context, page, active) {
    const tabs = document.createElement("nav");
    tabs.className = "research-section-tabs factor-subject-scope-tabs";
    tabs.setAttribute("aria-label", context.t(
      page === "sets" ? "因子集合范围" : "因子范围",
    ));
    const noun = page === "sets" ? "因子集合" : "因子";
    for (const [id, prefix] of [["mine", "我的"], ["subordinates", "下级用户"]]) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `research-section-tab${id === active ? " active" : ""}`;
      button.textContent = context.t(`${prefix}${noun}`);
      button.setAttribute("aria-current", id === active ? "page" : "false");
      const path = page === "sets" ? "/factors/sets" : "/factors";
      button.addEventListener("click", () => context.navigate(
        `${path}?scope=${encodeURIComponent(id)}`,
      ));
      tabs.append(button);
    }
    return tabs;
  }

  function render(context, data, mount, {
    page, query, groupRefs = ["*"], ownerUsernames = ["*"], scope = "public",
    tablePage = 1, onPageChange = () => {},
  }) {
    if (page === "families") {
      return renderFamilies(context, data, mount, {
        query, scope, groupRefs, ownerUsernames, tablePage, onPageChange,
      });
    }
    return renderSubjects(context, data, mount, {
      page, query, groupRefs, ownerUsernames, scope, tablePage, onPageChange,
    });
  }

  function renderFamilies(context, data, mount, {
    query, scope, groupRefs, ownerUsernames, tablePage, onPageChange,
  }) {
    const scoped = dataForScope(data, scope);
    const ownerMatches = ownerPredicate(ownerUsernames);
    const allowedFamilies = familyRefsForGroups(data, scoped, groupRefs);
    const rows = scoped.families.filter(item => (
      model().matchesFamily(item, query)
      && ownerMatches(item)
      && (!allowedFamilies || allowedFamilies.has(item.family_ref))
    ));
    const panel = document.createElement("section");
    panel.className = `factor-family-scope-panel ${scope}`;
    const heading = document.createElement("h2");
    heading.textContent = context.t(scopeTitle(scope));
    panel.append(heading);
    if (!rows.length) {
      panel.append(FTUI.empty(
        context.t(scopeEmpty(scope)),
        context.t("没有匹配的因子家族"),
      ));
      mount.replaceChildren(panel);
      return;
    }
    const view = FTUI.pagedTable(
      [context.t("原类名"), context.t("说明"), context.t("分类"), context.t("来源"), context.t("所有者"), context.t("因子数")],
      rows.map(item => [
        model().familyName(item),
        model().description(item),
        (item.categories || []).join("、"),
        origin(item, context),
        model().owner(item),
        item.factor_count || 0,
      ]),
      pagingOptions(context, tablePage, onPageChange),
    );
    linkRows(view, rows.slice(view.start, view.start + view.pageSize), item =>
      `/factors/family/${encodeURIComponent(item.family_ref)}`, context,
    );
    panel.append(view.shell);
    mount.replaceChildren(panel);
  }

  function familyKind(value) {
    const owner = String(value?.owner_username || "");
    if (owner && owner !== "__public_jobs__") return "private";
    const kind = String(
      value?.factor_kind || value?.source || "",
    ).trim().toLowerCase();
    if (kind === "public") return "public";
    if (String(value?.owner_username || "") === "__public_jobs__") {
      return "public";
    }
    return "private";
  }

  function dataForScope(data, scope) {
    const scopes = data.familyScopes || data.family_scopes;
    if (scopes && scopes[scope]) return scopes[scope];
    const families = (data.families || []).filter(item => {
      if (scope === "public") return familyKind(item) === "public";
      if (scope === "mine") {
        return familyKind(item) !== "public"
          && String(item.owner_username || "") === String(data.principal || "");
      }
      return familyKind(item) !== "public"
        && String(item.owner_username || "") !== String(data.principal || "");
    });
    const refs = new Set(families.map(item => item.family_ref));
    return {
      ...data,
      families,
      factors: (data.factors || []).filter(item => refs.has(
        item.family_ref || item.factor_family_ref,
      )),
    };
  }

  function scopeTitle(scope) {
    if (scope === "mine") return "我的因子家族";
    if (scope === "subordinates") return "下级用户因子家族";
    return "公共因子家族";
  }

  function scopeEmpty(scope) {
    if (scope === "mine") return "暂无我的因子家族";
    if (scope === "subordinates") return "暂无下级用户因子家族";
    return "暂无公共因子家族";
  }

  function renderSubjects(context, data, mount, {
    page, query, groupRefs, ownerUsernames, scope, tablePage, onPageChange,
  }) {
    const names = model().productGroupNames(data.groups);
    const bySubject = model().subjectGroups(data.groups);
    const kind = page === "sets" ? "factor-set" : "factor";
    const scoped = dataForScope(data, scope);
    const values = kind === "factor-set"
      ? (data.setScopes?.[scope] || [])
      : scoped.factors;
    const selectedGroups = Array.isArray(groupRefs) ? groupRefs : ["*"];
    const allGroups = selectedGroups.includes("*") || !selectedGroups.length;
    const ownerMatches = ownerPredicate(ownerUsernames);
    const items = values.map(value => ({kind, value})).filter(item => {
      const refs = model().productGroupRefs(item, bySubject);
      const groupMatches = allGroups || selectedGroups.some(groupRef => (
        groupRef === "" ? refs.length === 0 : refs.includes(groupRef)
      ));
      const labels = model().groupLabels(
        item, names, bySubject, context.t("未绑定产品组"),
      );
      return groupMatches && ownerMatches(item.value) && model().matches({
        ...item.value,
        product_group_labels: labels.join(" "),
      }, query);
    });
    if (!items.length) {
      mount.replaceChildren(FTUI.empty(
        kind === "factor-set" ? context.t("没有匹配的因子集合") : context.t("没有匹配的因子"),
        context.t("请更换关键词或产品组筛选"),
      ));
      return;
    }
    const headers = kind === "factor-set"
      ? [context.t("因子集合"), context.t("成员数"), context.t("所有者"), context.t("可见范围"), context.t("产品组")]
      : [context.t("因子"), context.t("原类名"), context.t("说明"), context.t("来源"), context.t("所有者"), context.t("产品组")];
    const rows = items.map(item => kind === "factor-set" ? [
      item.value.title_zh || item.value.set_id,
      item.value.member_count || 0,
      model().owner(item.value),
      visibility(item.value, context),
      model().groupLabels(item, names, bySubject, context.t("未绑定产品组")).join("、"),
    ] : [
      item.value.factor_alias,
      model().familyName(item.value),
      model().description(item.value),
      origin(item.value, context),
      model().owner(item.value),
      model().groupLabels(item, names, bySubject, context.t("未绑定产品组")).join("、"),
    ]);
    const view = FTUI.pagedTable(
      headers, rows, pagingOptions(context, tablePage, onPageChange),
    );
    linkRows(view, items.slice(view.start, view.start + view.pageSize), item => item.kind === "factor"
      ? `/factors/factor/${encodeURIComponent(item.value.factor_ref)}`
      : `/factors/set/${encodeURIComponent(item.value.target_ref || item.value.set_ref)}`,
    context);
    mount.replaceChildren(view.shell);
  }

  function ownerPredicate(ownerUsernames) {
    const selected = Array.isArray(ownerUsernames) ? ownerUsernames : ["*"];
    if (!selected.length || selected.includes("*")) return () => true;
    const values = new Set(selected.map(value => String(value || "")));
    return item => values.has(String(item?.owner_username || ""));
  }

  function familyRefsForGroups(data, scoped, groupRefs) {
    const selected = Array.isArray(groupRefs) ? groupRefs : ["*"];
    if (!selected.length || selected.includes("*")) return null;
    const bySubject = model().subjectGroups(data.groups);
    const refs = new Set();
    (scoped.factors || []).forEach(value => {
      const subject = {kind: "factor", value};
      const groups = model().productGroupRefs(subject, bySubject);
      if (selected.some(groupRef => (
        groupRef === "" ? groups.length === 0 : groups.includes(groupRef)
      ))) refs.add(value.family_ref || value.factor_family_ref);
    });
    return refs;
  }

  function pagingOptions(context, page, onPageChange) {
    return {
      page,
      pageSize: 20,
      onPageChange,
      previousLabel: context.t("上一页"),
      nextLabel: context.t("下一页"),
      pageLabel: (current, total) => context.t("第 %lld / %lld 页")
        .replace("%lld", String(current)).replace("%lld", String(total)),
      totalLabel: total => `${total} ${context.t("项")}`,
    };
  }

  function origin(value, context) {
    return context.t(value.factor_kind === "public" ? "公共" : "用户");
  }

  function visibility(value, context) {
    if (value.visibility === "synced") return context.t("本地与服务器");
    if (value.visibility === "local") return context.t("仅本地");
    return context.t("仅服务器");
  }

  function linkRows(view, items, path, context) {
    [...view.body.rows].forEach((row, index) => {
      row.dataset.href = "true";
      row.addEventListener("click", () => context.navigate(path(items[index])));
    });
  }

  window.FTFactorList = Object.freeze({
    familyScopeTabs,
    headerTabs,
    normalizeFamilyScope,
    render,
    searchPlaceholder,
    subjectScopeTabs,
  });
})();
