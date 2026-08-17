(() => {
  function current(context) {
    return context.isRouteCurrent?.() !== false;
  }

  function endpoint(source) {
    return source === "local"
      ? "/api/client/product_prices" : "/api/catalog/prices";
  }

  function sourceEntries(value) {
    const seen = new Set();
    return (Array.isArray(value) ? value : [])
      .map(item => typeof item === "string"
        ? {alias: item, freq: ""} : item)
      .filter(item => item && String(item.alias || "").trim())
      .map(item => ({
        alias: String(item.alias).trim(),
        freq: String(item.freq || "").trim(),
      }))
      .filter(item => {
        if (seen.has(item.alias)) return false;
        seen.add(item.alias);
        return true;
      });
  }

  function sourceLabel(context, item) {
    return [item.alias, item.freq].filter(Boolean).join(" · ")
      || context.t("未命名数据源");
  }

  function option(select, value, label) {
    const item = document.createElement("option");
    item.value = value;
    item.textContent = label;
    select.append(item);
  }

  function priceStateFromLocation() {
    const query = new URLSearchParams(location.search);
    return {
      // Product catalog routes use data_source for a catalog provider ID
      // (for example, "Local").  The price API expects a concrete source
      // alias whose frequency is already encoded (for example,
      // "LocalCNFuturesDAY1"), so the panel starts with automatic selection.
      dataSource: "",
      adjusted: ["1", "true", "yes"].includes(
        String(query.get("adjusted") || "").toLowerCase(),
      ),
    };
  }

  function adjustmentLabel(context, method) {
    switch (String(method || "raw")) {
      case "continuous_futures_roll":
        return context.t("连续合约换月平滑复权");
      case "adjusted_source":
        return context.t("数据源复权");
      default:
        return context.t("未复权");
    }
  }

  function metadata(context, payload) {
    const rows = [
      [context.t("数据源"), payload.data_source || context.t("自动")],
      [context.t("数据频率"), payload.freq || context.t("暂无频率")],
      [context.t("价格序列"), payload.adjusted
        ? context.t("复权价格") : context.t("原始价格")],
      [context.t("复权方式"), adjustmentLabel(context, payload.adjustment_method)],
      [context.t("数据点"), String(payload.count || (payload.data || []).length)],
    ];
    if (payload.adjustment_formula) {
      rows.splice(4, 0, [context.t("复权公式"), payload.adjustment_formula]);
    }
    return FTUI.table([context.t("项目"), context.t("值")], rows).shell;
  }

  function renderControls(context, state, options) {
    const controls = document.createElement("div");
    controls.className = "product-price-controls";

    const sourceField = document.createElement("label");
    sourceField.className = "product-price-control";
    sourceField.append(Object.assign(document.createElement("span"), {
      textContent: context.t("数据源"),
    }));
    const sourceSelect = document.createElement("select");
    sourceSelect.className = "product-price-source-select";
    sourceSelect.setAttribute("aria-label", context.t("数据源"));
    sourceField.append(sourceSelect);
    controls.append(sourceField);

    const adjustedField = document.createElement("label");
    adjustedField.className = "product-price-control product-price-adjusted";
    adjustedField.append(Object.assign(document.createElement("span"), {
      textContent: context.t("价格序列"),
    }));
    const adjustedSelect = document.createElement("select");
    adjustedSelect.className = "product-price-adjusted-select";
    adjustedSelect.setAttribute("aria-label", context.t("价格序列"));
    option(adjustedSelect, "raw", context.t("原始价格"));
    option(adjustedSelect, "adjusted", context.t("复权价格"));
    adjustedField.append(adjustedSelect);
    controls.append(adjustedField);

    const frequency = document.createElement("span");
    frequency.className = "product-price-frequency";
    frequency.append(Object.assign(document.createElement("b"), {
      textContent: `${context.t("数据频率")}：`,
    }));
    const frequencyValue = document.createElement("span");
    frequency.append(frequencyValue);
    controls.append(frequency);

    function apply(payload) {
      const entries = sourceEntries(payload.available_sources);
      const actual = String(payload.data_source || state.dataSource || "").trim();
      sourceSelect.replaceChildren();
      option(sourceSelect, "", context.t("自动"));
      entries.forEach(item => option(
        sourceSelect, item.alias, sourceLabel(context, item),
      ));
      state.dataSource = actual;
      sourceSelect.value = entries.some(item => item.alias === actual) ? actual : "";
      state.adjusted = Boolean(payload.supports_adjusted && payload.adjusted);
      adjustedSelect.value = state.adjusted ? "adjusted" : "raw";
      adjustedField.hidden = !payload.supports_adjusted;
      frequencyValue.textContent = payload.freq || entries.find(
        item => item.alias === actual,
      )?.freq || context.t("暂无频率");
    }

    function setBusy(busy) {
      sourceSelect.disabled = busy || sourceSelect.options.length <= 1;
      adjustedSelect.disabled = busy;
    }

    sourceSelect.addEventListener("change", () => {
      state.dataSource = sourceSelect.value;
      options.reload();
    });
    adjustedSelect.addEventListener("change", () => {
      state.adjusted = adjustedSelect.value === "adjusted";
      options.reload();
    });

    apply({
      available_sources: [],
      data_source: state.dataSource,
      adjusted: state.adjusted,
      supports_adjusted: false,
    });
    return {controls, apply, setBusy};
  }

  async function render(context, mount, options = {}) {
    const source = options.source || "server";
    const product = options.product || {};
    const state = {
      ...priceStateFromLocation(),
      ...(options.dataSource ? {dataSource: options.dataSource} : {}),
      ...(options.adjusted !== undefined ? {adjusted: Boolean(options.adjusted)} : {}),
    };
    const root = document.createElement("section");
    root.className = "product-price-panel";
    root.append(Object.assign(document.createElement("h2"), {
      textContent: context.t("价格曲线"),
    }));
    const metadataMount = document.createElement("div");
    metadataMount.className = "product-price-metadata";
    const chartMount = document.createElement("div");
    chartMount.className = "product-price-chart-mount";
    const controls = renderControls(context, state, {
      reload: () => load(),
    });
    root.append(controls.controls, metadataMount, chartMount);
    mount.replaceChildren(root);

    let requestID = 0;
    async function load() {
      const requestIDForLoad = ++requestID;
      controls.setBusy(true);
      metadataMount.replaceChildren(FTUI.loading(context.t("正在读取数据能力…")));
      chartMount.replaceChildren(FTUI.loading(context.t("正在读取价格曲线…")));
      const payload = {
        product_name: product.name,
        adjusted: Boolean(state.adjusted),
        start_date: options.startDate || null,
        end_date: options.endDate || null,
      };
      if (state.dataSource) payload.data_source = state.dataSource;
      try {
        const value = await context.api(endpoint(source), {
          method: "POST",
          body: JSON.stringify(payload),
        });
        if (!current(context) || requestIDForLoad !== requestID) return;
        if (value?.success === false) throw new Error(value.error || "request failed");
        controls.apply(value || {});
        metadataMount.replaceChildren(metadata(context, value || {}));
        if (window.FTPriceChart?.render && Array.isArray(value?.data)) {
          FTPriceChart.render(context, chartMount, {
            ...value,
            product: value.product || product.name,
            desc: value.desc || product.desc,
          });
        } else {
          chartMount.replaceChildren(FTUI.empty(
            context.t("价格曲线暂不可用"), context.t("暂无可绘制数据"),
          ));
        }
      } catch (error) {
        if (!current(context) || requestIDForLoad !== requestID) return;
        metadataMount.replaceChildren(FTUI.empty(
          context.t("数据能力读取失败"), error.message || "",
        ));
        chartMount.replaceChildren(FTUI.empty(
          context.t("价格曲线读取失败"), error.message || "",
        ));
      } finally {
        if (requestIDForLoad === requestID) controls.setBusy(false);
      }
    }

    await load();
    return root;
  }

  window.FTProductPricePanel = Object.freeze({render, sourceEntries});
})();
