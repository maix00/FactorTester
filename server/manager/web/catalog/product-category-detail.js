(() => {
  async function render(context, target, mode, helpers) {
    const source = helpers.sourceOf();
    context.activeNav("products");
    helpers.catalogSwitch(context, "categories", source);
    context.content.replaceChildren(FTUI.loading(context.t("正在读取产品分类…")));
    const [payload, sources] = await Promise.all([
      helpers.loadCategories(context, source),
      helpers.loadSources(context, source),
    ]);
    if (!helpers.isCurrent()) return;
    const category = (payload.categories || []).find(item => item.id === target);
    if (mode === "create") {
      if (source === "local") {
        throw new Error(context.t("本地产品分类不可直接编辑"));
      }
      if (!context.session) {
        throw new Error(context.t("访客模式只能查看产品分类"));
      }
      return window.FTProductCategoryCreate.render(context, helpers, {mode});
    }
    if (!category) throw new Error(context.t("产品分类不存在"));
    const title = category.title_zh || category.alias || category.id;
    context.setHeading(title, context.t("产品分类"));
    context.updateActiveTab?.({title});
    if (mode === "edit") {
      const isSuperAdmin = context.session?.role === "super_admin";
      if (source === "local" || !context.session
        || (category.source_managed && !isSuperAdmin)) {
        throw new Error(category.source_managed
          ? context.t("只有超级管理员可以编辑数据源产品分类")
          : context.t("产品分类不可编辑"));
      }
      if (category.is_composite) {
        return renderCompositeEdit(context, helpers, category, sources, source);
      }
      return window.FTProductCategoryCreate.render(
        context, helpers, {
          category, mode: "edit", sourceCategory: category.source_managed,
        },
      );
    }
    renderView(context, helpers, category, sources, source);
  }

  function renderView(context, helpers, category, sources, source) {
    const root = document.createElement("div");
    root.className = "detail-stack product-category-detail-page";
    const actions = document.createElement("div");
    actions.className = "product-category-detail-actions";
    const back = FTUI.actionButton(context.t("返回产品分类"), () => {
      context.navigate(helpers.pathFor("/products/categories", source));
    }, {variant: "secondary"});
    actions.append(back);
    const canEdit = source === "server" && context.session
      && (!category.source_managed
        || context.session.role === "super_admin");
    if (canEdit) {
      actions.append(FTUI.actionButton(context.t("编辑"), () => {
        context.navigate(helpers.pathFor(
          `/products/categories/${encodeURIComponent(category.id)}?mode=edit`, source,
        ));
      }, {variant: "primary"}));
      if (!category.source_managed) {
        actions.append(deleteButton(context, helpers, category, source));
      }
      if (category.is_composite) {
        actions.append(refreshButton(context, helpers, category, source, "view"));
      }
    }
    root.append(actions, helpers.sourceSummary(context, source));
    root.append(FTUI.table(
      [context.t("字段"), context.t("值")],
      [
        [context.t("分类名称"), category.title_zh || category.alias || category.id],
        [context.t("分类类型"), category.source_managed
          ? context.t("数据源分类")
          : category.is_composite ? context.t("乘积分类") : context.t("用户分类")],
        [context.t("分类维度"), (category.dimensions || []).join(" × ") || "—"],
        [context.t("所有者"), category.source_managed
          ? context.t("数据源") : category.owner_ref || context.t("当前用户")],
      ],
    ).shell);
    root.append(sourceSection(context, category, sources));
    if (category.parent_category_ids?.length) {
      root.append(FTUI.table(
        [context.t("绑定的父分类"), context.t("分类 ID")],
        category.parent_category_ids.map(id => [categoryLabel(category, id), id]),
      ).shell);
    }
    const treeState = {selectedPaths: [], sync: null};
    const paths = renderLabelPaths(context, category, treeState, false);
    root.append(paths);
    const resolved = resolvedSection(context, category, treeState);
    root.append(resolved.section);
    context.content.replaceChildren(root);
    void renderResolvedTree(
      context, helpers, category, sources, source, resolved.treeMount, treeState,
    );
  }

  function renderCompositeEdit(context, helpers, category, sources, source) {
    const root = document.createElement("section");
    root.className = "detail-stack product-category-detail-page product-category-composite-edit";
    const header = document.createElement("div");
    header.className = "product-category-editor-header";
    const back = FTUI.actionButton(context.t("返回产品分类"), () => {
      context.navigate(helpers.pathFor(
        `/products/categories/${encodeURIComponent(category.id)}`, source,
      ));
    }, {variant: "secondary"});
    const heading = document.createElement("h2");
    heading.textContent = context.t("编辑乘积分类");
    header.append(back, heading);
    header.append(refreshButton(context, helpers, category, source, "edit"));
    root.append(header, helpers.sourceSummary(context, source));
    root.append(FTUI.table(
      [context.t("字段"), context.t("值")],
      [
        [context.t("分类 ID"), category.id],
        [context.t("分类名称"), category.title_zh || category.alias || category.id],
        [context.t("分类类型"), context.t("乘积分类")],
      ],
    ).shell);
    root.append(sourceSection(context, category, sources));
    if (category.parent_category_ids?.length) {
      root.append(FTUI.table(
        [context.t("绑定的父分类"), context.t("分类 ID")],
        category.parent_category_ids.map(id => [categoryLabel(category, id), id]),
      ).shell);
    }
    const note = document.createElement("p");
    note.textContent = context.t(
      "乘积分类只能修改自动生成的 Label 标题，内部产品路径只读",
    );
    root.append(note);
    const treeState = {selectedPaths: [], sync: null};
    const form = document.createElement("form");
    form.className = "product-category-composite-edit-form";
    const layout = document.createElement("div");
    layout.className = "product-category-composite-edit-layout";
    const labels = renderLabelEditor(context, category, treeState);
    layout.append(labels);
    const resolved = resolvedSection(context, category, treeState);
    layout.append(resolved.section);
    form.append(layout);
    const status = document.createElement("small");
    status.className = "product-category-form-error";
    const actions = document.createElement("div");
    actions.className = "dialog-actions";
    const save = FTUI.actionButton(context.t("保存"), null, {variant: "primary"});
    save.type = "submit";
    actions.append(save);
    form.append(status, actions);
    root.append(form);
    form.addEventListener("submit", async event => {
      event.preventDefault();
      const items = [...labels.querySelectorAll("[data-category-item]")].map(row => ({
        label: row.querySelector("input")?.value || "",
        paths: JSON.parse(row.dataset.paths || "[]"),
        ...(row.dataset.generated === "true" ? {label_generated: true} : {}),
      }));
      save.disabled = true; status.textContent = "";
      try {
        await context.api(`/api/catalog/categories/${encodeURIComponent(category.id)}`, {
          method: "PUT",
          body: JSON.stringify({
            name: category.title_zh || category.alias || category.id,
            items,
          }),
        });
        context.navigate(helpers.pathFor(
          `/products/categories/${encodeURIComponent(category.id)}`, source,
        ));
      } catch (error) {
        status.textContent = error.message || context.t("产品分类保存失败");
        save.disabled = false;
      }
    });
    context.content.replaceChildren(root);
    void renderResolvedTree(
      context, helpers, category, sources, source, resolved.treeMount, treeState,
    );
  }

  function renderLabelPaths(context, category, treeState, editable) {
    const section = document.createElement("section");
    section.className = "product-category-path-definitions";
    section.append(Object.assign(document.createElement("h2"), {
      textContent: context.t("Label 与产品路径"),
    }));
    const items = Array.isArray(category.items) ? category.items : [];
    if (!items.length) {
      section.append(FTUI.empty(
        context.t("暂无显式产品路径"),
        context.t("该分类由绑定的数据源目录或父分类解析"),
      ));
      return section;
    }
    const table = FTUI.table(
      [context.t("Label ID"), context.t("Label"), context.t("正路径"), context.t("负路径")],
      items.map(item => {
        const values = Array.isArray(item.paths) ? item.paths : [];
        return [item.label_id || "—", item.label || "—",
          multiline(values.filter(path => !String(path).startsWith("-"))),
          multiline(values.filter(path => String(path).startsWith("-")))];
      }),
    );
    [...table.body.rows].forEach((row, index) => {
      row.classList.add("product-category-label-row");
      row.tabIndex = 0;
      const activate = () => {
        treeState.selectedPaths = qualifiedPaths(category, items[index]);
        [...table.body.rows].forEach(item => item.classList.remove("active"));
        row.classList.add("active");
        treeState.sync?.();
      };
      row.addEventListener("click", activate);
      row.addEventListener("keydown", event => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault(); activate();
        }
      });
      if (index === 0) activate();
    });
    section.append(table.shell);
    return section;
  }

  function renderLabelEditor(context, category, treeState) {
    const section = document.createElement("section");
    section.className = "product-category-path-definitions product-category-label-editor";
    section.append(Object.assign(document.createElement("h2"), {
      textContent: context.t("Label 标题"),
    }));
    (category.items || []).forEach((item, index) => {
      const row = document.createElement("div");
      row.className = "product-category-composite-label-row";
      row.dataset.categoryItem = "true";
      row.dataset.paths = JSON.stringify(item.paths || []);
      const generated = item.label_generated === true || item.label === "Others";
      if (generated) {
        row.dataset.generated = "true";
        row.classList.add("product-category-generated-item");
      }
      const id = document.createElement("code");
      id.textContent = item.label_id || `${category.id}_${index + 1}`;
      const input = document.createElement("input");
      input.required = true; input.value = item.label || "";
      input.setAttribute("aria-label", context.t("Label 标题"));
      if (generated) {
        input.readOnly = true;
        input.title = context.t("Others 标签由系统自动生成，不能修改");
      }
      const path = document.createElement("div");
      path.className = "product-category-readonly-paths";
      path.append(
        multiline((item.paths || []).filter(value => !String(value).startsWith("-"))),
        multiline((item.paths || []).filter(value => String(value).startsWith("-"))),
      );
      const activate = () => {
        treeState.selectedPaths = qualifiedPaths(category, item);
        section.querySelectorAll(".active").forEach(value => value.classList.remove("active"));
        row.classList.add("active"); treeState.sync?.();
      };
      row.addEventListener("click", activate);
      input.addEventListener("focus", activate);
      row.append(id, input, path); section.append(row);
      if (index === 0) activate();
    });
    return section;
  }

  function resolvedSection(context, category, treeState) {
    const section = document.createElement("section");
    section.className = "product-category-resolved-products";
    section.append(Object.assign(document.createElement("h2"), {
      textContent: context.t("解析后的产品列表"),
    }));
    const treeMount = document.createElement("div");
    treeMount.className = "product-category-detail-tree";
    treeMount.append(FTUI.loading(context.t("正在读取分类产品…")));
    section.append(treeMount);
    return {section, treeMount};
  }

  function sourceSection(context, category, sources) {
    const section = document.createElement("section");
    section.className = "product-category-source-section";
    section.append(Object.assign(document.createElement("h2"), {
      textContent: context.t("绑定的数据源"),
    }));
    const ids = Array.isArray(category.source_ids) ? category.source_ids : [];
    const rows = ids.map(id => {
      const source = sources.find(item => String(item.id || "") === String(id));
      return [id, source?.title_zh || source?.name || source?.alias || "—",
        providerServers(source, context), source?.status || context.t("已登记")];
    });
    section.append(rows.length
      ? FTUI.table([context.t("数据源"), context.t("名称"), context.t("提供服务器"), context.t("状态")], rows).shell
      : FTUI.empty(context.t("暂无绑定数据源"), context.t("该分类没有声明数据源绑定")));
    return section;
  }

  async function renderResolvedTree(
    context, helpers, category, sources, source, mount, treeState,
  ) {
    try {
      const sourceIDs = category.source_ids?.length
        ? category.source_ids
        : helpers.loadSourceIDs?.(sources) || [];
      const value = await helpers.loadTree(context, source, [category.id], sourceIDs);
      if (!helpers.isCurrent()) return;
      const contractTreePath = (path, params = {}) => {
        const query = new URLSearchParams({path});
        query.append("category", category.id);
        sourceIDs.forEach(id => query.append("data_source", id));
        if (params.query) query.set("query", params.query);
        if (params.page) query.set("page", String(params.page));
        if (params.limit) query.set("limit", String(params.limit));
        return source === "local"
          ? `/api/client/contract_tree?${query}`
          : `/api/catalog/contract-tree?${query}`;
      };
      const treeOptions = {
        categoryDefinitions: [category],
        showCategoryFilter: false,
        selectable: true,
        selectionReadOnly: true,
        leafOnly: true,
        selectedPaths: treeState?.selectedPaths || [],
        source,
        contractTreePath,
      };
      await FTProductTree.render(context, mount, value, treeOptions);
      if (treeState) treeState.sync = () => {
        treeOptions.selectedPaths = treeState.selectedPaths;
        FTProductTree.syncSelectionControls(mount, treeState.selectedPaths);
      };
      treeState?.sync?.();
    } catch (error) {
      mount.replaceChildren(FTUI.empty(
        context.t("产品解析失败"), error.message || context.t("请稍后重试"),
      ));
    }
  }

  function deleteButton(context, helpers, category, source) {
    return FTUI.actionButton(context.t("删除"), async () => {
      if (!window.confirm(context.t("确认删除该产品分类？"))) return;
      try {
        await context.api(`/api/catalog/categories/${encodeURIComponent(category.id)}`, {
          method: "DELETE",
        });
        context.closeTab?.(context.tabID);
        context.navigate(helpers.pathFor("/products/categories", source));
      } catch (error) {
        context.showNotice?.(error.message || context.t("产品分类删除失败"), true);
      }
    }, {variant: "secondary"});
  }

  function refreshButton(context, helpers, category, source, mode) {
    return FTUI.actionButton(context.t("从父分类更新内容"), async () => {
      try {
        await context.api(
          `/api/catalog/categories/${encodeURIComponent(category.id)}/refresh`,
          {method: "POST"},
        );
        const query = mode === "edit" ? "?mode=edit" : "";
        context.navigate(helpers.pathFor(
          `/products/categories/${encodeURIComponent(category.id)}${query}`
            + `${query ? "&" : "?"}updated=${Date.now()}`,
          source,
        ));
      } catch (error) {
        context.showNotice?.(error.message || context.t("产品分类更新失败"), true);
      }
    }, {variant: "secondary"});
  }

  function multiline(values) {
    const mount = document.createElement("div");
    mount.className = "catalog-source-lines";
    (values || []).forEach(value => mount.append(Object.assign(
      document.createElement("div"), {textContent: value},
    )));
    return mount;
  }

  function qualifiedPaths(category, item) {
    const prefix = `ProductCategory/${category.id}/`;
    return (item?.paths || [])
      .filter(path => !String(path).trim().startsWith("-"))
      .map(path => {
        const value = String(path || "").trim().replace(/^\/+/, "");
        return value.startsWith("ProductCategory/") ? value : `${prefix}${value}`;
      });
  }

  function categoryLabel(category, id) {
    return (category.parent_category_labels || {})[id] || id;
  }

  function providerServers(source, context) {
    const values = source?.servers || source?.server_ids
      || source?.provider_servers || source?.provided_by || [];
    if (Array.isArray(values)) return values.join("、") || "—";
    if (values && typeof values === "object") return Object.keys(values).join("、") || "—";
    return String(values || context.t("当前服务器")).trim();
  }

  window.FTProductCategoryDetails = Object.freeze({render});
})();
