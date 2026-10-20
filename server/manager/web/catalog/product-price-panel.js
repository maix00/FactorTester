(() => {
  function current(context) {
    return context.isRouteCurrent?.() !== false;
  }

  function endpoint(source) {
    return source === "local"
      ? "/api/client/product_prices" : "/api/market-data/prices";
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
    const sourcePicker = FTMultiSelectFilter.create(context, {
      title: context.t("数据源"), multi: false, compact: true,
      className: "product-price-source-filter", items: [], selected: [""],
      onChange: values => {
        state.dataSource = values[0] || "";
        state.sourceFreq = state.sourceFreqByAlias?.[state.dataSource] || "";
        options.reload();
      },
    });
    const adjustedPicker = FTMultiSelectFilter.create(context, {
      title: context.t("价格序列"), multi: false, compact: true,
      className: "product-price-adjusted-filter",
      items: [
        {value: "raw", label: context.t("原始价格")},
        {value: "adjusted", label: context.t("复权价格")},
      ],
      selected: [state.adjusted ? "adjusted" : "raw"],
      onChange: values => {
        state.adjusted = values[0] === "adjusted";
        options.reload();
      },
    });
    controls.append(sourcePicker.element, adjustedPicker.element);

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
      state.sourceFreqByAlias = Object.fromEntries(entries.map(item => [item.alias, item.freq]));
      const actual = String(payload.data_source || state.dataSource || "").trim();
      sourcePicker.setItems([
        {value: "", label: context.t("自动选择"), exclusive: true},
        ...entries.map(item => ({value: item.alias, label: sourceLabel(context, item)})),
      ]);
      state.dataSource = actual;
      sourcePicker.setValues([entries.some(item => item.alias === actual) ? actual : ""]);
      state.sourceFreq = entries.find(item => item.alias === actual)?.freq || payload.freq || "";
      state.adjusted = Boolean(payload.supports_adjusted && payload.adjusted);
      adjustedPicker.setValues([state.adjusted ? "adjusted" : "raw"]);
      adjustedPicker.element.hidden = !payload.supports_adjusted;
      frequencyValue.textContent = payload.freq || entries.find(
        item => item.alias === actual,
      )?.freq || context.t("暂无频率");
    }

    function setBusy(busy) {
      sourcePicker.setStatus({loading: busy});
      adjustedPicker.setStatus({loading: busy});
    }

    apply({
      available_sources: [],
      data_source: state.dataSource,
      adjusted: state.adjusted,
      supports_adjusted: false,
    });
    return {controls, apply, setBusy, sourcePicker, adjustedPicker};
  }

  async function render(context, mount, options = {}) {
    const source = options.source || "server";
    const product = options.product || {};
    const contractUID = String(options.contractUID || "").trim();
    const targetName = contractUID || String(product.name || "").trim();
    const state = {
      ...priceStateFromLocation(),
      sourceFreq: contractUID ? "MIN1" : "",
      ...(options.dataSource ? {dataSource: options.dataSource} : {}),
      ...(options.adjusted !== undefined ? {adjusted: Boolean(options.adjusted)} : {}),
    };
    const root = document.createElement("section");
    root.className = "product-price-panel";
    const heading = document.createElement("div");
    heading.className = "product-price-heading";
    heading.append(Object.assign(document.createElement("h2"), {
      textContent: context.t("价格曲线"),
    }));
    let metadataPayload = null;
    const information = FTUI.iconButton(context, "doc.text.magnifyingglass",
      "数据源信息", () => {
        if (!metadataPayload) return;
        const dialog = FTUI.dialogRoot(context);
        dialog.className = "product-price-info-dialog";
        const card = document.createElement("form");
        card.method = "dialog";
        card.className = "dialog-card wide product-price-info-card";
        const close = document.createElement("button");
        close.type = "submit";
        close.className = "dialog-close";
        close.setAttribute("aria-label", context.t("关闭"));
        close.textContent = "×";
        card.append(close, Object.assign(document.createElement("h2"), {
          textContent: context.t("数据源信息"),
        }), metadata(context, metadataPayload));
        dialog.append(card);
        dialog.addEventListener("close", () => dialog.remove(), {once: true});
        document.body.append(dialog);
        dialog.showModal();
      });
    information.disabled = true;
    heading.append(information);
    const fit = FTUI.iconButton(context, "arrow.up.left.and.arrow.down.right",
      "显示全部价格", () => disposePriceChart?.fitContent?.());
    heading.append(fit);
    root.append(heading);
    const chartMount = document.createElement("div");
    chartMount.className = "product-price-chart-mount";
    const controls = renderControls(context, state, {
      reload: () => load(),
    });
    root.append(controls.controls, chartMount);
    mount.replaceChildren(root);

    let requestID = 0;
    let disposePriceChart = null;
    let pendingFocus = null;
    root.focusRange = (start, end) => {
      const minimum = Date.parse(start);
      const maximum = Date.parse(end);
      if (!Number.isFinite(minimum) || !Number.isFinite(maximum)) return;
      pendingFocus = [minimum, maximum + 24 * 60 * 60 * 1000];
      disposePriceChart?.focusRange?.(...pendingFocus);
    };
    let removalObserver = null;
    if (window.MutationObserver) {
      removalObserver = new MutationObserver(() => {
        if (root.isConnected) return;
        requestID += 1;
        disposePriceChart?.();
        disposePriceChart = null;
        removalObserver.disconnect();
      });
      removalObserver.observe(document.body, {childList: true, subtree: true});
    }
    function applyBound(payload, prefix, value) {
      if (!Number.isFinite(value)) return;
      const date = new Date(value);
      const pad = item => String(item).padStart(2, "0");
      payload[`${prefix}_date`] = `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
      payload[`${prefix}_time`] = `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
    }

    function rangePayload(minimum, maximum, maximumPoints, fullHistory = false) {
      const payload = {
        ...(contractUID ? {contract_uid: contractUID} : {product_name: product.name}),
        adjusted: Boolean(state.adjusted),
        max_points: maximumPoints || 1200,
      };
      if (state.dataSource) payload.data_source = state.dataSource;
      if (Number.isFinite(minimum)) applyBound(payload, "start", minimum);
      else if (!fullHistory && options.startDate) payload.start_date = options.startDate;
      if (Number.isFinite(maximum)) applyBound(payload, "end", maximum);
      else if (!fullHistory && options.endDate) payload.end_date = options.endDate;
      return payload;
    }

    async function fetchRange(minimum, maximum, maximumPoints, fullHistory = false) {
      const value = await context.api(endpoint(source), {
        method: "POST",
        body: JSON.stringify(rangePayload(minimum, maximum, maximumPoints, fullHistory)),
      });
      if (value?.success === false) {
        throw new Error(value.error || context.t("请求失败"));
      }
      return value || {};
    }

    async function load() {
      const requestIDForLoad = ++requestID;
      disposePriceChart?.();
      disposePriceChart = null;
      controls.setBusy(true);
      information.disabled = true;
      chartMount.replaceChildren(FTUI.loading(context.t("正在读取价格曲线…")));
      try {
        // An intraday source may contain millions of rows. Start with a
        // bounded recent overview; the chart asks for precise bars on zoom.
        const intraday = /^(MIN|HOUR)/i.test(state.sourceFreq || "");
        const end = Date.parse(options.endDate || "") || Date.now();
        const recentStart = Math.max(Date.parse(options.startDate || "") || 0,
          end - 14 * 24 * 60 * 60 * 1000);
        let value;
        let fullOverviewLoaded = !intraday;
        try {
          value = await fetchRange(intraday ? recentStart : undefined,
            intraday ? end : undefined, intraday ? 600 : 1200);
        } catch (error) {
          if (!intraday) throw error;
          // Historical contracts can have sparse data in the last fortnight.
          value = await fetchRange(undefined, undefined, 600, true);
          fullOverviewLoaded = true;
        }
        if (!current(context) || requestIDForLoad !== requestID) return;
        if (value?.success === false) {
          throw new Error(value.error || context.t("请求失败"));
        }
        controls.apply(value || {});
        metadataPayload = value || {};
        information.disabled = false;
        if (window.FTPriceChart?.barsOf && Array.isArray(value?.data)) {
          await window.FTStaticLoader.loadGroups(["chart-workbench-price"]);
          if (!current(context) || requestIDForLoad !== requestID) return;
          if (!window.FTChartWorkbench?.mountPriceChart) {
            throw new Error(context.t("行情图组件未加载"));
          }
          disposePriceChart = window.FTChartWorkbench.mountPriceChart(chartMount, {
            bars: FTPriceChart.barsOf(value),
            translate: value => context.t(value),
            loadRange: async (minimum, maximum, maxPoints) => (
              FTPriceChart.barsOf(await fetchRange(minimum, maximum, maxPoints))
            ),
          });
          if (pendingFocus) disposePriceChart?.focusRange?.(...pendingFocus);
          // Give minute sources a fast recent first paint, then extend the
          // chart with a bounded full-history aggregate. Preserve a range the
          // user has already selected while the second request is running.
          if (!fullOverviewLoaded) {
            void fetchRange(undefined, undefined, 600, true).then(overview => {
              if (!current(context) || requestIDForLoad !== requestID) return;
              disposePriceChart?.mergeOverview?.(FTPriceChart.barsOf(overview));
            }).catch(() => {
              // The recent chart remains usable; zoom requests still retry.
            });
          }
        } else {
          chartMount.replaceChildren(FTUI.empty(
            context.t("价格曲线暂不可用"), context.t("暂无可绘制数据"),
          ));
        }
      } catch (error) {
        if (!current(context) || requestIDForLoad !== requestID) return;
        metadataPayload = null;
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
