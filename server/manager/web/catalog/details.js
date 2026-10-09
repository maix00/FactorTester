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
    const query = new URLSearchParams(location.search);
    const selectedContractUID = String(query.get("contract") || "").trim();
    const selectedContractName = String(query.get("contract_label") || "").trim();
    const selectedContractHasData = String(query.get("contract_has_data") || "");
    context.activeNav("products");
    // Product details need the product directory only. Product groups are a
    // secondary lookup for missing product refs and must not delay this route.
    const value = await helpers.load(context, source, {includeGroups: false});
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
    if (!product && selectedContractUID && selectedContractUID === rawTarget) {
      await contractDetail(context, rawTarget, {
        source, query, selectedContractName, selectedContractHasData, helpers,
      });
      return;
    }
    if (!product) {
      // This is already the product route.  Do not fall back to the generic
      // report-reference resolver: a missing catalog mapping should be
      // immediate and explicit rather than showing an unbounded resolving UI.
      unavailableProductDetail(context, {
        display_name: pathLeaf || rawTarget,
        product_ref: rawTarget,
      }, source, helpers);
      // Only a product miss needs group summaries to explain whether the
      // missing reference is an unavailable group member. Keep the fallback
      // visible while that secondary directory request runs, and protect a
      // later navigation from a stale response.
      helpers.load(context, source, {
        includeProducts: false, includeGroups: true,
      }).then(groupValue => {
        if (!current(context)) return;
        const membership = groupValue.groups.flatMap(group =>
          Array.isArray(group.products) ? group.products : []
        ).find(item => {
          const ref = String(item.product_ref || item.product_name || "");
          return [ref, ref.replace(/^product:/, ""), item.display_name, item.name]
            .filter(Boolean).includes(rawTarget)
            || ref.split("/_products/").pop() === pathLeaf;
        });
        if (membership?.available === false) {
          unavailableProductDetail(context, membership, source, helpers);
        }
      }).catch(() => {});
      return;
    }
    context.setHeading(product.name || product.code, product.desc || context.t("产品详情"));
    helpers.catalogSwitch(context, "products", source);
    context.updateActiveTab?.({title: product.name || product.code});
    context.content.replaceChildren(FTUI.loading(context.t("正在读取产品资料…")));
    const fieldsPayload = await context.api(source === "local"
      ? `/api/client/product_fields?name=${encodeURIComponent(product.name)}`
      : `/api/product-library/product-fields?name=${encodeURIComponent(product.name)}`);
    if (!current(context)) return;
    const root = document.createElement("div"); root.className = "detail-stack product-detail-page";
    root.append(helpers.sourceSummary(context, source));
    root.append(FTUI.table(
      [context.t("字段"), context.t("说明"), context.t("当前值")],
      normalizeFields(fieldsPayload.fields).map(item => [item.name || item.key, item.description || item.desc, item.value]),
    ).shell);
    const priceMount = document.createElement("div");
    priceMount.className = "product-price-panel-mount";
    root.append(priceMount);
    const term = document.createElement("section"); term.className = "product-term-structure";
    term.append(Object.assign(document.createElement("h2"), {textContent: context.t("期限结构")}));
    const termMount = document.createElement("div"); termMount.append(FTUI.loading(context.t("正在读取合约列表…")));
    term.append(termMount); root.append(term);
    context.content.replaceChildren(root);
    const end = new Date(); const start = new Date(end); start.setFullYear(start.getFullYear() - 1);
    const contractsEndpoint = source === "local"
      ? "/api/client/product_contracts" : "/api/product-library/contracts";
    let pricePanelPromise;
    if (selectedContractUID && selectedContractHasData === "0") {
      priceMount.replaceChildren(FTUI.empty(
        context.t("无此产品信息"), context.t("该合约没有可用的数据"),
      ));
      pricePanelPromise = Promise.resolve();
    } else {
      pricePanelPromise = window.FTProductPricePanel?.render
        ? window.FTProductPricePanel.render(context, priceMount, {
            product, source, contractUID: selectedContractUID,
            contractName: selectedContractName,
            startDate: selectedContractUID
              ? query.get("contract_start") || ""
              : start.toISOString().slice(0, 10),
            endDate: selectedContractUID
              ? query.get("contract_end") || ""
              : end.toISOString().slice(0, 10),
          })
        : Promise.resolve();
    }
    const contractsRequest = context.api(
      `${contractsEndpoint}?product=${encodeURIComponent(product.name)}`
    ).catch(() => ({}));
    const [, contracts] = await Promise.all([pricePanelPromise, contractsRequest]);
    if (!current(context)) return;
    const contractRows = Array.isArray(contracts.contracts)
      ? [...contracts.contracts].reverse()
      : [];
    if (!contracts.supports_term_structure || !contractRows.length) {
      termMount.replaceChildren(FTUI.empty(context.t("暂无期限结构"), context.t("该产品没有可用的连续合约列表")));
    } else {
      const table = FTUI.table(
        [
          context.t("合约"), context.t("开始"), context.t("结束"),
          context.t("前复权乘法"), context.t("前复权加法"),
          context.t("后复权乘法"), context.t("后复权加法"),
          context.t("换月比值"), context.t("数据"),
        ],
        contractRows.map(item => [
          item.contract || item.uid,
          item.start || "",
          item.end || "",
          item.forward_adjustment_mul ?? context.t("—"),
          item.forward_adjustment_add ?? context.t("—"),
          item.backward_adjustment_mul ?? context.t("—"),
          item.backward_adjustment_add ?? context.t("—"),
          item.adjustment_ratio ?? context.t("—"),
          item.has_data ? context.t("可用") : context.t("无数据"),
        ]),
      );
      [...table.body.rows].forEach((row, index) => {
        row.dataset.href = "true";
        row.addEventListener("click", () => {
          const item = contractRows[index];
          const target = contractRows[index].uid || contractRows[index].contract || "";
          const query = new URLSearchParams({
            product: product.name || "",
            contract: target,
            contract_label: item.contract || item.uid || "",
            contract_has_data: item.has_data ? "1" : "0",
            contract_start: item.start || item.start_date || "",
            contract_end: item.end || item.end_date || "",
          });
          context.navigate(helpers.pathFor(
            `/products/product/${encodeURIComponent(target)}?${query}`,
            source,
          ));
        });
      });
      termMount.replaceChildren(table.shell);
    }
  }

  async function contractDetail(context, target, options) {
    const {
      source, query, selectedContractName, selectedContractHasData, helpers,
    } = options;
    const contractUID = String(target || "").trim();
    const title = selectedContractName || contractUID;
    const fieldsEndpoint = source === "local"
      ? "/api/client/product_fields" : "/api/product-library/product-fields";
    let fieldsPayload;
    try {
      fieldsPayload = await context.api(
        `${fieldsEndpoint}?name=${encodeURIComponent(contractUID)}`,
      );
    } catch (error) {
      if (!current(context)) return;
      unavailableProductDetail(context, {
        display_name: title,
        product_ref: contractUID,
        unavailable_reason: error.message || "产品字段读取失败",
      }, source, helpers);
      return;
    }
    if (!current(context)) return;
    const contract = {
      name: fieldsPayload.name || contractUID,
      desc: fieldsPayload.desc || title,
      product_type: "contract",
    };
    context.setHeading(title, context.t("产品详情"));
    helpers.catalogSwitch(context, "products", source);
    context.updateActiveTab?.({title});
    context.content.replaceChildren(FTUI.loading(context.t("正在读取产品资料…")));

    const root = document.createElement("div");
    root.className = "detail-stack product-detail-page";
    root.append(helpers.sourceSummary(context, source));
    root.append(FTUI.table(
      [context.t("字段"), context.t("说明"), context.t("当前值")],
      normalizeFields(fieldsPayload.fields).map(item => [
        item.name || item.key, item.description || item.desc, item.value,
      ]),
    ).shell);
    const priceMount = document.createElement("div");
    priceMount.className = "product-price-panel-mount";
    root.append(priceMount);
    const term = document.createElement("section");
    term.className = "product-term-structure";
    term.append(Object.assign(document.createElement("h2"), {
      textContent: context.t("期限结构"),
    }));
    term.append(FTUI.empty(
      context.t("暂无期限结构"),
      context.t("该产品没有可用的连续合约列表"),
    ));
    root.append(term);
    context.content.replaceChildren(root);

    if (selectedContractHasData === "0") {
      priceMount.replaceChildren(FTUI.empty(
        context.t("无此产品信息"), context.t("该合约没有可用的数据"),
      ));
      return;
    }
    if (window.FTProductPricePanel?.render) {
      await window.FTProductPricePanel.render(context, priceMount, {
        product: contract,
        source,
        contractUID,
        contractName: title,
        startDate: query.get("contract_start") || "",
        endDate: query.get("contract_end") || "",
      });
    } else {
      priceMount.replaceChildren(FTUI.empty(
        context.t("价格曲线暂不可用"), context.t("价格面板尚未加载"),
      ));
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

  function unavailableContractDetail(context, targetRef, helpers, displayTitle = targetRef) {
    const source = helpers.sourceOf();
    const title = String(displayTitle || context.t("合约详情"));
    context.setHeading(title, context.t("合约详情"));
    helpers.catalogSwitch(context, "products", source);
    context.updateActiveTab?.({title});
    const root = document.createElement("div");
    root.className = "detail-stack product-detail-page";
    root.append(helpers.sourceSummary(context, source));
    root.append(FTUI.table(
      [context.t("字段"), context.t("值")],
      [
        [context.t("合约"), targetRef || title],
        [context.t("状态"), context.t("无此产品信息")],
      ],
    ).shell);
    root.append(FTUI.empty(
      context.t("无此产品信息"),
      context.t("该合约没有可用的数据"),
    ));
    context.content.replaceChildren(root);
  }

  async function referenceDetail(context, kind, targetRef, helpers) {
    context.activeNav("products");
    if (kind === "contract" || kind === "continuous-contract") {
      const query = new URLSearchParams(location.search);
      const title = query.get("label") || targetRef;
      if (query.get("has_data") === "0") {
        unavailableContractDetail(context, targetRef, helpers, title);
        return;
      }
      context.setHeading(title, context.t("合约详情"));
      helpers.catalogSwitch(context, "products", helpers.sourceOf());
      context.updateActiveTab?.({title});
      const root = document.createElement("div");
      root.className = "detail-stack product-detail-page";
      root.append(helpers.sourceSummary(context, helpers.sourceOf()));
      const priceMount = document.createElement("div");
      priceMount.className = "product-price-panel-mount";
      root.append(priceMount);
      context.content.replaceChildren(root);
      if (window.FTProductPricePanel?.render) {
        await FTProductPricePanel.render(context, priceMount, {
          source: helpers.sourceOf(),
          contractUID: targetRef,
          contractName: title,
          startDate: query.get("start_date") || "",
          endDate: query.get("end_date") || "",
          dataSource: query.get("data_source") || "",
        });
      } else {
        priceMount.replaceChildren(FTUI.empty(
          context.t("价格曲线暂不可用"), context.t("价格面板尚未加载"),
        ));
      }
      return;
    }
    context.content.replaceChildren(FTUI.loading(context.t("正在解析产品引用…")));
    const payload = await context.api(`/api/report-references/validate?kind=${encodeURIComponent(kind)}&target_ref=${encodeURIComponent(targetRef)}`);
    if (!current(context)) return;
    const reference = payload.reference || payload.data?.reference || {};
    context.setHeading(reference.label || context.t("产品详情"), context.t("产品库"));
    helpers.catalogSwitch(context, "products", helpers.sourceOf());
    context.updateActiveTab?.({title: reference.label || context.t("产品详情")});
    const root = document.createElement("div"); root.className = "detail-stack";
    root.append(FTUI.table([context.t("字段"), context.t("值")], [...FTUI.fieldRows(reference), ...FTUI.fieldRows(reference.object || {})]).shell);
    context.content.replaceChildren(root);
  }

  window.FTProductDetails = {productDetail, referenceDetail};
})();
