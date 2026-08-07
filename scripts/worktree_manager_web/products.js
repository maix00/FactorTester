(() => {
  const cache = new Map();
  const treeCache = new Map();

  function sourceOf() {
    return embeddedOf() && new URLSearchParams(location.search).get("source") === "local"
      ? "local" : "server";
  }

  function pathFor(path, source = sourceOf()) {
    if (source !== "local") return path;
    const separator = path.includes("?") ? "&" : "?";
    return `${path}${separator}source=local`;
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
      ? context.t("当前数据源：本地客户端产品数据包")
      : context.t("当前数据源：服务器 Manager 产品数据包");
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

  function dataModesCell(context, modes) {
    const values = (Array.isArray(modes) ? modes : []).map(item => {
      const title = item?.title_zh || item?.id || "";
      return title ? `${title}：${item?.available ? context.t("已提供") : context.t("未提供")}` : "";
    });
    return multilineCell(values, "catalog-source-lines catalog-source-modes");
  }

  function availabilityCell(context, availability) {
    const value = availability || {};
    return multilineCell([
      `${context.t("状态")}：${value.status === "ready" ? context.t("可用") : context.t("暂无数据")}`,
      `${context.t("产品数")}：${value.product_count ?? 0}`,
    ], "catalog-source-lines catalog-source-availability");
  }

  function frequencyCell(context, availability) {
    const names = (availability?.frequency_names || []).map(value => String(value));
    return multilineCell(names.length ? names : [context.t("暂无频率")], "catalog-source-lines catalog-source-frequency");
  }

  async function sourceList(context) {
    const current = sourceOf();
    context.activeNav("products");
    context.setHeading(context.t("数据源"), context.t("产品目录"));
    catalogSwitch(context, "sources", current);
    const refresh = context.button("↻", () => sourceList(context), context.t("刷新"));
    context.toolbar.append(refresh);
    context.content.replaceChildren(FTUI.loading(context.t("正在读取数据源…")));

    const sources = [{
      id: "server", title: context.t("服务器产品数据包"),
      bundle: context.t("Manager 提供的产品、合约与行情目录"),
      description: context.t("适用于 Web 与 Swift 客户端的共享数据源"),
    }];
    // A browser cannot access the client filesystem.  The local row is only
    // meaningful inside the Swift embedded presentation.
    if (embeddedOf()) sources.unshift({
      id: "local", title: context.t("本地客户端产品数据包"),
      bundle: context.t("安装在本机并绑定当前账户的产品目录"),
      description: context.t("只在 Swift 客户端中可用"),
    });
    const rows = await Promise.all(sources.map(async item => {
      let descriptor = {
        source_name: item.title,
        bundle_name: item.bundle,
        bundle_id: "—",
        server_provided: item.id === "server",
        product_paths: [], categories: [], data_modes: [], availability: {},
      };
      try {
        const payload = await loadCategories(context, item.id);
        descriptor = (payload.sources || []).find(value => value.id === item.id) || descriptor;
      } catch (error) {
        descriptor.availability = {status: "error", error: error.message || ""};
      }
      return [item, descriptor];
    }));
    const root = document.createElement("div");
    root.className = "detail-stack product-source-page";
    root.append(sourceSummary(context, current));
    const table = FTUI.table(
      [context.t("数据源名称"), context.t("Bundle"), context.t("服务器提供"),
       context.t("产品路径"), context.t("产品类别"), context.t("数据形态"),
       context.t("可用性"), context.t("数据频率")],
      rows.map(([, descriptor]) => [
        descriptor.source_name || "—",
        multilineCell([descriptor.bundle_name, descriptor.bundle_id], "catalog-source-lines catalog-source-bundle"),
        descriptor.server_provided ? context.t("是") : context.t("否"),
        multilineCell(descriptor.product_paths, "catalog-source-lines catalog-source-paths"),
        multilineCell((descriptor.categories || []).map(category =>
          category.title_zh || category.title || category.id || "").filter(Boolean)),
        dataModesCell(context, descriptor.data_modes),
        availabilityCell(context, descriptor.availability),
        frequencyCell(context, descriptor.availability),
      ]),
    );
    rows.forEach(([item], index) => {
      const row = table.body.rows[index];
      row.dataset.href = "true";
      row.addEventListener("click", () => context.navigate(pathFor("/products", item.id)));
    });
    root.append(table.shell);
    root.append(Object.assign(document.createElement("p"), {
      className: "catalog-source-note",
      textContent: embeddedOf()
        ? context.t("选择数据源后，产品与产品组页面会读取对应的数据包")
        : context.t("Web 端只能访问服务器提供的数据源"),
    }));
    context.content.replaceChildren(root);
  }

  async function load(context, source) {
    const key = source || sourceOf();
    if (cache.has(key)) return cache.get(key);
    const groupsRequest = key === "local"
      ? request(context, "/api/client/product-groups")
      : request(context, context.servicePath("/api/product-groups"));
    const productsRequest = key === "local"
      ? request(context, "/api/client/product_names")
      : request(context, context.servicePath("/api/list_product_names"));
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
      source: key,
    };
    cache.set(key, value);
    return value;
  }

  async function loadCategories(context, source) {
    const endpoint = source === "local"
      ? "/api/client/product_categories"
      : context.servicePath("/api/product_categories");
    const value = await request(context, endpoint);
    return Array.isArray(value.categories) ? value : {
      ...value, categories: [], default_category_id: null, sources: [],
    };
  }

  async function loadTree(context, source, categoryID) {
    const key = `${source}:${categoryID}`;
    if (treeCache.has(key)) return treeCache.get(key);
    const query = `?checkbox=1&category=${encodeURIComponent(categoryID)}`;
    const endpoint = source === "local"
      ? `/api/client/product_tree${query}`
      : context.servicePath(`/api/product_tree${query}`);
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
      context.content.replaceChildren(FTUI.empty(context.t("产品目录读取失败"), error.message || ""));
      return;
    }
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
      const categoryPayload = await loadCategories(context, source);
      const categoryStorageKey = `ft-product-category:${source}`;
      const combinationStorageKey = `ft-product-category-definitions:${source}`;
      let selected = localStorage.getItem(categoryStorageKey)
        || categoryPayload.default_category_id || "";
      let combinations = [];
      try { combinations = JSON.parse(localStorage.getItem(combinationStorageKey) || "[]"); } catch (_) {}
      if (!Array.isArray(combinations)) combinations = [];
      const renderTree = async () => {
        const tree = selected ? await loadTree(context, source, selected) : [];
        const contractTreePath = path => {
          const query = `?path=${encodeURIComponent(path)}&category=${encodeURIComponent(selected)}`;
          return source === "local"
            ? `/api/client/contract_tree${query}`
            : context.servicePath(`/api/contract_tree${query}`);
        };
        await FTProductTree.render(context, treeMount, tree, {
          categoryDefinitions: categoryPayload.categories,
          selectedCategory: selected,
          savedCombinations: combinations,
          contractTreePath,
          onSave: async (nextID, nextCombinations) => {
            selected = nextID;
            combinations = nextCombinations;
            localStorage.setItem(categoryStorageKey, selected);
            localStorage.setItem(combinationStorageKey, JSON.stringify(combinations));
            await renderTree();
          },
        });
      };
      await renderTree();
      if (search.value.trim()) renderSearch(context, results, search.value, value, page, source);
    } catch (error) {
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
      mount.append(section); return;
    }
    const view = FTUI.table(
      [context.t("类型"), context.t("名称"), context.t("成员或代码"), context.t("来源")],
      items.map(item => item.kind === "group"
        ? [context.t("产品组"), item.value.name, pathCount(item.value), source === "local" ? context.t("本地") : context.t("服务器")]
        : [context.t("产品"), item.value.desc || item.value.name, item.value.name || item.value.code, item.value.exchange || ""]),
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
    mount.append(section);
  }

  async function productDetail(context, target) {
    const source = sourceOf();
    context.activeNav("products");
    const value = await load(context, source);
    const pathLeaf = String(target || "").split("/").filter(Boolean).pop() || target;
    const product = value.products.find(item =>
      item.name === target || item.code === target || item.name === pathLeaf || item.code === pathLeaf
    );
    if (!product) return referenceDetail(context, "product", target);
    context.setHeading(product.desc || product.name, context.t("产品详情"));
    catalogSwitch(context, "products", source);
    context.updateActiveTab?.({title: product.desc || product.name});
    context.content.replaceChildren(FTUI.loading(context.t("正在读取产品资料…")));
    const fieldsPath = `/api/product_fields?name=${encodeURIComponent(product.name)}`;
    const fieldsPayload = await context.api(source === "local"
      ? `/api/client/product_fields?name=${encodeURIComponent(product.name)}`
      : context.servicePath(fieldsPath));
    const root = document.createElement("div"); root.className = "detail-stack product-detail-page";
    root.append(sourceSummary(context, source));
    root.append(FTUI.table(
      [context.t("字段"), context.t("说明"), context.t("当前值")],
      normalizeFields(fieldsPayload.fields).map(item => [item.name || item.key, item.description || item.desc, item.value]),
    ).shell);
    const metadata = document.createElement("section"); metadata.className = "product-detail-metadata";
    metadata.append(Object.assign(document.createElement("h2"), {textContent: context.t("数据源与频率")}));
    const metadataMount = document.createElement("div"); metadataMount.append(FTUI.loading(context.t("正在读取数据能力…")));
    metadata.append(metadataMount); root.append(metadata);
    const term = document.createElement("section"); term.className = "product-term-structure";
    term.append(Object.assign(document.createElement("h2"), {textContent: context.t("期限结构")}));
    const termMount = document.createElement("div"); termMount.append(FTUI.loading(context.t("正在读取合约列表…")));
    term.append(termMount); root.append(term);
    const chart = document.createElement("section"); chart.className = "product-price-section";
    chart.append(Object.assign(document.createElement("h2"), {textContent: context.t("价格曲线")}));
    const chartMount = document.createElement("div"); chartMount.append(FTUI.loading(context.t("正在读取价格曲线…")));
    chart.append(chartMount); root.append(chart);
    context.content.replaceChildren(root);
    const end = new Date(); const start = new Date(end); start.setFullYear(start.getFullYear() - 1);
    const priceRequest = context.api(context.servicePath("/api/get_price_data"), {
      method: "POST", body: JSON.stringify({product_name: product.name, freq: "DAY1", adjusted: false,
        start_date: start.toISOString().slice(0, 10), end_date: end.toISOString().slice(0, 10)}),
    }).catch(() => ({}));
    const contractsRequest = context.api(context.servicePath(
      `/api/get_contracts?product=${encodeURIComponent(product.name)}`
    )).catch(() => ({}));
    const [price, contracts] = await Promise.all([priceRequest, contractsRequest]);
    const sources = price.available_sources || [];
    const freqs = price.available_freqs || [];
    metadataMount.replaceChildren(FTUI.table(
      [context.t("项目"), context.t("值")],
      [[context.t("当前数据源"), price.data_source || ""],
       [context.t("可用数据源"), sources.map(item => item.alias || item).join(", ")],
       [context.t("可用频率"), freqs.join(", ")]],
    ).shell);
    const contractRows = Array.isArray(contracts.contracts) ? contracts.contracts : [];
    if (!contracts.supports_term_structure || !contractRows.length) {
      termMount.replaceChildren(FTUI.empty(context.t("暂无期限结构"), context.t("该产品没有可用的连续合约列表")));
    } else {
      const table = FTUI.table(
        [context.t("合约"), context.t("开始"), context.t("结束"), context.t("数据")],
        contractRows.map(item => [item.contract || item.uid, item.start || "", item.end || "", item.has_data ? context.t("可用") : context.t("无数据")]),
      );
      [...table.body.rows].forEach((row, index) => {
        row.dataset.href = "true";
        row.addEventListener("click", () => context.navigate(pathFor(
          `/products/contract/${encodeURIComponent(contractRows[index].uid || contractRows[index].contract || "")}`,
          source,
        )));
      });
      termMount.replaceChildren(table.shell);
    }
    if (window.FTJobArtifactViewers?.priceChart && Array.isArray(price.data)) {
      FTJobArtifactViewers.priceChart(context, chartMount, JSON.stringify(price.data));
    } else {
      chartMount.replaceChildren(FTUI.empty(context.t("价格曲线暂不可用"), ""));
    }
  }

  async function groupDetail(context, target) {
    const source = sourceOf();
    context.activeNav("products");
    const value = await load(context, source);
    const stableID = String(target || "").startsWith("product-group:")
      ? String(target).slice("product-group:".length) : "";
    let group = value.groups.find(item => item.name === target || item.id === stableID || item.group_ref === target);
    if (source === "local") {
      const payload = await context.api(`/api/client/product-groups/${encodeURIComponent(group?.group_ref || group?.id || target)}`);
      group = payload.group || group;
    } else if (source !== "local") {
      const payload = await context.api(context.servicePath(`/api/product-groups/${encodeURIComponent(group?.name || target)}`));
      group = payload.group || group;
    }
    if (!group) throw new Error(context.t("产品组不存在或当前目录无法解析该引用"));
    context.setHeading(group.name || target, context.t("产品组详情"));
    catalogSwitch(context, "groups", source);
    context.updateActiveTab?.({title: group.name || target});
    const root = document.createElement("div"); root.className = "detail-stack product-group-detail-page";
    root.append(sourceSummary(context, source));
    root.append(FTUI.table([context.t("字段"), context.t("值")], FTUI.fieldRows(group)).shell);
    const names = Array.isArray(group.product_names) ? group.product_names : [];
    const memberships = Array.isArray(group.products) ? group.products : [];
    const productRefs = names.length ? names : memberships.map(item => item.product_ref || item.product_name).filter(Boolean);
    const productsSection = document.createElement("section"); productsSection.className = "product-group-products";
    productsSection.append(Object.assign(document.createElement("h2"), {textContent: context.t("包含的产品")}));
    const links = productRefs.map(name => {
      const link = document.createElement("button"); link.type = "button"; link.className = "catalog-link";
      link.textContent = name; link.addEventListener("click", () => context.navigate(pathFor(
        `/products/product/${encodeURIComponent(name)}`, source,
      ))); return link;
    });
    if (links.length) productsSection.append(...links); else productsSection.append(FTUI.empty(context.t("暂无产品"), ""));
    root.append(productsSection);
    const paths = Array.isArray(group.paths) ? group.paths : [];
    if (paths.length) root.append(FTUI.table([context.t("产品路径"), context.t("说明")], paths.map(item => typeof item === "string" ? [item, ""] : [item.path || item.id || item.name, item.label || item.description || ""])).shell);
    const subjects = [
      ...(Array.isArray(group.factor_refs) ? group.factor_refs : []).map(ref => ({type: context.t("因子"), ref, path: "/factors/factor/"})),
      ...(Array.isArray(group.factor_set_refs) ? group.factor_set_refs : []).map(ref => ({type: context.t("因子集合"), ref, path: "/factors/set/"})),
    ];
    if (subjects.length) {
      const table = FTUI.table([context.t("类型"), context.t("关联因子")], subjects.map(item => [item.type, item.ref]));
      [...table.body.rows].forEach((row, index) => { row.dataset.href = "true"; row.addEventListener("click", () => context.navigate(`${subjects[index].path}${encodeURIComponent(subjects[index].ref)}`)); });
      root.append(table.shell);
    }
    context.content.replaceChildren(root);
  }

  async function referenceDetail(context, kind, targetRef) {
    context.activeNav("products");
    context.content.replaceChildren(FTUI.loading(context.t("正在解析产品引用…")));
    if (kind === "contract" || kind === "continuous-contract") {
      try {
        const payload = await context.api(context.servicePath("/api/get_price_data"), {
          method: "POST",
          body: JSON.stringify({contract_uid: targetRef, freq: "DAY1", adjusted: false}),
        });
        if (payload.success !== false) {
          context.setHeading(payload.contract_name || targetRef, context.t("合约详情"));
          catalogSwitch(context, "products", sourceOf());
          context.updateActiveTab?.({title: payload.contract_name || targetRef});
          const root = document.createElement("div"); root.className = "detail-stack product-detail-page";
          root.append(FTUI.table(
            [context.t("字段"), context.t("值")],
            [[context.t("合约"), targetRef], [context.t("频率"), payload.freq || ""],
             [context.t("数据源"), payload.data_source || ""], [context.t("数据点"), payload.count || (payload.data || []).length]],
          ).shell);
          const chart = document.createElement("section"); chart.className = "product-price-section";
          chart.append(Object.assign(document.createElement("h2"), {textContent: context.t("价格曲线")}));
          const chartMount = document.createElement("div");
          if (window.FTJobArtifactViewers?.priceChart && Array.isArray(payload.data)) {
            FTJobArtifactViewers.priceChart(context, chartMount, JSON.stringify(payload.data));
          } else chartMount.append(FTUI.empty(context.t("价格曲线暂不可用"), ""));
          chart.append(chartMount); root.append(chart);
          context.content.replaceChildren(root); return;
        }
      } catch (_) {}
    }
    const payload = await context.api(context.servicePath(`/api/report-references/validate?kind=${encodeURIComponent(kind)}&target_ref=${encodeURIComponent(targetRef)}`));
    const reference = payload.reference || payload.data?.reference || {};
    context.setHeading(reference.label || context.t("产品详情"), context.t("产品库"));
    catalogSwitch(context, "products", sourceOf());
    context.updateActiveTab?.({title: reference.label || context.t("产品详情")});
    const root = document.createElement("div"); root.className = "detail-stack";
    root.append(FTUI.table([context.t("字段"), context.t("值")], [...FTUI.fieldRows(reference), ...FTUI.fieldRows(reference.object || {})]).shell);
    context.content.replaceChildren(root);
  }

  function normalizeFields(value) {
    if (Array.isArray(value)) return value.map(item => item && typeof item === "object" ? item : {name: String(item), value: ""});
    if (value && typeof value === "object") return Object.entries(value).map(([name, item]) => item && typeof item === "object" && !Array.isArray(item) ? {name, ...item} : {name, value: item});
    return [];
  }
  function pathCount(group) { return Array.isArray(group.paths) ? group.paths.length : (Array.isArray(group.product_names) ? group.product_names.length : 0); }
  function matches(value, query) { return !query || JSON.stringify(value || {}).toLowerCase().includes(query); }

  window.FTProducts = {groupDetail, list, productDetail, referenceDetail, sourceList};
})();
