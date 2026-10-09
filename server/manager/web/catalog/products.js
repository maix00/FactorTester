(() => {
  const cache = new Map();
  const categoryCache = new Map();
  const sourceCache = new Map();
  const treeCache = new Map();

  function cachedRequest(store, key, load) {
    if (store.has(key)) return store.get(key);
    const pending = Promise.resolve().then(load).catch(error => {
      store.delete(key);
      throw error;
    });
    store.set(key, pending);
    return pending;
  }

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
    const options = [
      ["sources", "数据源"], ["products", "产品"],
      ["categories", "产品分类"], ["groups", "产品组"],
    ];
    context.toolbar.append(segment(
      context, options, active,
      id => context.navigate(pathFor(
        id === "sources" ? "/products/sources"
          : id === "groups" ? "/products/groups"
          : id === "categories" ? "/products/categories" : "/products",
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

  function sourceFamilyPath(id, source = sourceOf()) {
    return pathFor(
      `/products/sources/${encodeURIComponent(String(id || ""))}`,
      source,
    );
  }

  function sourceFamilyDetail(context, id) {
    return window.FTProductSourceFamilyDetail.render(context, {
      localCatalogAvailable, sourceOf, pathFor, catalogSwitch, request,
      loadCategories, loadSources, sourceSummary, isCurrent,
    }, id);
  }

  async function load(context, source, options = {}) {
    const origin = source || sourceOf();
    const includeProducts = options.includeProducts !== false;
    const includeGroups = options.includeGroups !== false;
    const key = `${origin}:products=${includeProducts}:groups=${includeGroups}`;
    return cachedRequest(cache, key, async () => {
      const groupsRequest = includeGroups
        ? (origin === "local"
          ? request(context, "/api/client/product-groups")
          // The product library and every test editor consume the same
          // Manager-owned account-domain directory.  Member paths belong to
          // the detail request and must never make the list page fall back to
          // the retired business-port product-group API.
          : request(context, "/api/product-library/product-groups?view=summary"))
        : Promise.resolve({});
      const productsRequest = includeProducts
        ? (origin === "local"
          ? request(context, "/api/client/product_names")
          : request(context, "/api/product-library/products"))
        : Promise.resolve({});
      const [productsResult, groupsResult] = await Promise.allSettled([
        productsRequest, groupsRequest,
      ]);
      const productPayload = productsResult.status === "fulfilled" ? productsResult.value : {};
      const groupPayload = groupsResult.status === "fulfilled" ? groupsResult.value : {};
      return {
        products: Array.isArray(productPayload.products) ? productPayload.products : [],
        groups: Array.isArray(groupPayload.groups) ? groupPayload.groups : [],
        errors: {
          products: productsResult.status === "rejected" ? productsResult.reason : null,
          groups: groupsResult.status === "rejected" ? groupsResult.reason : null,
        },
        source: origin,
      };
    });
  }

  async function loadCategories(context, source) {
    const endpoint = source === "local"
      ? "/api/client/product_categories"
      : "/api/product-library/categories";
    return cachedRequest(categoryCache, source, async () => {
      const value = await request(context, endpoint);
      return Array.isArray(value.categories) ? value : {
        ...value, categories: [], default_category_id: null, sources: [],
      };
    });
  }

  async function loadSources(context, source) {
    const endpoint = source === "local"
      ? "/api/client/product_sources" : "/api/product-library/data-sources";
    return cachedRequest(sourceCache, source, async () => {
      const value = await request(context, endpoint);
      return Array.isArray(value.sources) ? value.sources : [];
    });
  }

  async function loadTree(context, source, categoryIDs, dataSourceIDs) {
    const categories = Array.isArray(categoryIDs) ? categoryIDs : [];
    const sourceKey = (dataSourceIDs || []).join(",") || "all";
    const categoryKey = categories.join(",") || "all";
    const key = `${source}:${sourceKey}:${categoryKey}`;
    return cachedRequest(treeCache, key, async () => {
      const query = new URLSearchParams({checkbox: "1"});
      categories.forEach(value => query.append("category", value));
      (dataSourceIDs || []).forEach(value => query.append("data_source", value));
      const endpoint = source === "local"
        ? `/api/client/product_tree?${query}`
        : `/api/product-library/tree?${query}`;
      const value = await request(context, endpoint);
      return value.tree || value;
    });
  }

  async function loadProductTree(context, source = "server") {
    const sourceDefinitions = await loadSources(context, source);
    const sourceIDs = FTProductCategoryModel.availableSourceIDs(sourceDefinitions);
    const tree = await loadTree(context, source, [], sourceIDs);
    const endpoint = source === "local"
      ? "/api/client/contract_tree" : "/api/product-library/contract-tree";
    return {
      tree,
      source,
      sourceIDs,
      contractTreePath: (path, params = {}) => {
        const query = new URLSearchParams({path});
        sourceIDs.forEach(value => query.append("data_source", value));
        if (params.query) query.set("query", params.query);
        if (params.page) query.set("page", String(params.page));
        if (params.limit) query.set("limit", String(params.limit));
        return `${endpoint}?${query}`;
      },
    };
  }

  function rejectProductGroupWrite(context, source) {
    const message = !context.session
      ? context.t("访客模式只能查看产品组")
      : source === "local"
        ? context.t("本地产品组不可直接编辑")
        : context.t("产品组不可编辑");
    if (typeof window.alert === "function") window.alert(message);
    else context.showNotice?.(message, true);
  }

  function productGroupManagementActions(context, source) {
    const actions = document.createElement("div");
    actions.className = "product-category-management-actions product-group-management-actions";
    // Keep the create affordance visible on the same catalog surface as the
    // category actions. A visitor can see the catalog, but cannot write.
    const showWriteActions = !context.session || source !== "local";
    const canWrite = source === "server" && Boolean(context.session);
    if (showWriteActions) {
      actions.append(FTUI.actionButton(context.t("新增产品组"), () => {
        if (!canWrite) {
          rejectProductGroupWrite(context, source);
          return;
        }
        context.navigate(pathFor("/products/group/new", source));
      }, {variant: "primary"}));
    }
    return actions;
  }

  async function list(context, page = "products") {
    const source = sourceOf();
    if (page === "categories") {
      return window.FTProductCategories.list(context, {
        localCatalogAvailable, sourceOf, pathFor, catalogSwitch,
        loadCategories, loadSources, loadProductTree, sourceSummary, sourceFamilyPath,
        isCurrent: () => isCurrent(context),
      });
    }
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
    const refresh = FTUI.refreshButton(context, async () => {
      if (source !== "local" && context.session) {
        await context.api("/api/catalog/refresh", {method: "POST"});
      }
      [...cache.keys()].filter(key => key.startsWith(`${source}:`))
        .forEach(key => cache.delete(key));
      categoryCache.delete(source);
      sourceCache.delete(source);
      [...treeCache.keys()].filter(key => key.startsWith(`${source}:`)).forEach(key => treeCache.delete(key));
      return list(context, page);
    });
    context.toolbar.append(search, refresh);
    context.content.replaceChildren(FTUI.loading(context.t("正在读取产品目录…")));
    let value;
    try {
      value = await load(context, source, {
        includeProducts: page !== "products",
        includeGroups: page === "groups",
      });
    } catch (error) {
      if (!isCurrent(context)) return;
      context.content.replaceChildren(FTUI.empty(context.t("产品目录读取失败"), error.message || ""));
      return;
    }
    if (!isCurrent(context)) return;
    const root = document.createElement("div");
    root.className = "library-page";
    root.append(sourceSummary(context, source));
    if (page === "groups") {
      root.append(productGroupManagementActions(context, source));
    }
    const results = document.createElement("div");
    results.className = "library-results";
    root.append(results);
    context.content.replaceChildren(root);
    search.addEventListener("input", () => {
      if (page === "groups") {
        renderSearch(context, results, search.value, value, page, source);
      } else {
        renderProductSearch(context, results, search.value, source);
      }
    });
    if (page === "groups") {
      if (value.errors?.groups) {
        renderSearch(context, results, "", {...value, groups: []}, page, source);
        results.prepend(FTUI.empty(context.t("产品组读取失败"), value.errors.groups.message || ""));
        return;
      }
      renderSearch(context, results, "", value, page, source);
      return;
    }
    const categoryMount = document.createElement("div");
    categoryMount.className = "product-category-mount";
    const treeMount = document.createElement("div");
    treeMount.className = "product-tree-panel";
    results.replaceChildren(categoryMount, treeMount);
    try {
      // Category controls need only category definitions. Start the source
      // lookup concurrently, but keep it inside the deferred tree loader so a
      // slow federated descriptor lookup cannot delay the category filter.
      const sourceDefinitionsPromise = loadSources(context, source).then(
        definitions => ({definitions, error: null}),
        error => ({definitions: [], error}),
      );
      const categoryPayload = await loadCategories(context, source);
      if (!isCurrent(context)) return;
      const categoryStorageKey = `ft-product-category:${source}`;
      let selected = localStorage.getItem(categoryStorageKey) || "";
      let selectedIDs = FTProductTree.categorySelectionValues(
        selected, categoryPayload.categories,
      );
      const canonicalSelected = FTProductTree.categorySelectionID(
        selectedIDs, categoryPayload.categories,
      );
      if (canonicalSelected !== selected) {
        selected = canonicalSelected;
        localStorage.setItem(categoryStorageKey, selected);
      }
      let sourceDefinitions = [];
      let selectedSources = [];
      const contractTreePath = (path, params = {}) => {
        const query = new URLSearchParams({path});
        selectedIDs.forEach(value => query.append("category", value));
        selectedSources.forEach(value => query.append("data_source", value));
        if (params.query) query.set("query", params.query);
        if (params.page) query.set("page", String(params.page));
        if (params.limit) query.set("limit", String(params.limit));
        return source === "local"
          ? `/api/client/contract_tree?${query}`
          : `/api/product-library/contract-tree?${query}`;
      };
      const treeOptions = {
        categoryDefinitions: categoryPayload.categories,
        dataSourceDefinitions: sourceDefinitions,
        sourceFamilyPath,
        selectedDataSources: selectedSources,
        selectedCategory: selected,
        contractTreePath,
        categoryMount,
        source,
        isCurrent: () => isCurrent(context),
        loadTree: async () => {
          const sourceResult = await sourceDefinitionsPromise;
          if (!isCurrent(context)) return [];
          if (sourceResult.error) throw sourceResult.error;
          sourceDefinitions = sourceResult.definitions;
          selectedSources = FTProductCategoryModel.availableSourceIDs(
            sourceDefinitions,
          );
          // The tree's lazy product-table rows retain this options object, so
          // publish descriptors before the initial tree is drawn.
          treeOptions.dataSourceDefinitions = sourceDefinitions;
          treeOptions.selectedDataSources = selectedSources;
          return loadTree(context, source, selectedIDs, selectedSources);
        },
        onSave: async nextID => {
          selected = nextID;
          selectedIDs = FTProductTree.categorySelectionValues(
            selected, categoryPayload.categories,
          );
          localStorage.setItem(categoryStorageKey, selected);
          treeOptions.selectedCategory = selected;
          cache.clear();
          categoryCache.clear();
          sourceCache.clear();
          treeCache.clear();
          await renderTree();
        },
      };
      const renderTree = async () => {
        // No selected Category means the stable classifier-only product tree.
        // Category controls remain unchecked until the user explicitly saves
        // a dimension or a composition.
        if (!isCurrent(context)) return;
        await FTProductTree.render(context, treeMount, null, treeOptions);
        if (!isCurrent(context)) return;
      };
      await renderTree();
      if (!isCurrent(context)) return;
      if (search.value.trim()) renderProductSearch(context, results, search.value, source);
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
        ? [context.t("名称"), context.t("创建者"), context.t("研究绑定"), context.t("产品分类"), context.t("产品"), context.t("说明"), context.t("来源")]
        : [context.t("类型"), context.t("名称"), context.t("说明"), context.t("产品路径"), context.t("来源")],
      items.map(item => item.kind === "group"
        ? [
            item.value.name,
            creatorLabel(item.value, context),
            researchLabel(item.value, context),
            categoryLabel(item.value, context),
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

  async function renderProductSearch(context, mount, rawQuery, source) {
    const query = String(rawQuery || "").trim();
    mount.querySelectorAll?.(".product-search-results").forEach(item => item.remove());
    if (!query) return;
    const requestID = Number(mount.dataset.productSearchRequest || 0) + 1;
    mount.dataset.productSearchRequest = String(requestID);
    const section = document.createElement("section");
    section.className = "product-search-results";
    section.append(Object.assign(document.createElement("h2"), {
      textContent: context.t("搜索结果"),
    }));
    const endpoint = source === "local"
      ? "/api/client/product_names" : "/api/product-library/products";
    const params = new URLSearchParams({query, page: "1", limit: "50"});
    try {
      const payload = await request(context, `${endpoint}?${params}`);
      if (mount.dataset.productSearchRequest !== String(requestID)) return;
      const items = Array.isArray(payload.products) ? payload.products : [];
      if (!items.length) {
        section.append(FTUI.empty(
          context.t("没有匹配的产品"), context.t("请检查当前目录"),
        ));
        mount.prepend(section);
        return;
      }
      const view = FTUI.table([
        context.t("类型"), context.t("名称"), context.t("产品描述"),
        context.t("交易所"), context.t("产品路径"), context.t("数据源"),
      ], items.map(item => [
        context.t("产品"), item.name || item.code || "—", item.desc || "—",
        item.exchange || "—", item.product_path || "—",
        (item.source_ids || []).join(", "),
      ]));
      view.shell.classList.add("product-search-table-shell");
      [...view.body.rows].forEach((row, index) => {
        const item = items[index];
        row.dataset.href = "true";
        row.addEventListener("click", () => context.navigate(pathFor(
          `/products/product/${encodeURIComponent(item.name || item.code)}`,
          source,
        )));
      });
      section.append(view.shell);
    } catch (error) {
      if (mount.dataset.productSearchRequest !== String(requestID)) return;
      section.append(FTUI.empty(
        context.t("产品目录读取失败"), error.message || "",
      ));
    }
    mount.prepend(section);
  }

  function detailHelpers() {
    return {
      sourceOf, load, loadCategories, loadProductTree, loadSources, loadTree,
      loadSourceIDs: definitions => FTProductCategoryModel.availableSourceIDs(definitions),
      catalogSwitch, sourceSummary, sourceFamilyPath, pathFor,
      isCurrent,
    };
  }
  async function productDetail(context, target) {
    return window.FTProductDetails.productDetail(context, target, detailHelpers());
  }
  async function groupDetail(context, target, mode = "") {
    return window.FTProductGroupDetail.render(
      context, target, detailHelpers(), mode,
    );
  }
  async function referenceDetail(context, kind, targetRef) {
    return window.FTProductDetails.referenceDetail(context, kind, targetRef, detailHelpers());
  }
  async function categoryDetail(context, target, mode) {
    return window.FTProductCategoryDetails.render(
      context, target, mode, detailHelpers(),
    );
  }
  function pathCount(group) { return Array.isArray(group.paths) ? group.paths.length : (Array.isArray(group.product_names) ? group.product_names.length : 0); }
  function productCount(group) {
    return Array.isArray(group.products) && group.products.length
      ? group.products.length : pathCount(group);
  }
  function creatorLabel(group, context) {
    const kind = group.creator_kind === "profile"
      ? context.t("Profile") : context.t("用户");
    const label = group.creator_kind === "profile" ? group.creator_title || group.creator_ref
      : FTUI.userLabel(group.creator_ref, group.creator_title);
    return FTUI.userDisplay(group.creator_ref, `${kind} · ${label || "—"}`);
  }
  function researchLabel(group, context) {
    const bindings = Array.isArray(group.research_bindings)
      ? group.research_bindings : [];
    if (!bindings.length) return context.t("未绑定研究");
    return bindings.map(item => item.title || item.research_ref).join("、");
  }
  function categoryLabel(group, context) {
    const bindings = Array.isArray(group.category_bindings)
      ? group.category_bindings : [];
    if (bindings.length) {
      return bindings.map(item => item.title_zh || item.alias || item.id).join("、");
    }
    return (group.category_ids || []).length
      ? group.category_ids.join("、") : context.t("未绑定分类");
  }
  function groupSourceLabel(group, context) {
    return group.source === "server" ? context.t("服务器") : context.t("本地");
  }
  function matches(value, query) { return !query || JSON.stringify(value || {}).toLowerCase().includes(query); }

  window.FTProducts = {
    categoryDetail, groupDetail, list, productDetail, referenceDetail,
    sourceFamilyDetail, sourceList,
  };
})();
