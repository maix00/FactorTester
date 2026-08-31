(() => {
  function current(context, options = {}) {
    return options.isCurrent ? options.isCurrent() !== false
      : context.isCurrent?.() !== false;
  }

  function sourceIDs(definitions, helpers) {
    return helpers.loadSourceIDs
      ? helpers.loadSourceIDs(definitions)
      : FTProductCategoryModel.availableSourceIDs(definitions);
  }

  function endpoint(source) {
    return source === "local"
      ? "/api/client/contract_tree" : "/api/product-library/contract-tree";
  }

  function treePath(source, sourceIDs, categoryIDs, path, params = {}) {
    const query = new URLSearchParams({path});
    (categoryIDs || []).forEach(value => query.append("category", value));
    (sourceIDs || []).forEach(value => query.append("data_source", value));
    if (params.query) query.set("query", params.query);
    if (params.page) query.set("page", String(params.page));
    if (params.limit) query.set("limit", String(params.limit));
    return `${endpoint(source)}?${query}`;
  }

  async function render(context, mount, helpers, options = {}) {
    const source = options.source || "server";
    const categoryIDs = Array.isArray(options.categoryIDs)
      ? options.categoryIDs : [];
    const definitions = Array.isArray(options.sourceDefinitions)
      ? options.sourceDefinitions
      : await helpers.loadSources(context, source);
    const selectedPaths = Array.isArray(options.selectedPaths)
      ? options.selectedPaths : [];
    const ids = Array.isArray(options.sourceIDs)
      ? options.sourceIDs : sourceIDs(definitions, helpers);
    await FTProductTree.render(context, mount, null, {
      categoryDefinitions: [],
      dataSourceDefinitions: definitions,
      showCategoryFilter: false,
      selectable: options.selectable !== false,
      selectionReadOnly: options.editable !== true,
      leafOnly: options.leafOnly !== false,
      selectedPaths,
      source,
      sourceFamilyPath: helpers.sourceFamilyPath,
      contractTreePath: (path, params) => treePath(
        source, ids, categoryIDs, path, params,
      ),
      isCurrent: () => current(context, options),
      loadTree: () => helpers.loadTree(
        context, source, categoryIDs, ids,
      ),
      onTreeLoaded: options.onTreeLoaded,
      onSelectionChange: options.onSelectionChange,
    });
    return {
      sourceIDs: ids,
      dispose: () => {
        window.FTCatalogDetailUI?.clearMount(mount);
      },
    };
  }

  window.FTCatalogSelectionTree = Object.freeze({render});
})();
