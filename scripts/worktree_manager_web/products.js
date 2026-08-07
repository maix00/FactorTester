(() => {
  const cache = new Map();
  const treeCache = new Map();

  function sourceOf() {
    return new URLSearchParams(location.search).get("source") === "local"
      ? "local" : "server";
  }

  function pathFor(path, source = sourceOf()) {
    if (source !== "local") return path;
    const separator = path.includes("?") ? "&" : "?";
    return `${path}${separator}source=local`;
  }

  function catalogSwitch(context, active, source) {
    const select = document.createElement("select");
    select.className = "catalog-header-switcher";
    select.title = context.t("切换产品目录");
    // Keep the options as one shared header control for Web and Swift WebView.
    const options = [
      ["products", context.t("产品"), "/products"],
      ["groups", context.t("产品组"), "/products/groups"],
    ];
    options.forEach(([id, label, path]) => {
      const option = document.createElement("option");
      option.value = id; option.textContent = label; option.selected = id === active;
      select.append(option);
      option.dataset.path = path;
    });
    select.addEventListener("change", () => {
      const path = options.find(item => item[0] === select.value)?.[2] || "/products";
      context.navigate(pathFor(path, source));
    });
    context.toolbar.append(select);
    return select;
  }

  async function load(context, source) {
    const key = source || sourceOf();
    if (cache.has(key)) return cache.get(key);
    const groupsRequest = key === "local"
      ? context.api("/api/client/product-groups")
      : context.api(context.servicePath("/api/product-groups"));
    const [productPayload, groupPayload] = await Promise.all([
      context.api(context.servicePath("/api/list_product_names")), groupsRequest,
    ]);
    const value = {
      products: Array.isArray(productPayload.products) ? productPayload.products : [],
      groups: Array.isArray(groupPayload.groups) ? groupPayload.groups : [],
      source: key,
    };
    cache.set(key, value);
    return value;
  }

  async function loadTree(context) {
    const key = sourceOf();
    if (treeCache.has(key)) return treeCache.get(key);
    const value = await context.api(context.servicePath("/api/product_tree?checkbox=1"));
    treeCache.set(key, value);
    return value;
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
      cache.delete(source); treeCache.delete(source); list(context, page);
    }, context.t("刷新"));
    context.toolbar.append(search, refresh);
    context.content.replaceChildren(FTUI.loading(context.t("正在读取产品目录…")));
    const value = await load(context, source);
    const root = document.createElement("div");
    root.className = "library-page";
    const results = document.createElement("div");
    results.className = "library-results";
    root.append(results);
    context.content.replaceChildren(root);
    search.addEventListener("input", () => renderSearch(context, results, search.value, value, page, source));
    if (page === "groups") {
      renderSearch(context, results, "", value, page, source);
      return;
    }
    const treeMount = document.createElement("div");
    treeMount.className = "product-tree-panel";
    results.replaceChildren(treeMount);
    try {
      const tree = await loadTree(context);
      const storageKey = `ft-product-categories:${source}`;
      let selected = null;
      try { selected = JSON.parse(localStorage.getItem(storageKey) || "null"); } catch (_) {}
      FTProductTree.render(context, treeMount, tree, {
        selectedCategories: Array.isArray(selected) ? selected : undefined,
        onSave: categories => localStorage.setItem(storageKey, JSON.stringify(categories)),
      });
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
    const fieldsPayload = await context.api(context.servicePath(
      `/api/product_fields?name=${encodeURIComponent(product.name)}`
    ));
    const root = document.createElement("div"); root.className = "detail-stack product-detail-page";
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

  window.FTProducts = {groupDetail, list, productDetail, referenceDetail};
})();
