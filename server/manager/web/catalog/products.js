(() => {
  const cache = new Map();
  const treeCache = new Map();

  function isCurrent(context) {
    return context.isRouteCurrent?.() !== false;
  }

  function sourceOf() {
    return localCatalogAvailable()
      && new URLSearchParams(location.search).get("source") === "local"
      ? "local" : "server";
  }

  function localCatalogAvailable() {
    return window.FTAppRuntime?.hasLocalCatalog?.() === true;
  }

  function pathFor(path, source = sourceOf()) {
    const [pathname, rawQuery = ""] = String(path).split("?", 2);
    const query = new URLSearchParams(rawQuery);
    query.delete("source");
    query.delete("data_source");
    if (source === "local") query.set("source", "local");
    const encoded = query.toString();
    return encoded ? `${pathname}?${encoded}` : pathname;
  }

  function embeddedOf() {
    // Internal tab navigation keeps the embedded shell class but may replace
    // the query string, so do not rely on `presentation=embedded` surviving
    // every history.pushState call.
    return document.documentElement.classList.contains("embedded-presentation")
      || new URLSearchParams(location.search).get("presentation") === "embedded";
  }

  async function request(context, path, options = {}, timeoutMs = 15000) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
      return await context.api(path, {...options, signal: controller.signal});
    } catch (error) {
      if (error?.name === "AbortError") throw new Error(context.t("读取产品目录超时"));
      throw error;
    } finally {
      clearTimeout(timer);
    }
  }

  function segment(context, items, active, onChange, className) {
    const nav = document.createElement("nav");
    nav.className = className || "product-header-tabs";
    nav.setAttribute("aria-label", context.t("产品目录"));
    items.forEach(([id, label]) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `research-section-tab product-header-tab${id === active ? " active" : ""}`;
      button.textContent = context.t(label);
      button.setAttribute("aria-current", id === active ? "page" : "false");
      button.addEventListener("click", () => onChange(id));
      nav.append(button);
    });
    return nav;
  }

  function catalogSwitch(context, active, source) {
    // The catalog has one navigation control.  The source page is a peer of
    // products and groups, not a second source-specific segmented control.
    const options = [["sources", "数据源"], ["products", "产品"], ["groups", "产品组"]];
    context.toolbar.append(segment(
      context, options, active,
      id => context.navigate(pathFor(
        id === "sources" ? "/products/sources" : id === "groups" ? "/products/groups" : "/products",
        source,
      )),
      "research-section-tabs product-catalog-tabs",
    ));
  }

  function sourceSummary(context, source) {
    const summary = document.createElement("p");
    summary.className = "catalog-source-summary";
    summary.textContent = source === "local"
      ? context.t("当前目录：本地已注册数据源")
      : context.t("当前目录：服务器已注册数据源");
    return summary;
  }

  function multilineCell(values, className = "catalog-source-lines") {
    const cell = document.createElement("div");
    cell.className = className;
    const items = Array.isArray(values) ? values : [values];
    items.map(value => String(value || "").trim()).filter(Boolean).forEach(value => {
      cell.append(Object.assign(document.createElement("div"), {textContent: value}));
    });
    if (!cell.childElementCount) cell.textContent = "—";
    return cell;
  }

  function sourceList(context) {
    return window.FTProductSources.list(context, {
      localCatalogAvailable, sourceOf, pathFor, catalogSwitch, request,
      loadCategories, sourceSummary, isCurrent,
    });
  }

  async function load(context, source) {
    const origin = source || sourceOf();
    const key = origin;
    if (cache.has(key)) return cache.get(key);
    const groupsRequest = origin === "local"
      ? request(context, "/api/client/product-groups")
      : request(context, "/api/catalog/product-groups");
    const productsRequest = origin === "local"
      ? request(context, "/api/client/product_names")
      : request(context, "/api/catalog/products");
    const [productsResult, groupsResult] = await Promise.allSettled([
      productsRequest, groupsRequest,
    ]);
    const productPayload = productsResult.status === "fulfilled" ? productsResult.value : {};
    const groupPayload = groupsResult.status === "fulfilled" ? groupsResult.value : {};
    const value = {
      products: Array.isArray(productPayload.products) ? productPayload.products : [],
      groups: Array.isArray(groupPayload.groups) ? groupPayload.groups : [],
      errors: {
        products: productsResult.status === "rejected" ? productsResult.reason : null,
        groups: groupsResult.status === "rejected" ? groupsResult.reason : null,
      },
      source: origin,
    };
    cache.set(key, value);
    return value;
  }

  async function loadCategories(context, source) {
    const endpoint = source === "local"
      ? "/api/client/product_categories"
      : "/api/catalog/categories";
    const value = await request(context, endpoint);
    return Array.isArray(value.categories) ? value : {
      ...value, categories: [], default_category_id: null, sources: [],
    };
  }

  async function loadSources(context, source) {
    const endpoint = source === "local"
      ? "/api/client/product_sources" : "/api/catalog/sources";
    const value = await request(context, endpoint);
    return Array.isArray(value.sources) ? value.sources : [];
  }

  async function loadTree(context, source, categoryID, dataSourceIDs) {
    const sourceKey = (dataSourceIDs || []).join(",") || "all";
    const key = `${source}:${sourceKey}:${categoryID || "all"}`;
    if (treeCache.has(key)) return treeCache.get(key);
    const query = new URLSearchParams({checkbox: "1"});
    if (categoryID) query.set("category", categoryID);
    (dataSourceIDs || []).forEach(value => query.append("data_source", value));
    const endpoint = source === "local"
      ? `/api/client/product_tree?${query}`
      : `/api/catalog/tree?${query}`;
    const value = await request(context, endpoint);
    treeCache.set(key, value.tree || value);
    return treeCache.get(key);
  }

  async function list(context, page = "products") {
    const source = sourceOf();
    context.activeNav("products");
    context.setHeading(
      page === "groups" ? context.t("产品组") : context.t("产品"),
      source === "local" ? context.t("本地产品目录") : context.t("服务器产品目录"),
    );
    catalogSwitch(context, page, source);
    const search = document.createElement("input");
    search.className = "toolbar-search";
    search.placeholder = page === "groups"
      ? context.t("搜索产品组") : context.t("搜索产品或代码");
    const refresh = context.button("↻", () => {
      cache.delete(source);
      [...treeCache.keys()].filter(key => key.startsWith(`${source}:`)).forEach(key => treeCache.delete(key));
      list(context, page);
    }, context.t("刷新"));
    context.toolbar.append(search, refresh);
    context.content.replaceChildren(FTUI.loading(context.t("正在读取产品目录…")));
    let value;
    try {
      value = await load(context, source);
    } catch (error) {
      if (!isCurrent(context)) return;
      context.content.replaceChildren(FTUI.empty(context.t("产品目录读取失败"), error.message || ""));
      return;
    }
    if (!isCurrent(context)) return;
    const root = document.createElement("div");
    root.className = "library-page";
    root.append(sourceSummary(context, source));
    const results = document.createElement("div");
    results.className = "library-results";
    root.append(results);
    context.content.replaceChildren(root);
    search.addEventListener("input", () => renderSearch(context, results, search.value, value, page, source));
    if (page === "groups") {
      if (value.errors?.groups) {
        renderSearch(context, results, "", {...value, groups: []}, page, source);
        results.prepend(FTUI.empty(context.t("产品组读取失败"), value.errors.groups.message || ""));
        return;
      }
      renderSearch(context, results, "", value, page, source);
      return;
    }
    const treeMount = document.createElement("div");
    treeMount.className = "product-tree-panel";
    results.replaceChildren(treeMount);
    try {
      const [categoryPayload, sourceDefinitions] = await Promise.all([
        loadCategories(context, source),
        loadSources(context, source),
      ]);
      if (!isCurrent(context)) return;
      const categoryStorageKey = `ft-product-category:${source}`;
      const combinationStorageKey = `ft-product-category-definitions:${source}`;
      let selected = localStorage.getItem(categoryStorageKey) || "";
      let combinations = [];
      try { combinations = JSON.parse(localStorage.getItem(combinationStorageKey) || "[]"); } catch (_) {}
      if (!Array.isArray(combinations)) combinations = [];
      const selectedSources = FTProductCategoryModel.availableSourceIDs(
        sourceDefinitions,
      );
      const renderTree = async () => {
        // No selected Category means the stable classifier-only product tree.
        // Category controls remain unchecked until the user explicitly saves
        // a dimension or a composition.
        const tree = await loadTree(context, source, selected, selectedSources);
        if (!isCurrent(context)) return;
        const contractTreePath = path => {
          const query = new URLSearchParams({path});
          if (selected) query.set("category", selected);
          selectedSources.forEach(value => query.append("data_source", value));
          return source === "local"
            ? `/api/client/contract_tree?${query}`
            : `/api/catalog/contract-tree?${query}`;
        };
        await FTProductTree.render(context, treeMount, tree, {
          categoryDefinitions: categoryPayload.categories,
          dataSourceDefinitions: sourceDefinitions,
          selectedDataSources: selectedSources,
          selectedCategory: selected,
          savedCombinations: combinations,
          contractTreePath,
          onSave: async (nextID, nextCombinations) => {
            selected = nextID;
            combinations = nextCombinations;
            localStorage.setItem(categoryStorageKey, selected);
            localStorage.setItem(combinationStorageKey, JSON.stringify(combinations));
            cache.clear();
            context.navigate(pathFor("/products", source));
          },
        });
        if (!isCurrent(context)) return;
      };
      await renderTree();
      if (!isCurrent(context)) return;
      if (search.value.trim()) renderSearch(context, results, search.value, value, page, source);
    } catch (error) {
      if (!isCurrent(context)) return;
      treeMount.replaceChildren(FTUI.empty(context.t("产品树读取失败"), error.message || ""));
    }
  }

  function renderSearch(context, mount, rawQuery, value, page, source) {
    const query = String(rawQuery || "").trim().toLowerCase();
    mount.querySelectorAll?.(".product-search-results").forEach(item => item.remove());
    if (!query) {
      if (page === "products") return;
    }
    const items = (page === "groups"
      ? value.groups.map(item => ({kind: "group", value: item}))
      : value.products.map(item => ({kind: "product", value: item})))
      .filter(item => matches(item.value, query));
    const section = document.createElement("section");
    section.className = "product-search-results";
    section.append(Object.assign(document.createElement("h2"), {
      textContent: query ? context.t("搜索结果") : context.t("已注册产品组"),
    }));
    if (!items.length) {
      section.append(FTUI.empty(context.t("没有匹配的产品"), context.t("请检查当前目录")));
      mount.prepend(section); return;
    }
    const view = FTUI.table(
      page === "groups"
        ? [context.t("名称"), context.t("创建者"), context.t("研究绑定"), context.t("产品"), context.t("说明"), context.t("来源")]
        : [context.t("类型"), context.t("名称"), context.t("说明"), context.t("产品路径"), context.t("来源")],
      items.map(item => item.kind === "group"
        ? [
            item.value.name,
            creatorLabel(item.value, context),
            researchLabel(item.value, context),
            productCount(item.value),
            item.value.description || "",
            groupSourceLabel(item.value, context),
          ]
        : [context.t("产品"), item.value.name || item.value.code, item.value.desc || "", item.value.product_path || "", (item.value.source_ids || []).join(", ")]),
    );
    [...view.body.rows].forEach((row, index) => {
      row.dataset.href = "true";
      row.addEventListener("click", () => {
        const item = items[index];
        const valueRef = item.kind === "group"
          ? (item.value.id || item.value.group_ref || item.value.name)
          : (item.value.name || item.value.code);
        context.navigate(pathFor(
          `/products/${item.kind}/${encodeURIComponent(valueRef)}`, source,
        ));
      });
    });
    section.append(view.shell);
    mount.prepend(section);
  }

  function detailHelpers() {
    return {sourceOf, load, catalogSwitch, sourceSummary, pathFor};
  }
  async function productDetail(context, target) {
    return window.FTProductDetails.productDetail(context, target, detailHelpers());
  }
  async function groupDetail(context, target) {
    return window.FTProductDetails.groupDetail(context, target, detailHelpers());
  }
  async function referenceDetail(context, kind, targetRef) {
    return window.FTProductDetails.referenceDetail(context, kind, targetRef, detailHelpers());
  }
  function pathCount(group) { return Array.isArray(group.paths) ? group.paths.length : (Array.isArray(group.product_names) ? group.product_names.length : 0); }
  function productCount(group) {
    return Array.isArray(group.products) && group.products.length
      ? group.products.length : pathCount(group);
  }
  function creatorLabel(group, context) {
    const kind = group.creator_kind === "profile"
      ? context.t("Profile") : context.t("用户");
    return `${kind} · ${group.creator_title || group.creator_ref || "—"}`;
  }
  function researchLabel(group, context) {
    const bindings = Array.isArray(group.research_bindings)
      ? group.research_bindings : [];
    if (!bindings.length) return context.t("未绑定研究");
    return bindings.map(item => item.title || item.research_ref).join("、");
  }
  function groupSourceLabel(group, context) {
    return group.source === "server" ? context.t("服务器") : context.t("本地");
  }
  function matches(value, query) { return !query || JSON.stringify(value || {}).toLowerCase().includes(query); }

  window.FTProducts = {groupDetail, list, productDetail, referenceDetail, sourceList};
})();
