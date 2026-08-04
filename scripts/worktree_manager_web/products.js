(() => {
  let cached = [];

  async function list(context) {
    context.activeNav("products"); context.setHeading("产品", "市场资料");
    context.content.replaceChildren(FTUI.loading("正在读取产品目录…"));
    const payload = await context.api(context.servicePath("/api/list_product_names"));
    cached = Array.isArray(payload.products) ? payload.products : [];
    const search = document.createElement("input");
    search.className = "toolbar-search"; search.placeholder = "搜索代码或中文名称";
    context.toolbar.append(search, context.button("↻", () => list(context), "刷新"));
    const render = () => renderList(context, search.value.trim().toLowerCase());
    search.addEventListener("input", render); render();
  }

  function renderList(context, query) {
    const rows = cached.filter(item => !query || [item.name, item.desc, item.code, item.exchange]
      .some(value => String(value || "").toLowerCase().includes(query)));
    if (!rows.length) {
      context.content.replaceChildren(FTUI.empty("没有匹配的产品", "请检查当前服务端口的数据目录"));
      return;
    }
    const view = FTUI.table(["产品", "中文名称", "交易所", "可用字段"], rows.map(item => [
      item.name, item.desc, item.exchange,
      Array.isArray(item.fields) ? item.fields.map(field => field.name || field).join("、") : "",
    ]));
    [...view.body.rows].forEach((row, index) => {
      row.dataset.href = "true";
      row.addEventListener("click", () => context.navigate(`/products/${encodeURIComponent(rows[index].name)}`));
    });
    context.content.replaceChildren(view.shell);
  }

  async function detail(context, productName) {
    context.activeNav("products");
    if (!cached.length) {
      const payload = await context.api(context.servicePath("/api/list_product_names"));
      cached = Array.isArray(payload.products) ? payload.products : [];
    }
    const product = cached.find(item => item.name === productName || item.code === productName);
    if (!product) throw new Error("产品不存在或当前端口无法解析该引用");
    context.setHeading(product.desc || product.name, product.name);
    context.content.replaceChildren(FTUI.loading("正在读取产品字段…"));
    context.toolbar.append(context.button("‹", () => context.navigate("/products"), "返回产品列表"));
    const payload = await context.api(context.servicePath(`/api/product_fields?name=${encodeURIComponent(product.name)}`));
    const fields = normalizeFields(payload.fields);
    const root = document.createElement("div"); root.className = "detail-stack";
    root.append(FTUI.table(["字段", "说明", "当前值"], fields.map(item => [
      item.name || item.key, item.description || item.desc, item.value,
    ])).shell);
    context.content.replaceChildren(root);
  }

  function normalizeFields(value) {
    if (Array.isArray(value)) return value.map(item => (
      item && typeof item === "object" ? item : {name: String(item), value: ""}
    ));
    if (value && typeof value === "object") return Object.entries(value).map(([name, item]) => (
      item && typeof item === "object" && !Array.isArray(item)
        ? {name, ...item}
        : {name, value: item}
    ));
    return [];
  }

  window.FTProducts = {detail, list};
})();
