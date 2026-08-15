(() => {
  function current(context) {
    return context.isRouteCurrent?.() !== false;
  }

  function normalizeFields(value) {
    if (Array.isArray(value)) {
      return value.map(item => item && typeof item === "object"
        ? item : {name: String(item), value: ""});
    }
    if (value && typeof value === "object") {
      return Object.entries(value).map(([name, item]) =>
        item && typeof item === "object" && !Array.isArray(item)
          ? {name, ...item} : {name, value: item});
    }
    return [];
  }

  async function productDetail(context, target, helpers) {
    const source = helpers.sourceOf();
    context.activeNav("products");
    const value = await helpers.load(context, source);
    if (!current(context)) return;
    const rawTarget = String(target || "");
    const withoutKind = rawTarget.startsWith("product:")
      ? rawTarget.slice("product:".length) : rawTarget;
    const pathLeaf = withoutKind.split("/").filter(Boolean).pop() || withoutKind;
    const product = value.products.find(item =>
      item.name === rawTarget || item.code === rawTarget
      || item.product_ref === rawTarget || item.product_path === withoutKind
      || item.name === pathLeaf || item.code === pathLeaf
    );
    const membership = value.groups.flatMap(group =>
      Array.isArray(group.products) ? group.products : []
    ).find(item => {
      const ref = String(item.product_ref || item.product_name || "");
      return [ref, ref.replace(/^product:/, ""), item.display_name, item.name]
        .filter(Boolean).includes(rawTarget)
        || ref.split("/_products/").pop() === pathLeaf;
    });
    if (!product && membership?.available === false) {
      unavailableProductDetail(context, membership, source, helpers);
      return;
    }
    if (!product) return referenceDetail(context, "product", target, helpers);
    context.setHeading(product.name || product.code, product.desc || context.t("产品详情"));
    helpers.catalogSwitch(context, "products", source);
    context.updateActiveTab?.({title: product.name || product.code});
    context.content.replaceChildren(FTUI.loading(context.t("正在读取产品资料…")));
    const fieldsPayload = await context.api(source === "local"
      ? `/api/client/product_fields?name=${encodeURIComponent(product.name)}`
      : `/api/catalog/product-fields?name=${encodeURIComponent(product.name)}`);
    if (!current(context)) return;
    const root = document.createElement("div"); root.className = "detail-stack product-detail-page";
    root.append(helpers.sourceSummary(context, source));
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
    const priceEndpoint = source === "local"
      ? "/api/client/product_prices" : "/api/catalog/prices";
    const contractsEndpoint = source === "local"
      ? "/api/client/product_contracts" : "/api/catalog/contracts";
    const priceRequest = context.api(priceEndpoint, {
      method: "POST", body: JSON.stringify({product_name: product.name, freq: "DAY1", adjusted: false,
        start_date: start.toISOString().slice(0, 10), end_date: end.toISOString().slice(0, 10)}),
    }).catch(() => ({}));
    const contractsRequest = context.api(
      `${contractsEndpoint}?product=${encodeURIComponent(product.name)}`
    ).catch(() => ({}));
    const [price, contracts] = await Promise.all([priceRequest, contractsRequest]);
    if (!current(context)) return;
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
        row.addEventListener("click", () => context.navigate(helpers.pathFor(
          `/products/contract/${encodeURIComponent(contractRows[index].uid || contractRows[index].contract || "")}`,
          source,
        )));
      });
      termMount.replaceChildren(table.shell);
    }
    if (window.FTPriceChart?.render && Array.isArray(price.data)) {
      FTPriceChart.render(context, chartMount, {
        ...price,
        product: price.product || product.name,
        desc: price.desc || product.desc,
      });
    } else {
      chartMount.replaceChildren(FTUI.empty(context.t("价格曲线暂不可用"), ""));
    }
  }

  function unavailableProductDetail(context, product, source, helpers) {
    const title = product.display_name || product.name || product.product_ref;
    context.setHeading(title, context.t("产品详情"));
    helpers.catalogSwitch(context, "products", source);
    context.updateActiveTab?.({title});
    const root = document.createElement("div");
    root.className = "detail-stack product-detail-page";
    root.append(helpers.sourceSummary(context, source));
    root.append(FTUI.table(
      [context.t("字段"), context.t("值")],
      [
        [context.t("产品"), title],
        [context.t("产品引用"), product.product_ref || ""],
        [context.t("状态"), context.t("不可用")],
      ],
    ).shell);
    root.append(FTUI.empty(
      context.t("当前目录无法展示该产品"),
      context.t(product.unavailable_reason || "非服务器提供，无法展示相关信息"),
    ));
    context.content.replaceChildren(root);
  }

  async function groupDetail(context, target, helpers) {
    const source = helpers.sourceOf();
    context.activeNav("products");
    const value = await helpers.load(context, source);
    if (!current(context)) return;
    const stableID = String(target || "").startsWith("product-group:")
      ? String(target).slice("product-group:".length) : "";
    let group = value.groups.find(item => item.name === target || item.id === stableID || item.group_ref === target);
    if (source === "local") {
      const payload = await context.api(`/api/client/product-groups/${encodeURIComponent(group?.group_ref || group?.id || target)}`);
      if (!current(context)) return;
      group = payload.group || group;
    } else if (source !== "local") {
      const payload = await context.api(`/api/catalog/product-groups/${encodeURIComponent(group?.group_ref || group?.name || target)}`);
      if (!current(context)) return;
      group = payload.group || group;
    }
    if (!group) throw new Error(context.t("产品组不存在或当前目录无法解析该引用"));
    context.setHeading(group.name || target, context.t("产品组详情"));
    helpers.catalogSwitch(context, "groups", source);
    context.updateActiveTab?.({title: group.name || target});
    const root = document.createElement("div"); root.className = "detail-stack product-group-detail-page";
    root.append(helpers.sourceSummary(context, source));
    root.append(FTUI.table(
      [context.t("字段"), context.t("值")],
      [
        [context.t("产品组"), group.name || ""],
        [context.t("稳定引用"), group.group_ref || group.id || ""],
        [context.t("创建者类型"), group.creator_kind === "profile" ? context.t("Profile") : context.t("用户")],
        [context.t("创建者"), group.creator_title || group.creator_ref || ""],
        [context.t("产品分类"), (group.category_bindings || []).map(item =>
          item.title_zh || item.alias || item.id).join("、")
          || (group.category_ids || []).join("、")
          || context.t("未绑定分类")],
        [context.t("是否为研究创建"), group.created_for_research ? context.t("是") : context.t("否")],
        [context.t("状态"), group.state || ""],
      ],
    ).shell);
    const research = Array.isArray(group.research_bindings)
      ? group.research_bindings : [];
    if (research.length) {
      const researchSection = document.createElement("section");
      researchSection.className = "product-group-research";
      researchSection.append(Object.assign(document.createElement("h2"), {
        textContent: context.t("研究绑定"),
      }));
      researchSection.append(FTUI.table(
        [context.t("研究"), context.t("稳定引用"), context.t("Profile")],
        research.map(item => [item.title, item.research_ref, item.profile_id || ""]),
      ).shell);
      root.append(researchSection);
    }
    const names = Array.isArray(group.product_names) ? group.product_names : [];
    const memberships = Array.isArray(group.products) ? group.products : [];
    const productRows = memberships.length
      ? memberships
      : names.map(name => ({
          product_ref: name, display_name: name, available: true,
        }));
    const productsSection = document.createElement("section"); productsSection.className = "product-group-products";
    productsSection.append(Object.assign(document.createElement("h2"), {textContent: context.t("包含的产品")}));
    if (productRows.length) {
      const table = FTUI.table(
        [context.t("产品"), context.t("说明"), context.t("可用性"), context.t("数据源")],
        productRows.map(item => [
          item.display_name || item.name || item.product_ref,
          item.desc || item.display_name || "",
          item.available === false ? context.t("不可用") : context.t("可用"),
          (item.source_ids || []).join(", "),
        ]),
      );
      [...table.body.rows].forEach((row, index) => {
        const item = productRows[index];
        row.dataset.href = "true";
        if (item.available === false) row.classList.add("is-unavailable");
        row.addEventListener("click", () => context.navigate(helpers.pathFor(
          `/products/product/${encodeURIComponent(item.product_ref || item.display_name || item.name)}`,
          source,
        )));
      });
      productsSection.append(table.shell);
    } else {
      productsSection.append(FTUI.empty(context.t("暂无产品"), ""));
    }
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

  async function referenceDetail(context, kind, targetRef, helpers) {
    context.activeNav("products");
    context.content.replaceChildren(FTUI.loading(context.t("正在解析产品引用…")));
    if (kind === "contract" || kind === "continuous-contract") {
      try {
        const priceEndpoint = helpers.sourceOf() === "local"
          ? "/api/client/product_prices" : "/api/catalog/prices";
        const payload = await context.api(priceEndpoint, {
          method: "POST",
          body: JSON.stringify({contract_uid: targetRef, freq: "DAY1", adjusted: false}),
        });
        if (!current(context)) return;
        if (payload.success !== false) {
          context.setHeading(payload.contract_name || targetRef, context.t("合约详情"));
          helpers.catalogSwitch(context, "products", helpers.sourceOf());
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
          if (window.FTPriceChart?.render && Array.isArray(payload.data)) {
            FTPriceChart.render(context, chartMount, payload);
          } else chartMount.append(FTUI.empty(context.t("价格曲线暂不可用"), ""));
          chart.append(chartMount); root.append(chart);
          context.content.replaceChildren(root); return;
        }
      } catch (_) {}
    }
    const payload = await context.api(context.servicePath(`/api/report-references/validate?kind=${encodeURIComponent(kind)}&target_ref=${encodeURIComponent(targetRef)}`));
    if (!current(context)) return;
    const reference = payload.reference || payload.data?.reference || {};
    context.setHeading(reference.label || context.t("产品详情"), context.t("产品库"));
    helpers.catalogSwitch(context, "products", helpers.sourceOf());
    context.updateActiveTab?.({title: reference.label || context.t("产品详情")});
    const root = document.createElement("div"); root.className = "detail-stack";
    root.append(FTUI.table([context.t("字段"), context.t("值")], [...FTUI.fieldRows(reference), ...FTUI.fieldRows(reference.object || {})]).shell);
    context.content.replaceChildren(root);
  }

  window.FTProductDetails = {groupDetail, productDetail, referenceDetail};
})();
