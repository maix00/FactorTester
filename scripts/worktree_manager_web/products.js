(() => {
  let products = [];
  let groups = [];

  async function load(context) {
    if (products.length || groups.length) return;
    const [productPayload, groupPayload] = await Promise.all([
      context.api(context.servicePath("/api/list_product_names")),
      context.api(context.servicePath("/api/product-groups")),
    ]);
    products = Array.isArray(productPayload.products) ? productPayload.products : [];
    groups = Array.isArray(groupPayload.groups) ? groupPayload.groups : [];
  }

  async function list(context, page = "products") {
    context.activeNav("products");
    context.setHeading(context.t("产品库"), context.t("市场资料"));
    context.content.replaceChildren(FTUI.loading(context.t("正在读取产品目录…")));
    await load(context);
    const root = document.createElement("div");
    root.className = "library-page";
    root.append(pageTabs(context, page));
    const results = document.createElement("div");
    results.className = "library-results";
    root.append(results);
    context.content.replaceChildren(root);
    const search = document.createElement("input");
    search.className = "toolbar-search";
    search.placeholder = page === "groups"
      ? context.t("搜索产品组")
      : context.t("搜索产品或代码");
    context.toolbar.append(search, context.button("↻", refresh, context.t("刷新")));
    search.addEventListener("input", render);
    render();

    function refresh() {
      products = [];
      groups = [];
      list(context, page);
    }
    function render() {
      const query = search.value.trim().toLowerCase();
      if (!query) {
        results.replaceChildren(FTUI.empty(
          context.t("输入关键词开始检索"),
          page === "groups"
            ? context.t("可按名称、成员或说明检索产品组")
            : context.t("可按产品名称、代码或交易所检索"),
        ));
        return;
      }
      const items = (page === "groups"
        ? groups.map(value => ({kind: "group", value}))
        : products.map(value => ({kind: "product", value})))
        .filter(item => matches(item.value, query));
      if (!items.length) {
        results.replaceChildren(FTUI.empty(
          context.t("没有匹配的产品"), context.t("请检查当前服务端口的数据目录")
        ));
        return;
      }
      const view = FTUI.table(
        [context.t("类型"), context.t("名称"), context.t("代码或成员数"), context.t("交易所")],
        items.map(item => item.kind === "group"
          ? [context.t("产品组"), item.value.name, pathCount(item.value), ""]
          : [context.t("产品"), item.value.desc || item.value.name, item.value.name || item.value.code, item.value.exchange])
      );
      [...view.body.rows].forEach((row, index) => {
        row.dataset.href = "true";
        row.addEventListener("click", () => {
          const item = items[index];
          const value = item.kind === "group" ? item.value.name : item.value.name;
          context.navigate(`/products/${item.kind}/${encodeURIComponent(value)}`);
        });
      });
      results.replaceChildren(view.shell);
    }
  }

  function pageTabs(context, active) {
    const tabs = document.createElement("div");
    tabs.className = "library-tabs";
    for (const [id, label, path] of [
      ["products", context.t("产品"), "/products"],
      ["groups", context.t("产品组"), "/products/groups"],
    ]) {
      const button = document.createElement("button");
      button.className = `library-tab${id === active ? " active" : ""}`;
      button.textContent = label;
      button.addEventListener("click", () => context.navigate(path));
      tabs.append(button);
    }
    return tabs;
  }

  async function productDetail(context, target) {
    context.activeNav("products");
    await load(context);
    const product = products.find(item => item.name === target || item.code === target);
    if (!product) return referenceDetail(context, "product", target);
    context.setHeading(product.desc || product.name, product.name);
    context.content.replaceChildren(FTUI.loading(context.t("正在读取产品字段…")));
    const payload = await context.api(
      context.servicePath(`/api/product_fields?name=${encodeURIComponent(product.name)}`)
    );
    const fields = normalizeFields(payload.fields);
    const root = document.createElement("div");
    root.className = "detail-stack";
    root.append(FTUI.table(
      [context.t("字段"), context.t("说明"), context.t("当前值")],
      fields.map(item => [item.name || item.key, item.description || item.desc, item.value])
    ).shell);
    context.content.replaceChildren(root);
  }

  async function groupDetail(context, target) {
    context.activeNav("products");
    await load(context);
    const stableID = target.startsWith("product-group:")
      ? target.slice("product-group:".length)
      : "";
    const selected = groups.find(item =>
      item.name === target || (stableID && item.id === stableID)
    );
    if (!selected) throw new Error(context.t("产品组不存在或当前端口无法解析该引用"));
    const name = selected.name;
    const payload = await context.api(
      context.servicePath(`/api/product-groups/${encodeURIComponent(name)}`)
    );
    const group = payload.group || {};
    context.setHeading(group.name || name, context.t("产品组"));
    const root = document.createElement("div");
    root.className = "detail-stack";
    root.append(FTUI.table([context.t("字段"), context.t("值")], FTUI.fieldRows(group)).shell);
    const paths = Array.isArray(group.paths) ? group.paths : [];
    root.append(FTUI.table(
      [context.t("产品路径"), context.t("说明")],
      paths.map(item => typeof item === "string"
        ? [item, ""]
        : [item.path || item.id || item.name, item.label || item.description])
    ).shell);
    const subjects = [
      ...(Array.isArray(group.factor_refs) ? group.factor_refs : [])
        .map(ref => ({type: context.t("因子"), ref, path: "/factors/factor/"})),
      ...(Array.isArray(group.factor_set_refs) ? group.factor_set_refs : [])
        .map(ref => ({type: context.t("因子集合"), ref, path: "/factors/set/"})),
    ];
    if (subjects.length) {
      const view = FTUI.table(
        [context.t("类型"), context.t("关联因子")],
        subjects.map(item => [item.type, item.ref]),
      );
      [...view.body.rows].forEach((row, index) => {
        row.dataset.href = "true";
        row.addEventListener("click", () => context.navigate(
          `${subjects[index].path}${encodeURIComponent(subjects[index].ref)}`
        ));
      });
      root.append(view.shell);
    }
    context.content.replaceChildren(root);
  }

  async function referenceDetail(context, kind, targetRef) {
    context.activeNav("products");
    context.content.replaceChildren(FTUI.loading(context.t("正在解析产品引用…")));
    const payload = await context.api(context.servicePath(
      `/api/report-references/validate?kind=${encodeURIComponent(kind)}&target_ref=${encodeURIComponent(targetRef)}`
    ));
    const reference = payload.reference || payload.data?.reference || {};
    context.setHeading(reference.label || context.t("产品详情"), context.t("产品库"));
    const root = document.createElement("div");
    root.className = "detail-stack";
    root.append(FTUI.table(
      [context.t("字段"), context.t("值")],
      [...FTUI.fieldRows(reference), ...FTUI.fieldRows(reference.object || {})]
    ).shell);
    context.content.replaceChildren(root);
  }

  function normalizeFields(value) {
    if (Array.isArray(value)) return value.map(item =>
      item && typeof item === "object" ? item : {name: String(item), value: ""}
    );
    if (value && typeof value === "object") return Object.entries(value).map(([name, item]) =>
      item && typeof item === "object" && !Array.isArray(item)
        ? {name, ...item}
        : {name, value: item}
    );
    return [];
  }
  function pathCount(group) { return Array.isArray(group.paths) ? group.paths.length : 0; }
  function matches(value, query) {
    if (!query) return true;
    return JSON.stringify(value || {}).toLowerCase().includes(query);
  }

  window.FTProducts = {groupDetail, list, productDetail, referenceDetail};
})();
