(() => {

  function declaredTabs(resultDeclarations) {
    const seen = new Set();
    const output = [];
    (resultDeclarations || []).forEach(declaration => {
      (declaration?.result_tabs || []).forEach(tab => {
        const key = String(tab?.key || "");
        if (!key || seen.has(key)) return;
        seen.add(key); output.push({...tab, key});
      });
    });
    return output.sort((left, right) => (
      Number(left.order || 0) - Number(right.order || 0)
        || left.key.localeCompare(right.key)
    ));
  }

  function tabSourceNames(tabs) {
    return new Set((tabs || []).flatMap(tab => (
      Array.isArray(tab.source_artifacts) ? tab.source_artifacts : []
    )));
  }

  function tabsForArtifacts(resultDeclarations, artifacts) {
    const declared = declaredTabs(resultDeclarations);
    return declared;
  }

  function relevantArtifacts(artifacts, resultDeclarations = []) {
    const declared = declaredTabs(resultDeclarations);
    const names = tabSourceNames(declared);
    return (artifacts || []).filter(item => (
      item.state === "active" && names.has(String(item.name || ""))
    ));
  }

  function supports(artifacts, resultDeclarations = []) {
    return tabsForArtifacts(resultDeclarations, artifacts).length > 0;
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
    const configurationGroup = Array.isArray(analysis.configuration_groups)
      ? analysis.configuration_groups.find(group => (
        String(group?.config_group_id || "") === String(ui.configuration_group_id || "")
      )) || analysis.configuration_groups[0]
      : null;
    return String(
      configurationGroup?.product_scope_ref || ui.product_group_ref
        || analysis.product_path_selection_id
        || analysis.product_path_selection?.product_path_selection_id
        || analysis.product_path_selection?.product_group_template_id || "",
    );
  }

  function factorSeriesPath(factorRef, groupRef = "") {
    const params = new URLSearchParams({factor_ref: factorRef});
    if (groupRef) params.set("group_ref", groupRef);
    return `/factor-series?${params.toString()}`;
  }

  async function payloadsForTabs(
    context, artifacts, jobID, artifactQuery, resultDeclarations, tabKeys = null,
    sources = new Map(),
  ) {
    const declared = declaredTabs(resultDeclarations);
    const candidates = declared;
    const selected = tabKeys == null
      ? candidates : candidates.filter(tab => tabKeys.includes(tab.key));
    const names = tabSourceNames(selected);
    const selectedArtifacts = relevantArtifacts(artifacts, resultDeclarations)
      .filter(item => names.has(String(item.name || "")));
    const pairs = await Promise.all(selectedArtifacts.map(async artifact => {
      try {
        if (artifact.name === "ic_series_data") {
          let source = sources.get(artifact.name);
          if (!source) {
            source = window.FTJobArtifactQuery.timeSource(
              context, artifactPath(jobID, artifact, artifactQuery),
              {mode: "series", maxPoints: 800},
            );
            sources.set(artifact.name, source);
          }
          return [artifact.name, await source.load()];
        }
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

  async function ensureTabLoaded(context, state, key, rerender) {
    if (key === "runtime_summary") return;
    const tab = state.tabs.find(item => item.key === key);
    if (!tab) return;
    const activeNames = new Set((state.artifacts || [])
      .filter(item => item.state === "active")
      .map(item => String(item.name || "")));
    const required = (Array.isArray(tab.source_artifacts)
      ? tab.source_artifacts : []).filter(name => activeNames.has(String(name)));
    if (required.some(name => state.payloads[name] == null)) {
      const token = ++state.loadToken;
      state.loadingTab = key;
      state.loadError = "";
      rerender();
      try {
        const incoming = await payloadsForTabs(
          context, state.artifacts, state.jobID, state.artifactQuery,
          state.resultDeclarations, [key], state.sources,
        );
        if (token !== state.loadToken) return;
        state.payloads = {...state.payloads, ...incoming};
        state.rawModel = window.FTICResultModel.build(state.payloads);
        const discovered = state.rawModel.factors.map(item => item.key);
        state.factorOrder = [
          ...state.factorOrder.filter(item => discovered.includes(item)),
          ...discovered.filter(item => !state.factorOrder.includes(item)),
        ];
        state.activeMethod = state.rawModel.methods.includes(state.activeMethod)
          ? state.activeMethod : (state.rawModel.methods[0] || "rank");
      } catch (error) {
        if (token === state.loadToken) state.loadError = error.message || String(error);
      } finally {
        if (token === state.loadToken) state.loadingTab = "";
      }
      rerender();
    }
  }

  function empty(context, message) {
    const node = document.createElement("p");
    node.className = "ic-domain-empty"; node.textContent = context.t(message);
    return node;
  }

  function tabEmpty(context, state, key, fallback) {
    const tab = (state.tabs || []).find(item => item.key === key);
    return empty(context, tab?.empty_state || fallback);
  }

  function missingTab(context, state, tab) {
    const requests = Array.isArray(tab?.output_requests)
      ? tab.output_requests.map(String) : [];
    const declarations = new Map((state.resultDeclarations || []).map(item => [
      String(item.name || ""), item,
    ]));
    const canGenerate = requests.length > 0 && requests.every(name => (
      declarations.get(name)?.after_run === true
    ));
    return FTJobResultTabs.missingOutput(context, {
      canGenerate,
      onGenerate: canGenerate ? () => FTJobGeneration.generate(context, {
        jobID: state.jobID,
        artifactQuery: state.artifactQuery,
        executionQuery: state.executionQuery,
        onGenerated: state.onGenerated,
      }, requests) : null,
    });
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
    const matrix = state.model.matrix;
    if (!matrix.metrics.length) return tabEmpty(context, state, "summary", "暂无 IC 统计");
    const columns = ["metric", ...matrix.factors.map(factor => factor.key)];
    const rows = matrix.metrics.map(item => ({
      metric: item.label,
      values: item.values,
      bestIndex: item.bestIndex,
    }));
    const shell = document.createElement("div"); shell.className = "ic-domain-table-wrap";
    const table = window.FTReportTables.render({
      columns, rows, context, className: "ic-domain-summary-table",
      renderHeader: key => {
        if (key === "metric") return document.createTextNode(context.t("统计量"));
        const factor = matrix.factors.find(item => item.key === key);
        const button = document.createElement("button");
        button.type = "button";
        button.className = "ic-domain-factor-header";
        button.classList.toggle("active", key === state.activeFactorKey);
        button.append(factorReference(context, factor));
        button.addEventListener("click", () => {
          state.activeFactorKey = key; rerender();
        });
        return button;
      },
      renderCell: (value, row, key) => {
        if (key === "metric") return document.createTextNode(String(value || ""));
        return document.createTextNode(number(value));
      },
      values: row => [row.metric, ...row.values],
    });
    shell.append(table);
    const hint = document.createElement("small");
    hint.textContent = context.t("点击表头切换因子");
    shell.append(hint); return shell;
  }

  function chartView(context, options, stock = false, displayOptions = {}) {
    const target = document.createElement("div"); target.className = "ic-domain-chart";
    queueMicrotask(() => {
      if (!target.isConnected) return;
      try {
        window.FTJobHighcharts.mountOptions(
          context, target, options, stock, displayOptions,
        );
      }
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

  function selectedDescriptors(state) {
    const horizons = state.selectedHorizons?.length
      ? state.selectedHorizons : [state.activeHorizon];
    const delays = state.selectedDelays?.length
      ? state.selectedDelays.map(Number) : [Number(state.activeDelay || 0)];
    return state.descriptors.filter(item => (
      horizons.includes(item.horizon) && delays.includes(Number(item.delay || 0))
    ));
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

  function rowMatchesSelections(row, state) {
    const method = window.FTICResultModel.methodOf(row);
    const horizon = String(
      row.forward_return_horizon || row.horizon || row.baseline_horizon
        || row.primary_forward_return_horizon || "",
    );
    const delay = Number(row.entry_delay_bars || row.delay || 0);
    return (!method || state.selectedMethods.includes(method))
      && (!horizon || state.selectedHorizons.includes(horizon))
      && state.selectedDelays.includes(delay);
  }

  function methodLabel(context, method) {
    if (method === "rank") return context.t("Rank IC");
    if (method === "pearson") return context.t("Pearson IC");
    return method || context.t("IC");
  }

  function filterCapabilities(tab) {
    if (tab === "decay") return {method: true, horizon: false, delay: true, multi: true};
    if (["series", "autocorrelation", "rolling"].includes(tab)) {
      return {method: true, horizon: true, delay: true, multi: true};
    }
    return {method: true, horizon: true, delay: true, multi: false};
  }

  function filterControl(context, title, items, selected, multi, onChange) {
    return window.FTMultiSelectFilter.create(context, {
      title, items: items.map(item => ({
        value: String(item.value), label: String(item.label), description: String(item.label),
      })),
      selected: selected.map(String), multi, compact: true,
      onChange, onApply: onChange,
    }).element;
  }

  function sliceControl(context, state, rerender) {
    const root = document.createElement("div"); root.className = "ic-domain-slice";
    const rows = [];
    const capability = filterCapabilities(state.activeTab);
    const methods = state.rawModel.methods;
    const horizons = [...new Set(state.descriptors.map(item => item.horizon))];
    const delays = [...new Set(state.descriptors.map(item => Number(item.delay || 0)))];
    const commit = (key, values) => {
      const normalized = values.length ? values : [key === "delay" ? "0" : ""];
      if (key === "method") {
        state.selectedMethods = normalized;
        state.activeMethod = normalized[0] || methods[0] || "rank";
      } else if (key === "horizon") {
        state.selectedHorizons = normalized;
        state.activeHorizon = normalized[0] || horizons[0] || "";
      } else {
        state.selectedDelays = normalized.map(Number);
        state.activeDelay = state.selectedDelays[0] || 0;
      }
      rerender();
    };
    rows.push({label: "IC 类型", element: filterControl(
      context, context.t("IC 类型"),
      methods.map(value => ({value, label: methodLabel(context, value)})),
      capability.multi ? state.selectedMethods : [state.activeMethod],
      capability.multi, values => commit("method", values),
    )});
    if (capability.horizon) rows.push({label: "前瞻收益期", element: filterControl(
      context, context.t("前瞻收益期"),
      horizons.map(value => ({value, label: value})),
      capability.multi ? state.selectedHorizons : [state.activeHorizon],
      capability.multi, values => commit("horizon", values),
    )});
    if (capability.delay) rows.push({label: "入场延迟", element: filterControl(
      context, context.t("入场延迟"),
      delays.map(value => ({value, label: `d${value}`})),
      capability.multi ? state.selectedDelays : [state.activeDelay],
      capability.multi, values => commit("delay", values),
    )});
    const factor = activeFactor(state);
    if (factor?.factorRef) {
      const inspect = context.button(context.t("查看因子序列"), () => {
        context.navigate(factorSeriesPath(factor.factorRef, state.productGroupRef));
      }, context.t("将当前冻结因子与产品价格、成交量和持仓量对照"));
      inspect.classList.add("ic-factor-series-link");
      root.append(inspect);
    }
    root.prepend(FTJobResultTabs.filterPanel(context, {title: "筛选", rows}).element);
    return root;
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
    const standard = FTJobResultTabs.standardContent(
      context, state.activeTab, state.resultSummary,
    );
    if (standard) return standard;
    if (state.customAnalyses) {
      const customID = state.customAnalyses.tabIDFor(state.activeTab);
      if (customID) {
        const target = document.createElement("div");
        state.customAnalyses.render(customID, target, {
          onTabsChanged: rerender,
          onDeleted: () => {
            state.activeTab = state.tabs[0]?.key || "summary"; rerender();
          },
        });
        return target;
      }
    }
    const tab = state.tabs.find(item => item.key === state.activeTab);
    const activeArtifacts = new Set((state.artifacts || [])
      .filter(item => item.state === "active")
      .map(item => String(item.name || "")));
    const sources = Array.isArray(tab?.source_artifacts)
      ? tab.source_artifacts.map(String) : [];
    const available = tab?.source_policy === "all"
      ? sources.every(name => activeArtifacts.has(name))
      : sources.some(name => activeArtifacts.has(name));
    if (sources.length && !available) {
      return missingTab(context, state, tab);
    }
    const factor = activeFactor(state);
    const descriptor = activeDescriptor(state);
    if (!factor) return tabEmpty(context, state, state.activeTab, "暂无 IC 因子结果");
    if (state.activeTab === "summary") return summaryView(context, state, rerender);
    if (state.activeTab === "series") {
      const descriptors = selectedDescriptors(state);
      const options = window.FTICResultCharts.seriesOptions(
        factor, context, descriptors, state.selectedMethods,
      );
      const selected = options.series?.length;
      const source = state.sources.get("ic_series_data");
      return selected
        ? chartView(context, options, true, source ? {
          loadRange: (min, max, options = {}) => source.load({
            min, max, maxPoints: options.maxPoints,
          }),
          rangeOptions: payload => {
            const ranged = window.FTICResultModel.build({ic_series_data: payload});
            const rangedFactor = ranged.factors.find(item => (
              item.factorRef && item.factorRef === factor.factorRef
            )) || ranged.factors.find(item => item.factorAlias === factor.factorAlias);
            return window.FTICResultCharts.seriesOptions(
              rangedFactor || factor, context, descriptors, state.selectedMethods,
            );
          },
          loadingText: context.t("正在读取当前时间范围…"),
        } : {})
        : tabEmpty(context, state, "series", "暂无 IC 序列");
    }
    if (state.activeTab === "decay") {
      const decay = window.FTICResultCharts.decayOptions(
        factor, context, state.selectedMethods, state.selectedDelays,
      );
      const halfLife = state.model.halfLifeRows.filter(row => (
        rowMatchesFactor(row, factor)
          && (!window.FTICResultModel.methodOf(row)
            || state.selectedMethods.includes(window.FTICResultModel.methodOf(row)))
          && state.selectedDelays.includes(Number(row.entry_delay_bars || row.delay || 0))
      ));
      if (!decay.series?.some(item => item.data?.some(value => value != null)) && !halfLife.length) {
        return tabEmpty(context, state, "decay", "暂无多周期 IC 衰减数据");
      }
      const root = document.createElement("div"); root.className = "ic-domain-stack";
      if (decay.series?.length) root.append(chartView(context, decay));
      if (halfLife.length) root.append(chartView(
        context, window.FTICResultCharts.holdingDecayOptions(halfLife, context),
      ));
      return root;
    }
    if (state.activeTab === "autocorrelation") {
      const descriptors = selectedDescriptors(state);
      return descriptors.some(item => state.selectedMethods.some(method => (
        window.FTICResultModel.autocorrelation(
          factor, 20, state.model.summaryRows, item, method,
        ).length
      )))
        ? chartView(context, window.FTICResultCharts.autocorrelationOptions(
          factor, context, state.model.summaryRows, descriptors, state.selectedMethods,
        ))
        : tabEmpty(context, state, "autocorrelation", "IC 序列不足，无法估计自相关");
    }
    if (state.activeTab === "distribution") {
      return window.FTICResultModel.histogram(
        factor, state.model.summaryRows, descriptor, state.activeMethod,
      ).length
        ? chartView(context, window.FTICResultCharts.histogramOptions(
          factor, context, state.model.summaryRows, descriptor, state.activeMethod,
        ))
        : tabEmpty(context, state, "distribution", "暂无 IC 分布数据");
    }
    if (state.activeTab === "quantile_portfolio") {
      const selected = window.FTICResultModel.portfolioRowsFor(
        factor, descriptor, state.activeMethod,
      ).filter(row => rowMatchesSlice(row, state));
      return selected.length
        ? window.FTICPortfolioView.table(context, selected)
        : tabEmpty(context, state, "quantile_portfolio", "暂无分组组合统计数据");
    }
    if (state.activeTab === "resample") {
      const selected = state.model.resampleRows.filter(row => (
        rowMatchesFactor(row, factor) && rowMatchesSlice(row, state)
      ));
      return selected.length
        ? dataTable(context, selected)
        : tabEmpty(context, state, "resample", "暂无重采样稳定性数据");
    }
    const sourceRows = state.activeTab === "rolling"
      ? state.model.rollingRows : state.model.periodRows;
    const selected = sourceRows.filter(row => (
      rowMatchesFactor(row, factor) && (
        state.activeTab === "rolling" ? rowMatchesSelections(row, state) : rowMatchesSlice(row, state)
      )
    ));
    if (state.activeTab === "rolling" && selected.length) {
      const root = document.createElement("div"); root.className = "ic-domain-stack";
      root.append(
        chartView(context, window.FTICResultCharts.rollingOptions(selected, context)),
        dataTable(context, selected),
      );
      return root;
    }
    return selected.length
      ? dataTable(context, selected)
      : tabEmpty(context, state, state.activeTab, "暂无 IC 诊断数据");
  }

  function renderLoaded(context, target, state) {
    const standardTabs = FTJobResultTabs.compose({
      tabs: state.tabs || [], resultSummary: state.resultSummary,
    });
    const customKey = state.customAnalyses?.tabIDFor(state.activeTab);
    if (!customKey && !standardTabs.some(tab => tab.key === state.activeTab)) {
      state.activeTab = standardTabs[0]?.key || "summary";
    }
    const ordered = state.factorOrder.map(key => (
      state.rawModel.factors.find(item => item.key === key)
    )).filter(Boolean);
    state.descriptors = [...new Map(
      state.selectedMethods.flatMap(method => (
        window.FTICResultModel.descriptorsFor(ordered, method)
      )).map(item => [`${item.horizon}\u0000${item.delay}`, item]),
    ).values()];
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
    const availableMethods = new Set(state.rawModel.methods);
    state.selectedMethods = state.selectedMethods.filter(item => availableMethods.has(item));
    if (!state.selectedMethods.length && state.activeMethod) {
      state.selectedMethods = [state.activeMethod];
    }
    const availableHorizons = new Set(state.descriptors.map(item => item.horizon));
    state.selectedHorizons = state.selectedHorizons.filter(item => availableHorizons.has(item));
    if (!state.selectedHorizons.length && state.activeHorizon) {
      state.selectedHorizons = [state.activeHorizon];
    }
    const availableDelays = new Set(state.descriptors.map(item => Number(item.delay || 0)));
    state.selectedDelays = state.selectedDelays.map(Number)
      .filter(item => availableDelays.has(item));
    if (!state.selectedDelays.length) state.selectedDelays = [Number(state.activeDelay || 0)];
    state.model = {...state.rawModel, factors: ordered};
    state.model.matrix = window.FTICResultModel.statisticMatrix(
      ordered, state.rawModel.summaryRows, activeDescriptor(state), state.activeMethod,
    );
    const content = document.createElement("div"); content.className = "ic-domain-content";
    const rerender = () => renderLoaded(context, target, state);
    const customTabs = state.customAnalyses?.tabs({
      onDeleted: () => { state.activeTab = standardTabs[0]?.key || "summary"; rerender(); },
    }) || [];
    const nav = window.FTJobResultTabs.create(context, {
      className: "ic-domain-header",
      tabs: [
        ...standardTabs,
        ...customTabs,
      ],
      active: state.activeTab,
      controls: [sliceControl(context, state, rerender)],
      onChange: key => void FTJobResultTabs.activate(context, key, {
        customAnalyses: state.customAnalyses,
        onActive: async next => {
        state.loadToken += 1;
        state.loadingTab = "";
        state.loadError = "";
        state.activeTab = next;
        rerender();
        await ensureTabLoaded(context, state, next, rerender);
        },
      }),
    }).header;
    if (state.loadError) {
      content.append(empty(context, state.loadError));
    } else if (state.loadingTab) {
      content.append(window.FTUI.loading(context.t("正在读取此结果…")));
    } else {
      content.append(tabContent(context, state, rerender));
    }
    target.replaceChildren(nav, content);
  }

  function section(context, options) {
    const artifactTabs = tabsForArtifacts(
      options.resultDeclarations, options.artifacts,
    );
    const resultTabs = FTJobResultTabs.compose({
      tabs: artifactTabs, resultSummary: options.resultSummary,
    });
    if (!resultTabs.length) {
      return null;
    }
    const root = document.createElement("section"); root.className = "job-section ic-domain-results";
    const heading = document.createElement("h2"); heading.textContent = context.t("IC 测试结果");
    const target = document.createElement("div");
    target.append(window.FTUI.loading(context.t("正在读取 IC 结果…")));
    root.append(heading, target);
    queueMicrotask(async () => {
      try {
        const requested = options.customAnalyses?.state?.requestedKey || "";
        const activeTab = resultTabs.some(tab => tab.key === requested)
          ? requested : resultTabs[0]?.key || "summary";
        const rawModel = window.FTICResultModel.build({});
        const state = {
          rawModel, model: rawModel, factorOrder: [], tabs: resultTabs,
          activeFactorKey: "", activeTab,
          activeMethod: "rank", activeHorizon: "", activeDelay: 0,
          selectedMethods: ["rank"], selectedHorizons: [], selectedDelays: [0],
          customAnalyses: options.customAnalyses || null,
          productGroupRef: productGroupRef(
            options.configuration, options.productGroupRef,
          ),
          artifacts: options.artifacts, jobID: options.jobID,
          artifactQuery: options.artifactQuery || "",
          executionQuery: options.executionQuery || "",
          onGenerated: options.onGenerated,
          resultDeclarations: options.resultDeclarations || [],
          resultSummary: options.resultSummary || {},
          payloads: {}, sources: new Map(), loadToken: 0,
          loadingTab: resultTabs.some(tab => tab.key === activeTab) ? activeTab : "",
          loadError: "",
        };
        const rerender = () => renderLoaded(context, target, state);
        renderLoaded(context, target, state);
        await ensureTabLoaded(context, state, activeTab, rerender);
      } catch (error) { target.replaceChildren(empty(context, error.message)); }
    });
    return root;
  }

  window.FTICResults = Object.freeze({
    declaredTabs, factorSeriesPath, productGroupRef,
    relevantArtifacts, section, supports, tabsForArtifacts,
  });
})();
