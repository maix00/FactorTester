(() => {
  async function render(context, target, mode, helpers) {
    context.content.__ftProductCategoryCleanup?.();
    delete context.content.__ftProductCategoryCleanup;
    const source = helpers.sourceOf();
    context.activeNav("products");
    helpers.catalogSwitch(context, "categories", source);
    context.content.replaceChildren(FTUI.loading(context.t("正在读取产品分类…")));
    if (mode === "create") {
      if (source === "local") {
        throw new Error(context.t("本地产品分类不可直接编辑"));
      }
      if (!context.session) {
        throw new Error(context.t("访客模式只能查看产品分类"));
      }
      context.setHeading(context.t("新增分类"), context.t("产品分类"));
      context.updateActiveTab?.({title: context.t("新增分类")});
      if (!helpers.isCurrent(context)) return;
      const sourcesPromise = helpers.loadSources(context, source);
      return renderPage(context, helpers, {
        category: null, mode: "create", source, sources: null,
        sourcesPromise, canEdit: true,
      });
    }

    const payload = await helpers.loadCategories(context, source);
    if (!helpers.isCurrent(context)) return;
    const sourcesPromise = helpers.loadSources(context, source);
    const category = (payload.categories || []).find(item => item.id === target);
    if (!category) throw new Error(context.t("产品分类不存在"));
    const title = category.title_zh || category.alias || category.id;
    context.setHeading(title, context.t("产品分类"));
    context.updateActiveTab?.({title});
    const canEdit = source === "server" && Boolean(context.session)
      && (!category.source_managed || context.session.role === "super_admin");
    if (mode === "edit" && !canEdit) {
      throw new Error(category.source_managed
        ? context.t("只有超级管理员可以编辑数据源产品分类")
        : context.t("产品分类不可编辑"));
    }
    return renderPage(context, helpers, {
      category, mode, source, sources: null, sourcesPromise, canEdit,
    });
  }

  function renderPage(context, helpers, options) {
    const {category, mode, source, sources, sourcesPromise, canEdit} = options;
    return window.FTProductCategoryDetailLayout.render(context, helpers, {
      category, mode, source, sources, canEdit,
      loadSources: sourcesPromise ? () => sourcesPromise : null,
      sourceSummary: () => helpers.sourceSummary(context, source),
      deleteButton: category && canEdit && !category.source_managed
        ? () => deleteButton(context, helpers, category, source) : null,
      refreshButton: category?.is_composite && canEdit
        ? refreshMode => refreshButton(context, helpers, category, source, refreshMode)
        : null,
      onSave: payload => saveCategory(context, helpers, category, source, payload),
      renderTree: treeOptions => renderResolvedTree(
        context, helpers, category, sources, source, sourcesPromise, treeOptions,
      ),
    });
  }

  async function saveCategory(context, helpers, category, source, payload) {
    const endpoint = category
      ? `/api/catalog/categories/${encodeURIComponent(category.id)}`
      : "/api/catalog/categories";
    const value = await context.api(endpoint, {
      method: category ? "PUT" : "POST",
      body: JSON.stringify(payload),
    });
    const saved = value.category || category || {};
    if (category) {
      context.navigate(helpers.pathFor(
        `/products/categories/${encodeURIComponent(saved.id)}`, source,
      ));
      return;
    }
    context.closeTab?.(context.tabID);
    context.navigate(helpers.pathFor(
      `/products/categories?updated=${Date.now()}`, source,
    ));
  }

  async function renderResolvedTree(
    context, helpers, category, sources, source, sourcesPromise, options,
  ) {
    const {mount, treeState, editable} = options;
    if (!mount) return;
    try {
      // Mount the ordinary source tree immediately.  The category is a
      // selection definition, never a product-tree provider.  Waiting here
      // for source metadata or the whole tree left the Label row's own
      // placeholder visible indefinitely on a slow/embedded data bridge.
      const sourceDefinitions = Array.isArray(sources) ? sources : [];
      const selectedSourceIDs = [];
      const contractTreePath = (path, params = {}) => {
        const query = new URLSearchParams({path});
        if (params.query) query.set("query", params.query);
        if (params.page) query.set("page", String(params.page));
        if (params.limit) query.set("limit", String(params.limit));
        return source === "local"
          ? `/api/client/contract_tree?${query}`
          : `/api/catalog/contract-tree?${query}`;
      };
      const treeOptions = {
        categoryDefinitions: [],
        dataSourceDefinitions: sourceDefinitions,
        showCategoryFilter: false,
        selectable: true,
        selectionReadOnly: !editable,
        leafOnly: true,
        selectedPaths: treeState.selectedPaths || [],
        source,
        contractTreePath,
        isCurrent: () => helpers.isCurrent(context),
        // An empty source filter means the ordinary tree exposed by this
        // Manager, including all currently available local data sources.
        loadTree: () => helpers.loadTree(
          context, source, [], selectedSourceIDs,
        ),
        onTreeLoaded: () => treeState.sync?.(),
        onSelectionChange: selected => {
          treeState.selectedPaths = selected;
          treeState.onTreeSelection?.(selected);
        },
      };
      const definitionsPromise = Array.isArray(sources)
        ? Promise.resolve(sources)
        : (sourcesPromise || helpers.loadSources(context, source));
      void definitionsPromise.then(value => {
        treeOptions.dataSourceDefinitions = Array.isArray(value) ? value : [];
      }).catch(() => {});
      await FTProductTree.render(context, mount, null, treeOptions);
      if (!helpers.isCurrent(context)) return;
      treeState.sync = () => {
        treeOptions.selectedPaths = treeState.selectedPaths;
        FTProductTree.syncSelectionControls(mount, treeState.selectedPaths);
      };
      treeState.sync();
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
        context.navigate(helpers.pathFor(
          `/products/categories?updated=${Date.now()}`, source,
        ));
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

  window.FTProductCategoryDetails = Object.freeze({render});
})();
