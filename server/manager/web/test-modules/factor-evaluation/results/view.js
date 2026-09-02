(() => {
  function supports(options) {
    return String(options.jobKind || "").toLowerCase() === "factor_evaluation";
  }

  function artifactOf(artifacts) {
    return (artifacts || []).find(item => (
      item.state === "active" && String(item.name || "") === "result"
    ));
  }

  async function loadResult(context, options) {
    const summary = window.FTFactorSeriesModel.build(options.resultSummary || {});
    if (summary.series.length) return summary;
    const artifact = artifactOf(options.artifacts);
    if (!artifact) throw new Error(context.t("因子序列结果未被完整保留"));
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

  function render(context, target, state) {
    const {model, options} = state;
    const customTabs = options.customAnalyses?.tabs({
      onDeleted: () => { state.activeTab = "series"; render(context, target, state); },
    }) || [];
    const header = window.FTJobResultTabs.create(context, {
      className: "factor-series-result-header",
      tabs: [{key: "series", label: "因子序列"}, ...customTabs],
      active: state.activeTab,
      onChange: async key => {
        if (key === "custom-analysis:new") {
          try {
            const analysis = await options.customAnalyses.add();
            state.activeTab = options.customAnalyses.keyFor(analysis.tab_id);
          } catch (error) {
            context.showNotice?.(error.message || String(error), true);
          }
        } else state.activeTab = key;
        render(context, target, state);
      },
    }).header;
    const content = document.createElement("div");
    content.className = "factor-series-result-content";
    const customID = options.customAnalyses?.tabIDFor(state.activeTab);
    if (customID) {
      options.customAnalyses.render(customID, content, {
        onTabsChanged: () => render(context, target, state),
        onDeleted: () => { state.activeTab = "series"; render(context, target, state); },
      });
      target.replaceChildren(header, content);
      return;
    }
    if (!model.series.length) {
      content.append(FTUI.empty(context.t("暂无因子序列"), ""));
      target.replaceChildren(header, content);
      return;
    }
    const root = document.createElement("div");
    root.className = "factor-series-viewer";
    const controls = document.createElement("div");
    controls.className = "factor-series-controls";
    const field = document.createElement("div");
    field.className = "factor-series-product-control";
    const label = document.createElement("b"); label.textContent = context.t("产品");
    let selectedProduct = window.FTFactorSeriesModel.identity(model.series[0]);
    const source = document.createElement("small");
    const chart = document.createElement("div");
    chart.className = "factor-series-chart-mount";
    const contracts = document.createElement("div");
    contracts.className = "factor-series-contracts";
    root.append(controls, chart, contracts);
    content.append(root);
    target.replaceChildren(header, content);
    const show = () => loadProduct(
      context, model, options, selectedProduct, chart, contracts, source,
    ).catch(error => {
      chart.replaceChildren(FTUI.empty(
        context.t("曲线暂不可用"), error.message || String(error),
      ));
    });
    const picker = window.FTMultiSelectFilter.create(context, {
      title: context.t("产品"), compact: true, multi: false,
      className: "factor-series-product-filter",
      items: model.series.map(item => ({
        value: window.FTFactorSeriesModel.identity(item),
        label: window.FTFactorSeriesModel.label(item),
        description: context.t("切换要展示的产品价格、因子序列与期限结构"),
      })),
      selected: [selectedProduct],
      searchPlaceholder: context.t("搜索产品…"),
      onChange: async values => {
        selectedProduct = values[0] || selectedProduct;
        await show();
      },
    });
    field.append(label, picker.element);
    controls.append(field, source);
    show();
  }

  async function loadProduct(context, model, options, product, chart, tableMount, note) {
    const item = model.series.find(value => (
      window.FTFactorSeriesModel.identity(value) === product
    )) || model.series[0];
    chart.replaceChildren(FTUI.loading(context.t("正在读取价格与因子曲线…")));
    tableMount.replaceChildren();
    note.textContent = "";
    const request = window.FTFactorSeriesModel.priceRequest(
      options.configuration, product, model.factor.freq,
    );
    const [priceResult, contractResult] = await Promise.allSettled([
      window.FTMarketData.prices(context, request),
      window.FTMarketData.contracts(context, product),
    ]);
    const price = priceResult.status === "fulfilled" ? priceResult.value : {
      payload: {data: []}, source: "",
    };
    const contractPayload = contractResult.status === "fulfilled"
      ? contractResult.value.payload : {};
    const rows = Array.isArray(contractPayload.contracts)
      ? contractPayload.contracts : [];
    try {
      const chartInstance = window.FTFactorSeriesChart.mount(context, chart, {
        product,
        factorLabel: model.factor.alias || model.factor.name || context.t("因子"),
        factorSeries: item,
        price: price.payload,
        contracts: rows,
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

  window.FTFactorSeriesResults = Object.freeze({artifactOf, section, supports});
})();
