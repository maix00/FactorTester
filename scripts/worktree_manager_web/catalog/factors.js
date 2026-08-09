(() => {
  let cache = null;

  function current(context) {
    return context.isRouteCurrent?.() !== false;
  }

  async function load(context, refresh = false) {
    if (cache && !refresh) return cache;
    const [library, sets, groups, localSets] = await Promise.all([
      context.api(context.servicePath("/custom-factors/api/client/factor-library")),
      context.api(context.servicePath("/custom-factors/api/client/factor-sets")),
      context.api(context.servicePath("/api/product-groups")),
      nativeLocalFactorSets("catalog").catch(() => ({items: []})),
    ]);
    cache = {
      factors: Array.isArray(library.factors) ? library.factors : [],
      families: Array.isArray(library.families) ? library.families : [],
      sets: mergeFactorSets(sets.items, localSets.items),
      groups: Array.isArray(groups.groups) ? groups.groups : [],
    };
    return cache;
  }

  async function list(context, page = "families") {
    context.activeNav("factors");
    context.setHeading(context.t("因子库"), "FactorTester");
    context.content.replaceChildren(FTUI.loading(context.t("正在读取因子库…")));
    const data = await load(context);
    if (!current(context)) return;
    const root = document.createElement("div");
    root.className = "library-page";
    root.append(pageTabs(context, page));
    const results = document.createElement("div");
    results.className = "library-results";
    root.append(results);
    context.content.replaceChildren(root);

    const search = document.createElement("input");
    search.className = "toolbar-search";
    search.placeholder = page === "families"
      ? context.t("搜索因子家族")
      : context.t("搜索因子、因子集合或产品组");
    context.toolbar.append(
      search,
      context.button("↻", async () => {
        await load(context, true);
        if (!current(context)) return;
        list(context, page);
      }, context.t("刷新")),
    );
    search.addEventListener("input", render);
    render();

    function render() {
      const query = search.value.trim().toLowerCase();
      if (!query) {
        results.replaceChildren(FTUI.empty(
          context.t("输入关键词开始检索"),
          page === "families"
            ? context.t("可检索公共或用户因子家族")
            : context.t("结果将按未绑定产品组及各产品组分别展示"),
        ));
        return;
      }
      if (page === "families") renderFamilies(context, data, results, query);
      else renderFactors(context, data, results, query);
    }
  }

  function pageTabs(context, active) {
    const tabs = document.createElement("div");
    tabs.className = "library-tabs";
    for (const [id, label, path] of [
      ["families", context.t("因子家族"), "/factors/families"],
      ["factors", context.t("因子"), "/factors"],
    ]) {
      const button = document.createElement("button");
      button.className = `library-tab${id === active ? " active" : ""}`;
      button.textContent = label;
      button.addEventListener("click", () => context.navigate(path));
      tabs.append(button);
    }
    return tabs;
  }

  function renderFamilies(context, data, mount, query) {
    const rows = data.families.filter(item => matches(item, query));
    if (!rows.length) {
      mount.replaceChildren(FTUI.empty(
        context.t("没有匹配的因子家族"), context.t("请更换关键词"),
      ));
      return;
    }
    const view = FTUI.table(
      [context.t("因子家族"), context.t("来源"), context.t("所有者"), context.t("因子数")],
      rows.map(item => [
        familyName(item), origin(item), owner(item), item.factor_count || 0,
      ]),
    );
    linkRows(view, rows, item =>
      `/factors/family/${encodeURIComponent(item.family_ref)}`, context,
    );
    [...view.body.rows].forEach(row => row.classList.add("family-row"));
    mount.replaceChildren(view.shell);
  }

  function renderFactors(context, data, mount, query) {
    const groupNames = productGroupNames(data.groups);
    const groupsBySubject = subjectGroups(data.groups);
    const items = [
      ...data.factors.map(value => ({kind: "factor", value})),
      ...data.sets.map(value => ({kind: "factor-set", value})),
    ].filter(item => matchesFactorItem(item, query, groupNames, groupsBySubject));
    if (!items.length) {
      mount.replaceChildren(FTUI.empty(
        context.t("没有匹配的因子"), context.t("请更换因子或产品组关键词"),
      ));
      return;
    }
    const sections = new Map();
    for (const item of items) {
      for (const key of productGroupKeys(item, groupsBySubject)) {
        if (!sections.has(key)) sections.set(key, []);
        sections.get(key).push(item);
      }
    }
    const stack = document.createElement("div");
    stack.className = "factor-group-stack";
    const ordered = [...sections.entries()].sort(([left], [right]) =>
      groupTitle(left, groupNames, context).localeCompare(
        groupTitle(right, groupNames, context), "zh-CN",
      )
    );
    for (const [groupRef, groupItems] of ordered) {
      const section = document.createElement("section");
      section.className = "factor-group-section";
      const heading = document.createElement("h2");
      heading.textContent = groupTitle(groupRef, groupNames, context);
      const view = FTUI.table(
        [context.t("名称"), context.t("类型"), context.t("来源"), context.t("所有者"), context.t("可见范围")],
        groupItems.map(item => [
          itemTitle(item),
          item.kind === "factor" ? context.t("因子") : context.t("因子集合"),
          item.kind === "factor" ? origin(item.value, context) : context.t("用户"),
          item.kind === "factor" ? owner(item.value) : item.value.profile_id,
          item.kind === "factor" ? context.t("仅服务器") : visibility(item.value, context),
        ]),
      );
      linkRows(view, groupItems, item => item.kind === "factor"
        ? `/factors/factor/${encodeURIComponent(item.value.factor_ref)}`
        : `/factors/set/${encodeURIComponent(item.value.target_ref || item.value.set_ref)}`,
      context);
      [...view.body.rows].forEach((row, index) => {
        row.classList.add("factor-row", groupItems[index].kind);
      });
      section.append(heading, view.shell);
      stack.append(section);
    }
    mount.replaceChildren(stack);
  }

  async function factorDetail(context, targetRef) {
    context.activeNav("factors");
    const data = await load(context);
    if (!current(context)) return;
    const factor = data.factors.find(item => item.factor_ref === targetRef);
    if (!factor) throw new Error(context.t("因子不存在或当前端口无法解析该引用"));
    context.setHeading(factor.factor_alias || context.t("因子详情"), familyName(factor));
    const root = document.createElement("div");
    root.className = "detail-stack";
    const expression = factorExpression(factor);
    if (expression && window.katex) {
      const summary = document.createElement("section");
      summary.className = "factor-family-summary";
      const heading = document.createElement("h3");
      heading.textContent = context.t("FactorExpr 公式");
      const formula = document.createElement("div");
      formula.className = "factor-family-formula display-math";
      katex.render(expression, formula, {displayMode: true, throwOnError: false});
      summary.append(heading, formula);
      root.append(summary);
    }
    root.append(FTUI.table([context.t("字段"), context.t("值")], FTUI.fieldRows(factor)).shell);
    if (Array.isArray(factor.params) && factor.params.length) {
      root.append(FTUI.table(
        [context.t("参数"), context.t("值")],
        factor.params.map(item => [item.alias, item.redacted ? context.t("已隐藏") : item.value]),
      ).shell);
    }
    context.content.replaceChildren(root);
  }

  async function familyDetail(context, targetRef) {
    context.activeNav("factors");
    const data = await load(context);
    if (!current(context)) return;
    const family = data.families.find(item => item.family_ref === targetRef);
    if (!family) throw new Error(context.t("因子家族不存在或当前端口无法解析该引用"));
    context.setHeading(familyName(family), context.t("因子家族"));
    const root = document.createElement("div");
    root.className = "detail-stack";
    if (family.description || family.math_expr) {
      const summary = document.createElement("section");
      summary.className = "factor-family-summary";
      if (family.description) {
        const description = document.createElement("p");
        description.textContent = family.description;
        summary.append(description);
      }
      if (family.math_expr) {
        const formula = document.createElement("div");
        formula.className = "factor-family-formula display-math";
        katex.render(family.math_expr, formula, {
          displayMode: true,
          throwOnError: false,
        });
        summary.append(formula);
      }
      root.append(summary);
    }
    root.append(FTUI.table([context.t("字段"), context.t("值")], FTUI.fieldRows(family)).shell);
    const members = data.factors.filter(item => family.factor_refs?.includes(item.factor_ref));
    const view = FTUI.table(
      [context.t("因子"), context.t("来源"), context.t("所有者")],
      members.map(item => [item.factor_alias, origin(item), owner(item)]),
    );
    linkRows(view, members, item =>
      `/factors/factor/${encodeURIComponent(item.factor_ref)}`, context,
    );
    root.append(view.shell);
    context.content.replaceChildren(root);
  }

  async function setDetail(context, targetRef) {
    context.activeNav("factors");
    const data = await load(context);
    if (!current(context)) return;
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
    const payload = selected?.visibility === "local"
      ? await nativeLocalFactorSets("members", {
          target_ref: frozenRef, offset: 0, limit: 100,
        })
      : await context.api(
          context.servicePath(`/custom-factors/api/client/factor-sets/detail?target_ref=${encodeURIComponent(frozenRef)}&limit=100`),
        );
    if (!current(context)) return;
    const value = payload.factor_set || payload || {};
    context.setHeading(
      value.title_zh || context.t("因子集合"), context.t("因子集合")
    );
    const root = document.createElement("div");
    root.className = "detail-stack";
    root.append(FTUI.table([context.t("字段"), context.t("值")], FTUI.fieldRows(value)).shell);
    const members = Array.isArray(value.related_references) ? value.related_references : [];
    const view = FTUI.table(
      [context.t("因子"), context.t("冻结引用")],
      members.map(item => [item.label || item.title_zh, item.target_ref]),
    );
    linkRows(view, members, item =>
      `/factors/factor/${encodeURIComponent(item.target_ref)}`, context,
    );
    root.append(view.shell);
    context.content.replaceChildren(root);
  }

  function productGroupKeys(item, groupsBySubject) {
    const subjectRef = item.kind === "factor"
      ? item.value.factor_ref
      : item.value.set_ref;
    const refs = groupsBySubject.get(subjectRef) || [];
    return refs.length ? refs : [""];
  }
  function productGroupNames(groups) {
    return new Map(groups.map(group => [`product-group:${group.id}`, group.name]));
  }
  function subjectGroups(groups) {
    const index = new Map();
    for (const group of groups) {
      const groupRef = `product-group:${group.id}`;
      for (const subjectRef of [
        ...(Array.isArray(group.factor_refs) ? group.factor_refs : []),
        ...(Array.isArray(group.factor_set_refs) ? group.factor_set_refs : []),
      ]) {
        if (!index.has(subjectRef)) index.set(subjectRef, []);
        index.get(subjectRef).push(groupRef);
      }
    }
    return index;
  }
  function groupTitle(ref, names, context) {
    if (!ref) return context.t("未绑定产品组");
    if (ref.startsWith("name:")) return ref.slice(5);
    return names.get(ref) || ref;
  }
  function matchesFactorItem(item, query, groupNames, groupsBySubject) {
    const labels = productGroupKeys(item, groupsBySubject)
      .map(ref => groupNames.get(ref) || ref);
    return matches({...item.value, product_group_labels: labels.join(" ")}, query);
  }
  function matches(value, query) {
    return JSON.stringify(value || {}).toLowerCase().includes(query);
  }
  function familyName(value) {
    return value.chinese_name || value.factor_family_alias || value.factor_family_name || "";
  }

  function factorExpression(value) {
    for (const key of ["math_expr", "formula", "latex", "factor_expr", "expression"]) {
      const candidate = value?.[key];
      if (typeof candidate === "string" && candidate.trim()) return candidate.trim();
    }
    return "";
  }
  function owner(value) { return value.owner_alias || value.owner_username || ""; }
  function origin(value, context) {
    return context.t(value.factor_kind === "public" ? "公共" : "用户");
  }
  function itemTitle(item) {
    return item.kind === "factor" ? item.value.factor_alias : item.value.title_zh;
  }
  function visibility(value, context) {
    if (value.visibility === "synced") return context.t("已同步");
    if (value.visibility === "local") return context.t("仅本地");
    return context.t("仅服务器");
  }
  function mergeFactorSets(serverItems, localItems) {
    const server = Array.isArray(serverItems) ? serverItems : [];
    const local = Array.isArray(localItems) ? localItems : [];
    const values = server.map(item => ({...item, visibility: "server"}));
    const exact = new Map(values
      .filter(item => item.target_ref)
      .map((item, index) => [item.target_ref, index]));
    for (const item of local) {
      const index = item.target_ref ? exact.get(item.target_ref) : undefined;
      if (index !== undefined) {
        values[index] = {...values[index], ...item, visibility: "synced"};
      } else {
        values.push({...item, visibility: "local"});
      }
    }
    return values;
  }
  async function nativeLocalFactorSets(action, payload = {}) {
    const handler = window.webkit?.messageHandlers?.factorTesterLocalFactorSets;
    if (!handler?.postMessage) return {items: []};
    const value = await handler.postMessage({action, ...payload});
    return value && typeof value === "object" ? value : {items: []};
  }
  function linkRows(view, items, path, context) {
    [...view.body.rows].forEach((row, index) => {
      row.dataset.href = "true";
      row.addEventListener("click", () => context.navigate(path(items[index])));
    });
  }

  window.FTFactors = {factorDetail, familyDetail, list, setDetail};
})();
