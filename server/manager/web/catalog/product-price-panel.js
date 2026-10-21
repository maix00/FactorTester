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
        deliveryMode: String(item.delivery_mode || "historical_snapshot"),
      }))
      .filter(item => {
        if (seen.has(item.alias)) return false;
        seen.add(item.alias);
        return true;
      });
  }

  function sourceLabel(context, item) {
    const delivery = item.deliveryMode === "live_stream" ? context.t("实时")
      : item.deliveryMode === "delayed_stream" ? context.t("延迟") : "";
    return [item.alias, delivery, item.freq].filter(Boolean).join(" · ")
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

  function renderControls(context, state) {
    const controls = document.createElement("div");
    controls.className = "product-price-controls";
    const intervalMinutes = {MIN1: 1, MIN5: 5, MIN15: 15, MIN30: 30,
      HOUR1: 60, DAY1: 1440, WEEK1: 10080};
    const intervalItems = [
      {value: "SOURCE", label: context.t("原始频率")},
      {value: "MIN5", label: context.t("5 分钟")},
      {value: "MIN15", label: context.t("15 分钟")},
      {value: "MIN30", label: context.t("30 分钟")},
      {value: "HOUR1", label: context.t("1 小时")},
      {value: "DAY1", label: context.t("1 交易日")},
      {value: "WEEK1", label: context.t("1 周")},
    ];
    const sourcePicker = FTMultiSelectFilter.create(context, {
      title: context.t("数据源"), multi: false,
      className: "product-price-source-filter", items: [], selected: [""],
      onChange: values => {
        state.dataSource = values[0] || "";
        state.sourceFreq = state.sourceFreqByAlias?.[state.dataSource] || "";
        state.sourceDeliveryMode = state.sourceDeliveryModeByAlias?.[state.dataSource]
          || "historical_snapshot";
        if (state.sourceDeliveryMode === "live_stream") {
          state.chartInterval = "LIVE";
          intervalPicker.setValues(["LIVE"]);
        }
        refreshIntervals();
      },
    });
    const adjustedPicker = FTMultiSelectFilter.create(context, {
      title: context.t("价格序列"), multi: false,
      className: "product-price-adjusted-filter",
      items: [
        {value: "raw", label: context.t("原始价格")},
        {value: "adjusted", label: context.t("复权价格")},
      ],
      selected: [state.adjusted ? "adjusted" : "raw"],
      onChange: values => {
        state.adjusted = values[0] === "adjusted";
      },
    });
    const timezonePicker = FTMultiSelectFilter.create(context, {
      title: context.t("显示时区"), multi: false,
      className: "product-price-timezone-filter", items: [], selected: ["product"],
      onChange: values => {
        state.timeZoneChoice = values[0] || "product";
      },
    });
    const intervalPicker = FTMultiSelectFilter.create(context, {
      title: context.t("K 线频率"), multi: false,
      className: "product-price-interval-filter",
      items: intervalItems,
      selected: [state.chartInterval],
      onChange: values => {
        state.chartInterval = values[0] || "SOURCE";
      },
    });
    function refreshIntervals() {
      const sourceMinutes = intervalMinutes[state.sourceFreq] || 0;
      intervalPicker.setItems([
        ...(state.sourceDeliveryMode === "live_stream"
          ? [{value: "LIVE", label: context.t("实时")}] : []),
        ...intervalItems.filter(item => item.value === "SOURCE"
          || intervalMinutes[item.value] >= sourceMinutes),
      ]);
      if (state.chartInterval === "LIVE" && state.sourceDeliveryMode !== "live_stream") {
        state.chartInterval = "SOURCE";
        intervalPicker.setValues(["SOURCE"]);
      } else if (state.chartInterval !== "SOURCE" && state.chartInterval !== "LIVE"
          && intervalMinutes[state.chartInterval] < sourceMinutes) {
        state.chartInterval = "SOURCE";
        intervalPicker.setValues(["SOURCE"]);
      }
    }
    const rangePicker = FTMultiSelectFilter.create(context, {
      title: context.t("时间范围"), multi: false,
      className: "product-price-range-filter",
      items: [
        {value: "day", label: context.t("最近一天")},
        {value: "month", label: context.t("最近一个月")},
        {value: "year", label: context.t("最近一年")},
        {value: "ytd", label: context.t("今年以来")},
        {value: "all", label: context.t("全部")},
        {value: "custom", label: context.t("所选时间段")},
      ],
      selected: [state.timeRange],
      onChange: values => {
        state.timeRange = values[0] || "year";
        if (state.timeRange !== "custom") state.focusRange = null;
      },
    });
    controls.append(sourcePicker.element, adjustedPicker.element,
      intervalPicker.element, rangePicker.element, timezonePicker.element);

    const frequency = document.createElement("span");
    frequency.className = "product-price-frequency";
    frequency.append(Object.assign(document.createElement("b"), {
      textContent: `${context.t("源数据频率")}：`,
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
      const entries = sourceEntries(payload.available_sources);
      state.sourceFreqByAlias = Object.fromEntries(entries.map(item => [item.alias, item.freq]));
      state.sourceDeliveryModeByAlias = Object.fromEntries(
        entries.map(item => [item.alias, item.deliveryMode]));
      const actual = String(payload.data_source || state.dataSource || "").trim();
      sourcePicker.setItems([
        {value: "", label: context.t("自动选择"), exclusive: true},
        ...entries.map(item => ({value: item.alias, label: sourceLabel(context, item)})),
      ]);
      state.dataSource = actual;
      sourcePicker.setValues([entries.some(item => item.alias === actual) ? actual : ""]);
      state.sourceFreq = entries.find(item => item.alias === actual)?.freq || payload.freq || "";
      state.sourceDeliveryMode = entries.find(item => item.alias === actual)?.deliveryMode
        || payload.delivery_mode || "historical_snapshot";
      refreshIntervals();
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
      intervalPicker.setStatus({loading: busy});
      rangePicker.setStatus({loading: busy});
    }

    apply({
      available_sources: [],
      data_source: state.dataSource,
      adjusted: state.adjusted,
      supports_adjusted: false,
    });
    return {controls, apply, setBusy, sourcePicker, adjustedPicker,
      intervalPicker, rangePicker, timezonePicker};
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
      sourceDeliveryMode: "historical_snapshot",
      chartInterval: "DAY1",
      timeRange: options.startDate || options.endDate ? "custom" : "all",
      ...(options.dataSource ? {dataSource: options.dataSource} : {}),
      ...(options.adjusted !== undefined ? {adjusted: Boolean(options.adjusted)} : {}),
    };
    const draftState = {...state};
    const root = document.createElement("section");
    root.className = "product-price-panel";
    const heading = document.createElement("div");
    heading.className = "product-price-heading";
    heading.append(Object.assign(document.createElement("h2"), {
      textContent: context.t("行情数据"),
    }));
    const timezoneLabel = document.createElement("span");
    timezoneLabel.className = "product-price-timezone-label";
    heading.append(timezoneLabel);
    const selectionLabel = document.createElement("span");
    selectionLabel.className = "product-price-selection-label";
    heading.append(selectionLabel);
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
      "适配当前时间范围", () => disposePriceChart?.fitContent?.());
    heading.append(fit);
    root.append(heading);
    const chartMount = document.createElement("div");
    chartMount.className = "product-price-chart-mount";
    const chartHost = document.createElement("div");
    chartMount.append(chartHost);
    const loadOverlay = document.createElement("div");
    loadOverlay.className = "product-price-load-overlay";
    loadOverlay.setAttribute("role", "status");
    loadOverlay.textContent = context.t("正在读取所选时间范围的 K 线…");
    const controls = renderControls(context, draftState);
    const settings = FTUI.iconButton(context, "gearshape", "图表设置", () => {
      const dialog = FTUI.dialogRoot(context);
      dialog.className = "product-price-info-dialog";
      const card = document.createElement("div");
      card.className = "dialog-card wide product-price-info-card";
      const close = document.createElement("button");
      close.type = "button";
      close.className = "dialog-close";
      close.setAttribute("aria-label", context.t("关闭"));
      close.textContent = "×";
      close.addEventListener("click", () => dialog.close());
      const errorMessage = document.createElement("p");
      errorMessage.className = "product-price-settings-error";
      errorMessage.setAttribute("role", "alert");
      errorMessage.hidden = true;
      const actions = document.createElement("div");
      actions.className = "dialog-actions product-price-settings-actions";
      const save = FTUI.actionButton(context.t("保存并加载"), null, {variant: "primary"});
      save.addEventListener("click", async () => {
        errorMessage.hidden = true;
        save.disabled = true;
        const succeeded = await load({...draftState}, errorMessage);
        save.disabled = false;
        if (succeeded) dialog.close();
      });
      actions.append(save);
      card.append(close, Object.assign(document.createElement("h2"), {
        textContent: context.t("图表设置"),
      }), controls.controls, errorMessage, actions);
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
    let termRanges = [];
    let selectedTermID = "";
    let overlayTimer = null;
    const termID = item => String(item.uid || item.contract || `${item.start}:${item.end}`);
    root.setTermRanges = rows => {
      termRanges = (Array.isArray(rows) ? rows : []).map(item => ({
        id: termID(item), start: Date.parse(item.start),
        end: Date.parse(item.end) + 24 * 60 * 60 * 1000,
      })).filter(item => Number.isFinite(item.start) && Number.isFinite(item.end));
      disposePriceChart?.setRangeBands?.(termRanges);
    };
    root.selectTermRange = item => {
      selectedTermID = termID(item);
      const shown = disposePriceChart?.selectRangeBand?.(selectedTermID);
      if (shown === false) context.showNotice?.(
        context.t("该区间不在已加载的行情数据内，请在图表设置中扩大时间范围"), true);
    };
    let removalObserver = null;
    if (window.MutationObserver) {
      removalObserver = new MutationObserver(() => {
        if (root.isConnected) return;
        requestID += 1;
        if (overlayTimer) clearTimeout(overlayTimer);
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

    function rangePayload(minimum, maximum, maximumPoints, fullHistory = false,
      selection = state) {
      const payload = {
        ...(contractUID ? {contract_uid: contractUID} : {product_name: product.name}),
        adjusted: Boolean(selection.adjusted),
        max_points: maximumPoints || 1200,
        chart_mode: "fixed",
        chart_interval: selection.chartInterval,
      };
      if (selection.dataSource) payload.data_source = selection.dataSource;
      if (["day", "month", "year", "ytd"].includes(selection.timeRange)) {
        payload.chart_range = selection.timeRange;
      }
      if (Number.isFinite(minimum)) applyBound(payload, "start", minimum);
      else if (selection.timeRange === "custom" && selection.focusRange) {
        applyBound(payload, "start", selection.focusRange[0]);
      }
      else if (!fullHistory && selection.timeRange === "custom" && options.startDate) {
        payload.start_date = options.startDate;
      }
      if (Number.isFinite(maximum)) applyBound(payload, "end", maximum);
      else if (selection.timeRange === "custom" && selection.focusRange) {
        applyBound(payload, "end", selection.focusRange[1]);
      }
      else if (!fullHistory && selection.timeRange === "custom" && options.endDate) {
        payload.end_date = options.endDate;
      }
      return payload;
    }

    async function fetchRange(minimum, maximum, maximumPoints, fullHistory = false,
      selection = state) {
      const value = await context.api(endpoint(source), {
        method: "POST",
        body: JSON.stringify(rangePayload(minimum, maximum, maximumPoints, fullHistory, selection)),
      });
      if (value?.success === false) {
        throw new Error(value.error || context.t("请求失败"));
      }
      return value || {};
    }

    async function load(selection = state, settingsError = null) {
      const requestIDForLoad = ++requestID;
      if (overlayTimer) clearTimeout(overlayTimer);
      overlayTimer = null;
      loadOverlay.classList.remove("is-error");
      loadOverlay.textContent = context.t("正在读取所选时间范围的 K 线…");
      controls.setBusy(true);
      if (!settingsError) chartMount.append(loadOverlay);
      try {
        // The selected interval is authoritative. Never silently change its
        // candle width to satisfy the transport budget.
        const value = await fetchRange(undefined, undefined, 5000, false, selection);
        if (!current(context) || requestIDForLoad !== requestID) return false;
        if (value?.success === false) {
          throw new Error(value.error || context.t("请求失败"));
        }
        const appliedSelection = {...selection,
          productTimeZone: value.timezone || selection.productTimeZone};
        const intervalNames = {LIVE: context.t("实时"), SOURCE: context.t("原始频率"), MIN5: context.t("5 分钟"),
          MIN15: context.t("15 分钟"), MIN30: context.t("30 分钟"),
          HOUR1: context.t("1 小时"), DAY1: context.t("1 交易日"),
          WEEK1: context.t("1 周")};
        const rangeNames = {day: context.t("最近一天"), month: context.t("最近一个月"),
          year: context.t("最近一年"), ytd: context.t("今年以来"),
          all: context.t("全部"), custom: context.t("所选时间段")};
        if (window.FTPriceChart?.barsOf && Array.isArray(value?.data)) {
          await window.FTStaticLoader.loadGroups(["chart-workbench-price"]);
          if (!current(context) || requestIDForLoad !== requestID) return false;
          if (!window.FTChartWorkbench?.mountPriceChart) {
            throw new Error(context.t("行情图组件未加载"));
          }
          disposePriceChart = window.FTChartWorkbench.mountPriceChart(chartHost, {
            bars: FTPriceChart.barsOf(value),
            hasOpenInterest: Boolean(value.has_oi),
            timeZone: displayTimeZone(appliedSelection),
            translate: value => context.t(value),
          });
          disposePriceChart?.setRangeBands?.(termRanges);
          if (selectedTermID) disposePriceChart?.selectRangeBand?.(selectedTermID);
        } else {
          chartHost.replaceChildren(FTUI.empty(
            context.t("行情数据暂不可用"), context.t("暂无可绘制数据"),
          ));
        }
        Object.assign(state, appliedSelection);
        controls.apply(value || {});
        state.dataSource = draftState.dataSource;
        state.sourceFreq = draftState.sourceFreq;
        state.sourceFreqByAlias = draftState.sourceFreqByAlias;
        state.sourceDeliveryMode = draftState.sourceDeliveryMode;
        state.sourceDeliveryModeByAlias = draftState.sourceDeliveryModeByAlias;
        state.adjusted = draftState.adjusted;
        state.productTimeZone = draftState.productTimeZone;
        selectionLabel.textContent = `${intervalNames[state.chartInterval]} · ${rangeNames[state.timeRange]}`;
        timezoneLabel.textContent = `${context.t("时区")} · ${displayTimeZone(state)}`;
        metadataPayload = value || {};
        information.disabled = false;
        return true;
      } catch (error) {
        if (!current(context) || requestIDForLoad !== requestID) return false;
        if (settingsError) {
          settingsError.textContent = error.message || context.t("行情数据读取失败");
          settingsError.hidden = false;
          context.showNotice?.(settingsError.textContent, true);
          return false;
        }
        if (!disposePriceChart) chartHost.replaceChildren(FTUI.empty(
          context.t("行情数据读取失败"), error.message || ""));
        else {
          loadOverlay.textContent = error.message || context.t("行情数据读取失败");
          loadOverlay.classList.add("is-error");
          overlayTimer = setTimeout(() => {
            loadOverlay.remove();
            overlayTimer = null;
          }, 5000);
        }
      } finally {
        if (requestIDForLoad === requestID) {
          controls.setBusy(false);
          if (!loadOverlay.classList.contains("is-error")) loadOverlay.remove();
        }
      }
      return false;
    }

    await load();
    return root;
  }

  window.FTProductPricePanel = Object.freeze({render, sourceEntries});
})();
