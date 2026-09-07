(() => {
  function supports(options) {
    const kind = String(options.jobKind || "").toLowerCase();
    return kind === "factor_evaluation" || (options.resultDeclarations || []).some(
      item => item.name === "factor_series",
    ) || Boolean(artifactOf(options.artifacts));
  }

  function artifactOf(artifacts) {
    return (artifacts || []).find(item => (
      item.state === "active" && ["factor_series_data", "result"].includes(
        String(item.name || ""),
      )
    ));
  }

  function supportsPriceAdjustment(contractPayload) {
    return contractPayload?.supports_term_structure === true;
  }

  async function loadResult(context, options) {
    const summary = window.FTFactorSeriesModel.build(options.resultSummary || {});
    if (summary.series.length) return summary;
    const artifact = artifactOf(options.artifacts);
    if (!artifact) throw new Error(context.t("未计算"));
    const path = `/api/jobs/${encodeURIComponent(options.jobID)}`
      + `/artifacts/${encodeURIComponent(artifact.name)}${options.artifactQuery || ""}`;
    const response = await FTJobArtifacts.fetch(context, path);
    return window.FTFactorSeriesModel.build(JSON.parse(await response.text()));
  }

  function section(context, options) {
    if (!supports(options)) return null;
    const root = document.createElement("section");
    root.className = "job-section factor-series-results";
    const heading = document.createElement("h2");
    heading.textContent = context.t("因子序列结果");
    const target = document.createElement("div");
    target.append(FTUI.loading(context.t("正在读取因子序列…")));
    root.append(heading, target);
    queueMicrotask(async () => {
      try {
        const model = await loadResult(context, options);
        render(context, target, {
          model, options,
          activeTab: options.customAnalyses?.state?.requestedKey || "series",
        });
      } catch (error) {
        target.replaceChildren(FTUI.empty(context.t("因子序列暂不可用"), error.message));
      }
    });
    return root;
  }

  function embedded(context, options) {
    const target = document.createElement("div");
    target.className = "factor-series-result-content";
    target.append(FTUI.loading(context.t("正在读取因子序列…")));
    queueMicrotask(async () => {
      try {
        const model = await loadResult(context, options);
        renderSeriesContent(context, target, {model, options});
      } catch (error) {
        target.replaceChildren(FTJobResultTabs.missingOutput(context, {
          message: error?.message || "本次运行没有生成因子序列",
        }));
      }
    });
    return target;
  }

  function render(context, target, state) {
    const {model, options} = state;
    const customTabs = options.customAnalyses?.tabs({
      onDeleted: () => { state.activeTab = "series"; render(context, target, state); },
    }) || [];
    const tabs = FTJobResultTabs.compose({
      tabs: [{key: "series", label: "因子序列"}],
      resultSummary: options.resultSummary, customTabs,
    });
    state.activeTab = FTJobResultTabs.active(tabs, state.activeTab, "series");
    const header = window.FTJobResultTabs.create(context, {
      className: "factor-series-result-header",
      tabs,
      active: state.activeTab,
      onChange: key => void FTJobResultTabs.activate(context, key, {
        customAnalyses: options.customAnalyses,
        onActive: next => { state.activeTab = next; render(context, target, state); },
      }),
    }).header;
    const content = document.createElement("div");
    content.className = "factor-series-result-content";
    const customID = options.customAnalyses?.tabIDFor(state.activeTab);
    const standard = FTJobResultTabs.standardContent(
      context, state.activeTab, options.resultSummary,
    );
    if (standard) {
      content.append(standard);
      target.replaceChildren(header, content);
      return;
    }
    if (customID) {
      options.customAnalyses.render(customID, content, {
        onTabsChanged: () => render(context, target, state),
        onDeleted: () => { state.activeTab = "series"; render(context, target, state); },
      });
      target.replaceChildren(header, content);
      return;
    }
    renderSeriesContent(context, content, state);
    target.replaceChildren(header, content);
  }

  function renderSeriesContent(context, target, state) {
    const {model, options} = state;
    target.replaceChildren();
    if (!model.series.length) {
      target.append(FTUI.empty(context.t("暂无因子序列"), ""));
      return;
    }
    const root = document.createElement("div");
    root.className = "factor-series-viewer";
    const controls = document.createElement("div");
    controls.className = "factor-series-controls";
    let selectedFactor = state.selectedFactor
      || window.FTFactorSeriesModel.factorIdentity(model.series[0], model);
    let selectedProduct = state.selectedProduct
      || window.FTFactorSeriesModel.identity(model.series.find(item => (
        window.FTFactorSeriesModel.factorIdentity(item, model) === selectedFactor
      )) || model.series[0]);
    const source = document.createElement("small");
    const adjustmentField = document.createElement("div");
    adjustmentField.className = "factor-series-adjustment-control";
    adjustmentField.hidden = true;
    const initialRequest = window.FTFactorSeriesModel.priceRequest(
      options.configuration, selectedProduct, model.factor.freq,
    );
    const adjustmentState = {adjusted: initialRequest.adjusted, generation: 0};
    const chart = document.createElement("div");
    chart.className = "factor-series-chart-mount";
    const contracts = document.createElement("div");
    contracts.className = "factor-series-contracts";
    root.append(controls, chart, contracts);
    target.append(root);
    const show = () => loadProduct(
      context, model, options, selectedProduct, selectedFactor, chart, contracts, source,
      adjustmentField, adjustmentState,
    ).catch(error => {
      chart.replaceChildren(FTUI.empty(
        context.t("曲线暂不可用"), error.message || String(error),
      ));
    });
    const factorItems = [...new Map(model.series.map(item => [
      window.FTFactorSeriesModel.factorIdentity(item, model),
      {value: window.FTFactorSeriesModel.factorIdentity(item, model),
        label: window.FTFactorSeriesModel.factorLabel(item, model)},
    ])).values()];
    const productItems = () => [...new Map(model.series
      .filter(item => window.FTFactorSeriesModel.factorIdentity(item, model) === selectedFactor)
      .map(item => [window.FTFactorSeriesModel.identity(item), {
        value: window.FTFactorSeriesModel.identity(item),
        label: window.FTFactorSeriesModel.label(item),
      }])).values()];
    const factorPicker = window.FTMultiSelectFilter.create(context, {
      title: context.t("因子"), compact: true, multi: false,
      items: factorItems, selected: [selectedFactor],
      searchPlaceholder: context.t("搜索因子…"),
      onChange: async values => {
        selectedFactor = values[0] || selectedFactor;
        selectedProduct = productItems()[0]?.value || selectedProduct;
        state.selectedFactor = selectedFactor; state.selectedProduct = selectedProduct;
        renderSeriesContent(context, target, state);
      },
    });
    const picker = window.FTMultiSelectFilter.create(context, {
      title: context.t("产品"), compact: true, multi: false,
      className: "factor-series-product-filter",
      items: productItems().map(item => ({
        ...item,
        description: context.t("切换要展示的产品价格、因子序列与期限结构"),
      })),
      selected: [selectedProduct],
      searchPlaceholder: context.t("搜索产品…"),
      onChange: async values => {
        selectedProduct = values[0] || selectedProduct;
        state.selectedProduct = selectedProduct;
        await show();
      },
    });
    const adjustmentPicker = window.FTMultiSelectFilter.create(context, {
      title: context.t("复权方式"), compact: true, multi: false,
      className: "factor-series-adjustment-filter",
      items: [
        {value: "raw", label: context.t("原始价格")},
        {value: "adjusted", label: context.t("复权价格")},
      ],
      selected: [adjustmentState.adjusted ? "adjusted" : "raw"],
      onChange: async values => {
        adjustmentState.adjusted = values[0] === "adjusted";
        await show();
      },
    });
    adjustmentField.append(adjustmentPicker.element);
    const panel = FTJobResultTabs.filterPanel(context, {
      title: "筛选",
      rows: [
        ...(factorItems.length > 1 ? [{label: "因子", element: factorPicker.element}] : []),
        {label: "产品", element: picker.element},
        {label: "复权方式", element: adjustmentField},
      ],
    });
    controls.append(panel.element, source);
    show();
  }

  async function loadProduct(
    context, model, options, product, factor, chart, tableMount, note,
    adjustmentField, adjustmentState,
  ) {
    const generation = ++adjustmentState.generation;
    window.FTFactorSeriesChart.dispose(chart);
    const item = model.series.find(value => (
      window.FTFactorSeriesModel.identity(value) === product
      && window.FTFactorSeriesModel.factorIdentity(value, model) === factor
    )) || model.series[0];
    chart.replaceChildren(FTUI.loading(context.t("正在读取价格与因子曲线…")));
    tableMount.replaceChildren();
    note.textContent = "";
    const request = window.FTFactorSeriesModel.priceRequest(
      options.configuration, product, model.factor.freq,
    );
    request.adjusted = Boolean(adjustmentState.adjusted);
    const [priceResult, contractResult] = await Promise.allSettled([
      window.FTMarketData.prices(context, request),
      window.FTMarketData.contracts(context, product),
    ]);
    if (generation !== adjustmentState.generation) return;
    const price = priceResult.status === "fulfilled" ? priceResult.value : {
      payload: {data: []}, source: "",
    };
    const contractPayload = contractResult.status === "fulfilled"
      ? contractResult.value.payload : {};
    const rows = Array.isArray(contractPayload.contracts)
      ? contractPayload.contracts : [];
    adjustmentField.hidden = !supportsPriceAdjustment(contractPayload);
    try {
      const chartInstance = window.FTFactorSeriesChart.mount(context, chart, {
        product,
        factorLabel: window.FTFactorSeriesModel.factorLabel(item, model),
        factorSeries: item,
        price: price.payload,
        contracts: rows,
      }, {
        loadingText: context.t("正在读取当前时间范围…"),
        rangeOverscanBeforeMs: window.FTMarketData.rangeContextMs(request.freq),
        loadRange: async (minimum, maximum, range = {}) => {
          const ranged = window.FTMarketData.rangeRequest(
            request, minimum, maximum, range.maxPoints,
          );
          const result = await window.FTMarketData.prices(context, ranged, price.source);
          return {
            ...result.payload,
            __ftRange: {
              minimum: range.visibleMinimum ?? minimum,
              maximum: range.visibleMaximum ?? maximum,
            },
          };
        },
      });
      note.textContent = price.source
        ? `${context.t("行情来源")}：${context.t(price.source === "local" ? "本地" : "服务器")}`
        : context.t("价格不可用，仅显示因子序列");
      renderContracts(context, tableMount, rows, chartInstance);
    } catch (error) {
      chart.replaceChildren(FTUI.empty(context.t("曲线暂不可用"), error.message));
    }
  }

  function renderContracts(context, target, rows, chart) {
    if (!rows.length) {
      target.replaceChildren(FTUI.empty(context.t("暂无期限结构"), ""));
      return;
    }
    const title = document.createElement("h3"); title.textContent = context.t("期限结构列表");
    const view = FTUI.table(
      [context.t("合约"), context.t("开始"), context.t("结束"), context.t("数据")],
      rows.map(item => [
        item.contract || item.uid, item.start || item.start_date || "",
        item.end || item.end_date || "", item.has_data === false ? context.t("无数据") : context.t("可用"),
      ]),
    );
    [...view.body.rows].forEach((row, index) => {
      row.dataset.href = "true";
      row.addEventListener("click", () => {
        const item = rows[index];
        const from = window.FTPriceChart.timestampOf(item.start || item.start_date);
        const to = window.FTPriceChart.timestampOf(item.end || item.end_date);
        if (Number.isFinite(from) && Number.isFinite(to)) chart?.xAxis?.[0]?.setExtremes(from, to);
      });
    });
    target.replaceChildren(title, view.shell);
  }

  window.FTFactorSeriesResults = Object.freeze({
    artifactOf, embedded, section, supports, supportsPriceAdjustment,
  });
})();
