(() => {
  function productCount(source) {
    return Number(
      source?.catalog_product_count ?? source?.availability?.product_count ?? 0,
    );
  }

  function availableSourceIDs(definitions) {
    return (Array.isArray(definitions) ? definitions : [])
      .filter(source => productCount(source) > 0
        && source?.visitor_data_accessible !== false)
      .map(source => String(source.id || "").trim())
      .filter(Boolean);
  }

  function sourceIDsForPaths(paths, definitions) {
    const requested = [...new Set(
      (Array.isArray(paths) ? paths : [])
        .map(normalizePath)
        .filter(Boolean),
    )];
    const sources = Array.isArray(definitions) ? definitions : [];
    return sources
      .filter(source => {
        const declared = (Array.isArray(source?.product_paths)
          ? source.product_paths : [])
          .map(normalizePath).filter(Boolean);
        return declared.some(declaredPath => requested.some(requestedPath => (
          pathsOverlap(requestedPath, declaredPath)
        )));
      })
      .map(source => String(source?.id || source?.source_id || "").trim())
      .filter(Boolean);
  }

  function normalizePath(value) {
    const parts = String(value || "").trim().replace(/^-/, "")
      .replace(/^\/+|\/+$/g, "").split("/");
    if (parts[0] === "ProductCategory" && parts.length >= 3) {
      return parts.slice(2).join("/");
    }
    return parts.filter(Boolean).join("/");
  }

  function pathsOverlap(requested, declared) {
    // A source declaration provides its own node and descendants.  A generic
    // hard-coded parent such as Product/Futures must not bind to a child
    // source declaration such as Product/Futures/CNFutures.
    return requested === declared || requested.startsWith(`${declared}/`);
  }

  function treeNodeInitiallyOpen(node, depth) {
    const productList = String(node?.key || "").endsWith("/_products");
    return depth === 0 && !productList;
  }

  function multiply(definitions, requestedIDs) {
    const available = (Array.isArray(definitions) ? definitions : [])
      .filter(item => item && String(item.id || "").trim());
    const selected = [...new Set(
      (Array.isArray(requestedIDs) ? requestedIDs : [])
        .map(value => String(value || "").trim()).filter(Boolean),
    )];
    if (selected.length !== 2) throw new Error("请选择两个不同的分类");
    const selectedDefinitions = selected.map(id =>
      available.find(item => item.id === id));
    if (selectedDefinitions.some(item => !item)) {
      throw new Error("所选分类已不存在");
    }
    const base = available.filter(item => item.composable && !item.is_composite);
    const baseByID = new Map(base.map(item => [item.id, item]));
    const requestedDimensions = selectedDefinitions.flatMap(item => (
      Array.isArray(item.dimensions) && item.dimensions.length
        ? item.dimensions : [item.id]
    ));
    if (requestedDimensions.some(id => !baseByID.has(id))) {
      throw new Error("所选分类不能参与乘积");
    }
    const requestedSet = new Set(requestedDimensions);
    const ids = base.map(item => item.id).filter(id => requestedSet.has(id));
    const existing = available.find(item => {
      const itemDimensions = Array.isArray(item.dimensions) && item.dimensions.length
        ? item.dimensions : [item.id];
      return itemDimensions.length === ids.length
        && itemDimensions.every(id => requestedSet.has(id));
    });
    if (existing) throw new Error("乘积没有增加新的分类维度");
    const labels = ids.map(id => {
      const item = baseByID.get(id);
      return item.title_zh || item.alias || item.id;
    });
    // The browser may validate the requested dimensions, but it must never
    // mint a persistent category ID.  The Manager assigns the user-prefixed
    // ID when the request is saved.
    return {
      alias: labels.join("×"),
      title_zh: labels.join("×"),
      dimensions: ids,
      parent_category_ids: selected,
      composable: false,
      is_composite: true,
    };
  }

  window.FTProductCategoryModel = Object.freeze({
    availableSourceIDs,
    sourceIDsForPaths,
    multiply,
    treeNodeInitiallyOpen,
  });
})();
