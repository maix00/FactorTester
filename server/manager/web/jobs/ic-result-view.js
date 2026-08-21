(() => {
  const dataArtifactNames = new Set([
    "ic_series_data", "ic_statistics_data", "ic_statistics_summary_data",
    "ic_rolling_stability_data", "ic_period_diagnostics_data",
    "ic_holding_half_life_data", "ic_quantile_portfolio_statistics_data",
  ]);
  const tabs = [
    ["summary", "IC 汇总"], ["series", "IC 序列"], ["decay", "IC 衰减"],
    ["autocorrelation", "自相关"], ["rolling", "Rolling IC"],
    ["periods", "分期诊断"], ["holding_half_life", "持有期半衰期"],
    ["quantile_portfolio", "分组组合统计"],
    ["distribution", "IC 分布"],
  ];

  function relevantArtifacts(artifacts) {
    return (artifacts || []).filter(item => (
      item.state === "active" && dataArtifactNames.has(String(item.name || ""))
    ));
  }

  function supports(artifacts) {
    const names = new Set(relevantArtifacts(artifacts).map(item => item.name));
    return names.has("ic_series_data") || names.has("ic_statistics_data")
      || names.has("ic_quantile_portfolio_statistics_data");
  }

  function artifactPath(jobID, artifact, artifactQuery) {
    return `/api/jobs/${encodeURIComponent(jobID)}/artifacts/${encodeURIComponent(artifact.name)}${artifactQuery}`;
  }

  function configurationPayload(configuration) {
    return configuration?.configuration?.payload
      || configuration?.payload || configuration || {};
  }

  function productGroupRef(configuration, explicit = "") {
    if (explicit) return String(explicit);
    const payload = configurationPayload(configuration);
    const analysis = payload.analyses?.ic || payload.analysis?.ic || payload.ic || {};
    const ui = payload.ui?.ic || {};
    return String(
      ui.product_group_ref || analysis.product_path_selection_id
        || analysis.product_path_selection?.product_path_selection_id
        || analysis.product_path_selection?.product_group_template_id || "",
    );
  }

  function factorSeriesPath(factorRef, groupRef = "") {
    const params = new URLSearchParams({factor_ref: factorRef});
    if (groupRef) params.set("group_ref", groupRef);
    return `/factor-series?${params.toString()}`;
  }

  async function payloads(context, artifacts, jobID, artifactQuery) {
    const pairs = await Promise.all(relevantArtifacts(artifacts).map(async artifact => {
      try {
        const response = await FTJobArtifacts.fetch(
          context, artifactPath(jobID, artifact, artifactQuery),
        );
        return [artifact.name, JSON.parse(await response.text())];
      } catch (error) {
        throw new Error(
          `${String(artifact.name || "IC 数据")}: ${error?.message || error}`,
        );
      }
    }));
    return Object.fromEntries(pairs);
  }

  function empty(context, message) {
    const node = document.createElement("p");
    node.className = "ic-domain-empty"; node.textContent = context.t(message);
    return node;
  }

  function number(value) {
    if (value == null) return "—";
    if (!Number.isFinite(Number(value))) return String(value);
    const numeric = Number(value);
    return Math.abs(numeric) >= 1000 ? numeric.toLocaleString()
      : numeric.toFixed(6).replace(/0+$/, "").replace(/\.$/, "");
  }

  function factorReference(context, factor) {
    if (!factor?.factorRef) return document.createTextNode(factor?.factorAlias || "Factor");
    const url = FTJobListFormat.referenceURL("factor", factor.factorRef);
    return window.FTRichText.inline(`[${factor.factorAlias}](${url})`, context);
  }

  function summaryView(context, state, rerender) {
    if (!state.model.matrix.metrics.length) return empty(context, "暂无 IC 统计");
    const shell = document.createElement("div"); shell.className = "ic-domain-table-wrap";
    const table = document.createElement("table"); table.className = "ic-domain-table";
    const head = table.createTHead().insertRow();
    const metric = document.createElement("th"); metric.textContent = context.t("统计量");
    metric.className = "ic-domain-metric"; head.append(metric);
    let dragged = null;
    state.model.matrix.factors.forEach((factor, index) => {
      const cell = document.createElement("th"); cell.draggable = true;
      cell.classList.toggle("active", factor.key === state.activeFactorKey);
      cell.append(factorReference(context, factor));
      cell.addEventListener("click", () => {
        state.activeFactorKey = factor.key; rerender();
      });
      cell.addEventListener("dragstart", () => { dragged = index; });
      cell.addEventListener("dragover", event => event.preventDefault());
      cell.addEventListener("drop", event => {
        event.preventDefault();
        if (dragged == null || dragged === index) return;
        const [moved] = state.factorOrder.splice(dragged, 1);
        state.factorOrder.splice(index, 0, moved); rerender();
      });
      head.append(cell);
    });
    const body = table.createTBody();
    state.model.matrix.metrics.forEach(item => {
      const row = body.insertRow();
      const label = row.insertCell(); label.textContent = item.label;
      label.className = "ic-domain-metric";
      item.values.forEach((value, index) => {
        const cell = row.insertCell(); cell.textContent = number(value);
        cell.classList.toggle("best", index === item.bestIndex);
      });
    });
    shell.append(table);
    const hint = document.createElement("small");
    hint.textContent = context.t("点击表头切换因子，拖动表头调整比较顺序");
    shell.append(hint); return shell;
  }

  function chartView(context, options, stock = false) {
    const target = document.createElement("div"); target.className = "ic-domain-chart";
    queueMicrotask(() => {
      try { window.FTICResultCharts.mount(target, options, stock); }
      catch (error) { target.replaceChildren(empty(context, error.message)); }
    });
    return target;
  }

  function rowMatchesFactor(row, factor) {
    const ref = String(row.factor_ref || "");
    const alias = String(row.factor_alias || row.factor_name || "");
    return (ref && ref === factor.factorRef) || (!ref && alias === factor.factorAlias);
  }

  function activeDescriptor(state) {
    return state.activeHorizon ? {
      horizon: state.activeHorizon, delay: Number(state.activeDelay || 0),
    } : null;
  }

  function rowMatchesSlice(row, state) {
    const method = String(row.ic_method || row.correlation || row.method || "");
    if (method && !window.FTICResultModel.methodMatches(row, state.activeMethod)) return false;
    const horizon = String(
      row.forward_return_horizon || row.horizon || row.baseline_horizon
        || row.primary_forward_return_horizon || "",
    );
    if (horizon && horizon !== state.activeHorizon) return false;
    const hasDelay = row.entry_delay_bars != null || row.delay != null;
    return !hasDelay
      || Number(row.entry_delay_bars || row.delay || 0) === Number(state.activeDelay || 0);
  }

  function methodLabel(context, method) {
    if (method === "rank") return context.t("Rank IC");
    if (method === "pearson") return context.t("Pearson IC");
    return method || context.t("IC");
  }

  function sliceControl(context, state, rerender) {
    const root = document.createElement("div"); root.className = "ic-domain-slice";
    const methods = document.createElement("div"); methods.className = "ic-domain-methods";
    state.rawModel.methods.forEach(method => {
      const button = document.createElement("button"); button.type = "button";
      button.classList.toggle("active", state.activeMethod === method);
      button.textContent = methodLabel(context, method);
      button.addEventListener("click", () => {
        state.activeMethod = method; state.activeHorizon = ""; rerender();
      });
      methods.append(button);
    });
    const fields = document.createElement("div"); fields.className = "ic-domain-slice-fields";
    const choices = [
      ["horizon", context.t("前瞻收益期"), [...new Set(state.descriptors.map(item => item.horizon))]],
      ["delay", context.t("入场延迟"), state.descriptors.filter(item => (
        item.horizon === state.activeHorizon
      )).map(item => item.delay)],
    ];
    choices.forEach(([key, label, values]) => {
      const field = document.createElement("label");
      const title = document.createElement("span"); title.textContent = label;
      const select = document.createElement("select");
      [...new Set(values)].forEach(value => {
        const option = document.createElement("option"); option.value = String(value);
        option.textContent = key === "delay" ? `d${value}` : String(value); select.append(option);
      });
      select.value = String(key === "delay" ? state.activeDelay : state.activeHorizon);
      select.addEventListener("change", () => {
        if (key === "horizon") {
          state.activeHorizon = select.value;
          state.activeDelay = state.descriptors.find(item => (
            item.horizon === state.activeHorizon
          ))?.delay || 0;
        } else state.activeDelay = Number(select.value);
        rerender();
      });
      field.append(title, select); fields.append(field);
    });
    const factor = activeFactor(state);
    if (factor?.factorRef) {
      const inspect = context.button(context.t("查看因子序列"), () => {
        context.navigate(factorSeriesPath(factor.factorRef, state.productGroupRef));
      }, context.t("将当前冻结因子与产品价格、成交量和持仓量对照"));
      inspect.classList.add("ic-factor-series-link");
      fields.append(inspect);
    }
    root.append(methods, fields); return root;
  }

  function dataTable(context, rows) {
    if (!rows.length) return empty(context, "暂无数据");
    const columns = [...new Set(rows.slice(0, 200).flatMap(row => Object.keys(row)))];
    return window.FTReportTables.render({
      columns, rows: rows.slice(0, 500), context, className: "ic-domain-data-table",
      renderHeader: key => window.FTRichText.inline(String(key), context),
      renderCell: (value, row, key) => {
        if (key === "factor_alias" && row.factor_ref) {
          return factorReference(context, {
            factorAlias: String(value || row.factor_ref), factorRef: row.factor_ref,
          });
        }
        if (value && typeof value === "object") return window.FTUI.code(value);
        return window.FTRichText.inline(String(value ?? ""), context);
      },
      values: row => columns.map(key => row[key]),
    });
  }

  function activeFactor(state) {
    return state.model.factors.find(item => item.key === state.activeFactorKey)
      || state.model.factors[0];
  }

  function tabContent(context, state, rerender) {
    if (state.customAnalyses) {
      const customID = state.customAnalyses.tabIDFor(state.activeTab);
      if (customID) {
        const target = document.createElement("div");
        state.customAnalyses.render(customID, target, {
          onTabsChanged: rerender,
          onDeleted: () => {
            state.activeTab = tabs[0][0]; rerender();
          },
        });
        return target;
      }
    }
    const factor = activeFactor(state);
    const descriptor = activeDescriptor(state);
    if (!factor) return empty(context, "暂无 IC 因子结果");
    if (state.activeTab === "summary") return summaryView(context, state, rerender);
    if (state.activeTab === "series") {
      return window.FTICResultModel.seriesFor(factor, descriptor, state.activeMethod)
        ? chartView(context, window.FTICResultCharts.seriesOptions(
          factor, context, descriptor, state.activeMethod,
        ), true)
        : empty(context, "暂无 IC 序列");
    }
    if (state.activeTab === "decay") {
      return window.FTICResultModel.decay(factor, state.activeMethod).length
        ? chartView(context, window.FTICResultCharts.decayOptions(
          factor, context, state.activeMethod,
        ))
        : empty(context, "暂无多周期 IC 衰减数据");
    }
    if (state.activeTab === "autocorrelation") {
      return window.FTICResultModel.autocorrelation(
        factor, 20, state.model.summaryRows, descriptor, state.activeMethod,
      ).length
        ? chartView(context, window.FTICResultCharts.autocorrelationOptions(
          factor, context, state.model.summaryRows, descriptor, state.activeMethod,
        ))
        : empty(context, "IC 序列不足，无法估计自相关");
    }
    if (state.activeTab === "distribution") {
      return window.FTICResultModel.histogram(
        factor, state.model.summaryRows, descriptor, state.activeMethod,
      ).length
        ? chartView(context, window.FTICResultCharts.histogramOptions(
          factor, context, state.model.summaryRows, descriptor, state.activeMethod,
        ))
        : empty(context, "暂无 IC 分布数据");
    }
    if (state.activeTab === "holding_half_life") {
      const selected = state.model.halfLifeRows.filter(row => (
        rowMatchesFactor(row, factor) && rowMatchesSlice(row, state)
      ));
      return dataTable(context, selected.length ? selected : state.model.halfLifeRows);
    }
    if (state.activeTab === "quantile_portfolio") {
      const selected = window.FTICResultModel.portfolioRowsFor(
        factor, descriptor, state.activeMethod,
      ).filter(row => rowMatchesSlice(row, state));
      return window.FTICPortfolioView.table(context, selected);
    }
    const sourceRows = state.activeTab === "rolling"
      ? state.model.rollingRows : state.model.periodRows;
    const selected = sourceRows.filter(row => (
      rowMatchesFactor(row, factor) && rowMatchesSlice(row, state)
    ));
    if (state.activeTab === "rolling" && selected.length) {
      const root = document.createElement("div"); root.className = "ic-domain-stack";
      root.append(
        chartView(context, window.FTICResultCharts.rollingOptions(selected, context)),
        dataTable(context, selected),
      );
      return root;
    }
    return dataTable(context, selected.length ? selected : sourceRows);
  }

  function renderLoaded(context, target, state) {
    const ordered = state.factorOrder.map(key => (
      state.rawModel.factors.find(item => item.key === key)
    )).filter(Boolean);
    state.descriptors = window.FTICResultModel.descriptorsFor(
      ordered, state.activeMethod,
    );
    if (!state.descriptors.some(item => (
      item.horizon === state.activeHorizon && item.delay === Number(state.activeDelay || 0)
    ))) {
      const declared = window.FTICResultModel.primaryDescriptor(
        ordered[0], state.rawModel.summaryRows, state.activeMethod,
      );
      const selected = state.descriptors.find(item => (
        item.horizon === declared?.horizon && item.delay === declared?.delay
      )) || state.descriptors[0] || {horizon: "", delay: 0};
      state.activeHorizon = selected.horizon; state.activeDelay = selected.delay;
    }
    state.model = {...state.rawModel, factors: ordered};
    state.model.matrix = window.FTICResultModel.statisticMatrix(
      ordered, state.rawModel.summaryRows, activeDescriptor(state), state.activeMethod,
    );
    const content = document.createElement("div"); content.className = "ic-domain-content";
    const rerender = () => renderLoaded(context, target, state);
    const customTabs = state.customAnalyses?.tabs({
      onDeleted: () => { state.activeTab = tabs[0][0]; rerender(); },
    }) || [];
    const nav = window.FTJobResultTabs.create(context, {
      className: "ic-domain-header",
      tabs: [
        ...tabs.map(([key, label]) => ({key, label})),
        ...customTabs,
      ],
      active: state.activeTab,
      controls: [sliceControl(context, state, rerender)],
      onChange: async key => {
        if (key === "custom-analysis:new") {
          try {
            const analysis = await state.customAnalyses.add();
            state.activeTab = state.customAnalyses.keyFor(analysis.tab_id);
          } catch (error) {
            context.showNotice?.(error.message || String(error), true);
          }
        } else state.activeTab = key;
        rerender();
      },
    }).header;
    content.append(tabContent(context, state, rerender));
    target.replaceChildren(nav, content);
  }

  function section(context, options) {
    if (!supports(options.artifacts)) return null;
    const root = document.createElement("section"); root.className = "job-section ic-domain-results";
    const heading = document.createElement("h2"); heading.textContent = context.t("IC 测试结果");
    const target = document.createElement("div");
    target.append(window.FTUI.loading(context.t("正在读取 IC 结果…")));
    root.append(heading, target);
    queueMicrotask(async () => {
      try {
        const rawModel = window.FTICResultModel.build(await payloads(
          context, options.artifacts, options.jobID,
          options.artifactQuery || "",
        ));
        const factorOrder = rawModel.factors.map(item => item.key);
        renderLoaded(context, target, {
          rawModel, model: rawModel, factorOrder,
          activeFactorKey: factorOrder[0] || "",
          activeTab: options.customAnalyses?.state?.requestedKey || "summary",
          activeMethod: rawModel.methods[0] || "rank", activeHorizon: "", activeDelay: 0,
          customAnalyses: options.customAnalyses || null,
          productGroupRef: productGroupRef(
            options.configuration, options.productGroupRef,
          ),
        });
      } catch (error) { target.replaceChildren(empty(context, error.message)); }
    });
    return root;
  }

  window.FTICResults = Object.freeze({
    dataArtifactNames, factorSeriesPath, productGroupRef,
    relevantArtifacts, section, supports,
  });
})();
