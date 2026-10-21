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
      [context.t("产品时区"), payload.timezone || "Asia/Shanghai"],
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
    const timezonePicker = FTMultiSelectFilter.create(context, {
      title: context.t("显示时区"), multi: false, compact: true,
      className: "product-price-timezone-filter", items: [], selected: ["product"],
      onChange: values => {
        state.timeZoneChoice = values[0] || "product";
        options.setTimeZone(displayTimeZone(state));
        options.showTimeZone(displayTimeZone(state));
      },
    });
    controls.append(sourcePicker.element, adjustedPicker.element, timezonePicker.element);

    const frequency = document.createElement("span");
    frequency.className = "product-price-frequency";
    frequency.append(Object.assign(document.createElement("b"), {
      textContent: `${context.t("数据频率")}：`,
    }));
    const frequencyValue = document.createElement("span");
    frequency.append(frequencyValue);
    controls.append(frequency);

    function apply(payload) {
      state.productTimeZone = payload.timezone || state.productTimeZone || "Asia/Shanghai";
      timezonePicker.setItems([
        {value: "product", label: `${context.t("产品时区")} · ${state.productTimeZone}`},
        {value: "system", label: `${context.t("系统时区")} · ${systemTimeZone()}`},
        {value: "utc", label: "UTC"},
      ]);
      timezonePicker.setValues([state.timeZoneChoice || "product"]);
      options.showTimeZone(displayTimeZone(state));
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
    return {controls, apply, setBusy, sourcePicker, adjustedPicker, timezonePicker};
  }

  function systemTimeZone() {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  }

  function displayTimeZone(state) {
    return state.timeZoneChoice === "system" ? systemTimeZone()
      : state.timeZoneChoice === "utc" ? "UTC"
        : state.productTimeZone || "Asia/Shanghai";
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
    const timezoneLabel = document.createElement("span");
    timezoneLabel.className = "product-price-timezone-label";
    heading.append(timezoneLabel);
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
      setTimeZone: timeZone => disposePriceChart?.setTimeZone?.(timeZone),
      showTimeZone: timeZone => {
        timezoneLabel.textContent = `${context.t("时区")} · ${timeZone}`;
      },
    });
    const settings = FTUI.iconButton(context, "gearshape", "图表设置", () => {
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
        textContent: context.t("图表设置"),
      }), controls.controls);
      dialog.append(card);
      dialog.addEventListener("close", () => dialog.remove(), {once: true});
      document.body.append(dialog);
      dialog.showModal();
    });
    heading.append(settings);
    root.append(chartMount);
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
      const parts = Object.fromEntries(new Intl.DateTimeFormat("en-CA", {
        timeZone: state.productTimeZone || "Asia/Shanghai", year: "numeric",
        month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit",
        second: "2-digit", hourCycle: "h23",
      }).formatToParts(date).map(part => [part.type, part.value]));
      payload[`${prefix}_date`] = `${parts.year}-${parts.month}-${parts.day}`;
      payload[`${prefix}_time`] = `${parts.hour}:${parts.minute}:${parts.second}`;
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
        // One bounded full-history overview avoids a second whole-source read
        // and lets fitContent show the entire series on the first paint.
        const overviewPoints = Math.min(2400, Math.max(600,
          Math.round(chartMount.clientWidth || 1000)));
        const value = await fetchRange(undefined, undefined, overviewPoints, true);
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
            hasOpenInterest: Boolean(value.has_oi),
            timeZone: displayTimeZone(state),
            translate: value => context.t(value),
            loadRange: async (minimum, maximum, maxPoints) => {
              try {
                return FTPriceChart.barsOf(await fetchRange(minimum, maximum, maxPoints));
              } catch (error) {
                if (/指定范围内无(?:合约)?价格数据/.test(String(error?.message || ""))) {
                  return [];
                }
                throw error;
              }
            },
          });
          if (pendingFocus) disposePriceChart?.focusRange?.(...pendingFocus);
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
