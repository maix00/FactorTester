(() => {
  const model = () => window.FTFactorModel;

  function pageTabs(context, active) {
    const tabs = document.createElement("div");
    tabs.className = "library-tabs";
    for (const [id, label, path] of [
      ["families", context.t("因子家族"), "/factors/families"],
      ["factors", context.t("因子"), "/factors"],
      ["sets", context.t("因子集合"), "/factors/sets"],
    ]) {
      const button = document.createElement("button");
      button.className = `library-tab${id === active ? " active" : ""}`;
      button.textContent = label;
      button.addEventListener("click", () => context.navigate(path));
      tabs.append(button);
    }
    return tabs;
  }

  function searchPlaceholder(context, page) {
    if (page === "families") return context.t("搜索因子家族");
    if (page === "sets") return context.t("搜索因子集合");
    return context.t("搜索因子");
  }

  function groupFilter(context, data, page) {
    if (page === "families") return null;
    const select = document.createElement("select");
    select.className = "toolbar-select";
    select.title = context.t("按产品组筛选");
    const choices = [
      ["*", context.t("全部产品组")],
      ["", context.t("未绑定产品组")],
      ...[...model().productGroupNames(data.groups).entries()]
        .sort((left, right) => String(left[1]).localeCompare(String(right[1]), "zh-CN")),
    ];
    for (const [value, label] of choices) {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = label;
      select.append(option);
    }
    return select;
  }

  function render(context, data, mount, {page, query, groupRef}) {
    if (page === "families") return renderFamilies(context, data, mount, query);
    return renderSubjects(context, data, mount, {page, query, groupRef});
  }

  function renderFamilies(context, data, mount, query) {
    const rows = data.families.filter(item => model().matches(item, query));
    if (!rows.length) {
      mount.replaceChildren(FTUI.empty(
        context.t("没有匹配的因子家族"), context.t("请更换关键词"),
      ));
      return;
    }
    const view = FTUI.table(
      [context.t("因子家族"), context.t("分类"), context.t("来源"), context.t("所有者"), context.t("因子数")],
      rows.map(item => [
        model().familyName(item),
        (item.categories || []).join("、"),
        origin(item, context),
        model().owner(item),
        item.factor_count || 0,
      ]),
    );
    linkRows(view, rows, item =>
      `/factors/family/${encodeURIComponent(item.family_ref)}`, context,
    );
    mount.replaceChildren(view.shell);
  }

  function renderSubjects(context, data, mount, {page, query, groupRef}) {
    const names = model().productGroupNames(data.groups);
    const bySubject = model().subjectGroups(data.groups);
    const kind = page === "sets" ? "factor-set" : "factor";
    const values = kind === "factor-set" ? data.sets : data.factors;
    const items = values.map(value => ({kind, value})).filter(item => {
      const refs = model().productGroupRefs(item, bySubject);
      const groupMatches = groupRef === "*"
        || (groupRef === "" ? refs.length === 0 : refs.includes(groupRef));
      const labels = model().groupLabels(
        item, names, bySubject, context.t("未绑定产品组"),
      );
      return groupMatches && model().matches({
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
      : [context.t("因子"), context.t("因子家族"), context.t("来源"), context.t("所有者"), context.t("产品组")];
    const rows = items.map(item => kind === "factor-set" ? [
      item.value.title_zh || item.value.set_id,
      item.value.member_count || 0,
      model().owner(item.value),
      visibility(item.value, context),
      model().groupLabels(item, names, bySubject, context.t("未绑定产品组")).join("、"),
    ] : [
      item.value.factor_alias,
      item.value.factor_family_alias,
      origin(item.value, context),
      model().owner(item.value),
      model().groupLabels(item, names, bySubject, context.t("未绑定产品组")).join("、"),
    ]);
    const view = FTUI.table(headers, rows);
    linkRows(view, items, item => item.kind === "factor"
      ? `/factors/factor/${encodeURIComponent(item.value.factor_ref)}`
      : `/factors/set/${encodeURIComponent(item.value.target_ref || item.value.set_ref)}`,
    context);
    mount.replaceChildren(view.shell);
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
    groupFilter,
    pageTabs,
    render,
    searchPlaceholder,
  });
})();
