(() => {
  function list(context, helpers) {
    const source = helpers.sourceOf();
    context.activeNav("products");
    context.setHeading(context.t("产品分类"),
      source === "local" ? context.t("本地产品目录") : context.t("服务器产品目录"));
    helpers.catalogSwitch(context, "categories", source);
    const root = document.createElement("div");
    root.className = "library-page product-category-management-page";
    root.append(helpers.sourceSummary(context, source));
    const toolbar = document.createElement("div");
    toolbar.className = "product-category-management-actions";
    // A visitor has no account session. The server also rejects catalog
    // writes for visitors, so do not expose create controls to them.
    const readOnly = source === "local" || !context.session;
    if (!readOnly) {
      toolbar.append(
        FTUI.actionButton(context.t("新增分类"), () => {
          context.navigate(helpers.pathFor(
            "/products/categories/new?mode=create", source,
          ));
        }, {
          variant: "primary",
        }),
        FTUI.actionButton(context.t("新增乘积分类"), async () => {
          try {
            const value = await helpers.loadCategories(context, source);
            const selected = await window.FTProductCategoryOverlay.choose(
              context, value.categories || [],
            );
            if (!selected) return;
            const created = await context.api("/api/catalog/categories/composite", {
              method: "POST",
              body: JSON.stringify({category_ids: selected}),
            });
            const id = created.category?.id;
            if (id) context.navigate(helpers.pathFor(
              `/products/categories/${encodeURIComponent(id)}`, source,
            ));
          } catch (error) {
            context.showNotice?.(
              error.message || context.t("产品分类保存失败"), true,
            );
          }
        }, {variant: "secondary"}),
      );
    }
    toolbar.append(context.button("↻", () => list(context, helpers), context.t("刷新")));
    root.append(toolbar);
    const mount = document.createElement("div");
    mount.className = "product-category-management-results";
    mount.append(FTUI.loading(context.t("正在读取产品分类…")));
    root.append(mount);
    context.content.replaceChildren(root);
    helpers.loadCategories(context, source).then(value => {
      if (!helpers.isCurrent()) return;
      renderCategories(
        context, helpers, mount, value.categories || [], readOnly, source,
      );
    }).catch(error => {
      if (!helpers.isCurrent()) return;
      mount.replaceChildren(FTUI.empty(
        context.t("产品分类读取失败"), error.message || "",
      ));
    });
  }

  function renderCategories(
    context, helpers, mount, categories, readOnly, source,
  ) {
    if (!categories.length) {
      mount.replaceChildren(FTUI.empty(
        context.t("尚无产品分类"), context.t("请先新增一个产品分类"),
      ));
      return;
    }
    const byID = new Map(categories.map(category => [category.id, category]));
    const table = FTUI.table(
      [context.t("名称"), context.t("分类 ID"), context.t("类型"),
        context.t("来源/所有者"), context.t("Label 数"), context.t("父分类"),
        context.t("数据源")],
      categories.map(category => [
        category.title_zh || category.alias || category.id,
        category.id || "—",
        category.source_managed
          ? context.t("数据源分类")
          : category.is_composite ? context.t("乘积分类") : context.t("用户分类"),
        ownerSummary(context, category),
        Array.isArray(category.items) ? category.items.length : 0,
        parentSummary(context, category, byID),
        (category.source_ids || []).join("、") || "—",
      ]),
    );
    [...table.body.rows].forEach((row, index) => {
      const category = categories[index];
      row.dataset.href = "true";
      row.addEventListener("click", () => context.navigate(helpers.pathFor(
        `/products/categories/${encodeURIComponent(category.id)}`, source,
      )));
    });
    mount.replaceChildren(table.shell);
  }

  function ownerSummary(context, category) {
    if (category.source_managed) return context.t("数据源");
    const owner = String(category.owner_ref || "")
      .replace(/^user:/, "").trim();
    return owner || context.t("当前用户");
  }

  function parentSummary(context, category, byID) {
    const parents = Array.isArray(category.parent_category_ids)
      ? category.parent_category_ids : [];
    if (!parents.length) return "—";
    return parents.map(id => {
      const parent = byID.get(id);
      const title = parent?.title_zh || parent?.alias;
      return title ? `${title} (${id})` : id;
    }).join(" × ");
  }

  window.FTProductCategories = Object.freeze({list});
})();
