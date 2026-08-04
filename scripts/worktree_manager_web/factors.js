(() => {
  let cached = [];

  async function list(context) {
    context.activeNav("factors"); context.setHeading("因子库", "FactorTester");
    context.content.replaceChildren(FTUI.loading("正在读取因子库…"));
    const payload = await context.api(context.servicePath("/custom-factors/api/client/factor-library"));
    cached = Array.isArray(payload.factors) ? payload.factors : [];
    const search = document.createElement("input");
    search.className = "toolbar-search"; search.placeholder = "搜索因子或因子家族";
    context.toolbar.append(search, context.button("↻", () => list(context), "刷新"));
    const render = () => renderList(context, search.value.trim().toLowerCase());
    search.addEventListener("input", render); render();
  }

  function renderList(context, query) {
    const rows = cached.filter(item => !query || [
      item.factor_alias, item.factor_family_alias, item.factor_family_name,
      item.category, item.owner_alias, item.owner_username,
    ].some(value => String(value || "").toLowerCase().includes(query)));
    if (!rows.length) {
      context.content.replaceChildren(FTUI.empty("没有匹配的因子", "因子库由当前服务端口返回"));
      return;
    }
    const view = FTUI.table(["因子", "因子家族", "产品组", "类别", "所有者"], rows.map(item => [
      item.factor_alias, item.factor_family_alias || item.factor_family_name,
      item.product_group || item.scope_key, item.category,
      item.owner_alias || item.owner_username,
    ]));
    [...view.body.rows].forEach((row, index) => {
      row.dataset.href = "true";
      row.addEventListener("click", () => context.navigate(
        `/factors/${encodeURIComponent(factorIdentity(rows[index]))}`
      ));
    });
    context.content.replaceChildren(view.shell);
  }

  async function detail(context, identity) {
    context.activeNav("factors");
    if (!cached.length) {
      const payload = await context.api(context.servicePath("/custom-factors/api/client/factor-library"));
      cached = Array.isArray(payload.factors) ? payload.factors : [];
    }
    const factor = cached.find(item => factorIdentity(item) === identity || item.factor_alias === identity);
    if (!factor) throw new Error("因子不存在或当前端口无法解析该引用");
    context.setHeading(factor.factor_alias || "因子详情", factor.factor_family_alias || "因子库");
    const root = document.createElement("div"); root.className = "detail-stack";
    const fields = FTUI.table(["字段", "值"], FTUI.fieldRows(factor));
    root.append(fields.shell);
    const complex = Object.fromEntries(Object.entries(factor).filter(([, value]) => value && typeof value === "object"));
    if (Object.keys(complex).length) root.append(FTUI.code(complex));
    context.content.replaceChildren(root);
    context.toolbar.append(context.button("‹", () => context.navigate("/factors"), "返回因子列表"));
  }

  function factorIdentity(item) {
    return item.factor_ref || item.ref || item.factor_alias || item.factor_family_alias || "";
  }

  window.FTFactors = {detail, list};
})();
