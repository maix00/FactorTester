(() => {
  function productCount(source) {
    return Number(
      source?.catalog_product_count ?? source?.availability?.product_count ?? 0,
    );
  }

  function availableSourceIDs(definitions) {
    return (Array.isArray(definitions) ? definitions : [])
      .filter(source => productCount(source) > 0)
      .map(source => String(source.id || "").trim())
      .filter(Boolean);
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
    if (selected.length !== 2) throw new Error("请选择两个不同的 Category");
    const selectedDefinitions = selected.map(id =>
      available.find(item => item.id === id));
    if (selectedDefinitions.some(item => !item)) {
      throw new Error("所选 Category 已不存在");
    }
    const base = available.filter(item => item.composable && !item.is_composite);
    const baseByID = new Map(base.map(item => [item.id, item]));
    const requestedDimensions = selectedDefinitions.flatMap(item => (
      Array.isArray(item.dimensions) && item.dimensions.length
        ? item.dimensions : [item.id]
    ));
    if (requestedDimensions.some(id => !baseByID.has(id))) {
      throw new Error("所选 Category 不能参与乘积");
    }
    const requestedSet = new Set(requestedDimensions);
    const ids = base.map(item => item.id).filter(id => requestedSet.has(id));
    const existing = available.find(item => {
      const itemDimensions = Array.isArray(item.dimensions) && item.dimensions.length
        ? item.dimensions : [item.id];
      return itemDimensions.length === ids.length
        && itemDimensions.every(id => requestedSet.has(id));
    });
    if (existing) throw new Error("乘积没有增加新的 Category 维度");
    const labels = ids.map(id => {
      const item = baseByID.get(id);
      return item.title_zh || item.alias || item.id;
    });
    return {
      id: ids.join("_x_"),
      alias: labels.join("×"),
      title_zh: labels.join("×"),
      dimensions: ids,
      composable: false,
      is_composite: true,
    };
  }

  window.FTProductCategoryModel = Object.freeze({
    availableSourceIDs,
    multiply,
    treeNodeInitiallyOpen,
  });
})();
