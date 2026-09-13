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
    // Keep the complete catalog surface visible to visitors.  The buttons
    // are useful affordance/context, but their handlers must stop before
    // navigation or any write request when no account session exists.
    const readOnly = source === "local" || !context.session;
    const showWriteActions = !context.session || source !== "local";
    const canWrite = source === "server" && Boolean(context.session);
    if (showWriteActions) {
      toolbar.append(
        FTUI.actionButton(context.t("新增分类"), () => {
          if (!canWrite) {
            rejectVisitorOrLocalWrite(context, source);
            return;
          }
          context.navigate(helpers.pathFor(
            "/products/categories/new?mode=create", source,
          ));
        }, {
          variant: "primary",
        }),
        FTUI.actionButton(context.t("新增乘积分类"), async () => {
          if (!canWrite) {
            rejectVisitorOrLocalWrite(context, source);
            return;
          }
          try {
            const value = await helpers.loadCategories(context, source);
            const selected = await window.FTProductCategoryOverlay.choose(
              context, value.categories || [],
            );
            if (!selected) return;
            const created = await context.api("/api/product-library/categories/composite", {
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
    let refresh;
    root.append(toolbar);
    const mount = document.createElement("div");
    mount.className = "product-category-management-results";
    root.append(mount);
    context.content.replaceChildren(root);
    let loadToken = 0;
    const isCurrentView = token => token === loadToken
      && helpers.isCurrent() !== false
      && root.isConnected !== false
      && mount.isConnected !== false;
    const loadIntoMount = async () => {
      const token = ++loadToken;
      mount.replaceChildren(FTUI.loading(context.t("正在读取产品分类…")));
      try {
        const results = await Promise.allSettled([
          helpers.loadCategories(context, source),
          helpers.loadSources?.(context, source) || Promise.resolve([]),
        ]);
        if (!isCurrentView(token)) return;
        if (results[0].status === "rejected") throw results[0].reason;
        const sourceDefinitions = results[1].status === "fulfilled"
          ? results[1].value : [];
        renderCategories(
          context, helpers, mount, results[0].value.categories || [], readOnly,
          source, sourceDefinitions,
        );
      } catch (error) {
        if (!isCurrentView(token)) return;
        mount.replaceChildren(FTUI.empty(
          context.t("产品分类读取失败"), error.message || "",
        ));
      }
    };
    refresh = FTUI.refreshButton(context, async () => {
      if (source !== "local" && context.session) {
        await context.api("/api/catalog/refresh", {method: "POST"});
      }
      await loadIntoMount();
    });
    toolbar.append(refresh);
    void loadIntoMount();
  }

  function rejectVisitorOrLocalWrite(context, source) {
    const message = !context.session
      ? context.t("访客模式只能查看产品分类")
      : source === "local"
        ? context.t("本地产品分类不可直接编辑")
        : context.t("产品分类不可编辑");
    if (typeof window.alert === "function") window.alert(message);
    else context.showNotice?.(message, true);
  }

  function renderCategories(
    context, helpers, mount, categories, readOnly, source, sourceDefinitions,
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
        sourceFamilyCell(context, helpers, category.source_ids, sourceDefinitions, source),
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

  function sourceFamilyCell(context, helpers, ids, definitions, source) {
    const cell = document.createElement("div");
    cell.className = "catalog-source-lines catalog-source-family-list";
    const byID = new Map((Array.isArray(definitions) ? definitions : []).map(item => [
      String(item.id || item.family_id || item.bundle_id || ""), item,
    ]));
    (Array.isArray(ids) ? ids : []).forEach(id => {
      const descriptor = byID.get(String(id));
      const link = document.createElement("a");
      link.className = "catalog-source-family-link";
      link.textContent = descriptor?.family_name || descriptor?.bundle_name
        || descriptor?.source_name || id;
      if (helpers.sourceFamilyPath) {
        link.href = helpers.sourceFamilyPath(
          descriptor?.family_id || descriptor?.bundle_id || descriptor?.id || id,
          source,
        );
        link.addEventListener("click", event => {
          event.preventDefault();
          event.stopPropagation();
          context.navigate(link.href);
        });
      }
      cell.append(link);
    });
    if (!cell.childElementCount) cell.textContent = "—";
    return cell;
  }

  function ownerSummary(context, category) {
    if (category.source_managed) return context.t("数据源");
    const owner = String(category.owner_ref || "")
      .replace(/^user:/, "").trim();
    return FTUI.userDisplay(category.owner_ref, category.owner_alias || FTUI.userLabel(owner) || context.t("当前用户"));
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
