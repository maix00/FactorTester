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
    const candidates = declared;
    const active = new Set((artifacts || [])
      .filter(item => item.state === "active")
      .map(item => String(item.name || "")));
    return candidates.filter(tab => {
      const sources = Array.isArray(tab.source_artifacts)
        ? tab.source_artifacts.map(String) : [];
      if (!sources.length) return false;
      const matches = tab.source_policy === "all"
        ? sources.every(source => active.has(source))
        : sources.some(source => active.has(source));
      return matches;
    });
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

  async function payloadsForTabs(
    context, artifacts, jobID, artifactQuery, resultDeclarations, tabKeys = null,
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
          state.resultDeclarations, [key],
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
            state.activeTab = state.tabs[0]?.key || "summary"; rerender();
          },
        });
        return target;
      }
    }
    const factor = activeFactor(state);
    const descriptor = activeDescriptor(state);
    if (!factor) return tabEmpty(context, state, state.activeTab, "暂无 IC 因子结果");
    if (state.activeTab === "summary") return summaryView(context, state, rerender);
    if (state.activeTab === "series") {
      return window.FTICResultModel.seriesFor(factor, descriptor, state.activeMethod)
        ? chartView(context, window.FTICResultCharts.seriesOptions(
          factor, context, descriptor, state.activeMethod,
        ), true)
        : tabEmpty(context, state, "series", "暂无 IC 序列");
    }
    if (state.activeTab === "decay") {
      return window.FTICResultModel.decay(factor, state.activeMethod).length
        ? chartView(context, window.FTICResultCharts.decayOptions(
          factor, context, state.activeMethod,
        ))
        : tabEmpty(context, state, "decay", "暂无多周期 IC 衰减数据");
    }
    if (state.activeTab === "autocorrelation") {
      return window.FTICResultModel.autocorrelation(
        factor, 20, state.model.summaryRows, descriptor, state.activeMethod,
      ).length
        ? chartView(context, window.FTICResultCharts.autocorrelationOptions(
          factor, context, state.model.summaryRows, descriptor, state.activeMethod,
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
    if (state.activeTab === "holding_half_life") {
      const selected = state.model.halfLifeRows.filter(row => (
        rowMatchesFactor(row, factor) && rowMatchesSlice(row, state)
      ));
      return selected.length
        ? dataTable(context, selected)
        : tabEmpty(context, state, "holding_half_life", "暂无持有期半衰期数据");
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
    return selected.length
      ? dataTable(context, selected)
      : tabEmpty(context, state, state.activeTab, "暂无 IC 诊断数据");
  }

  function renderLoaded(context, target, state) {
    const standardTabs = state.tabs || [];
    const customKey = state.customAnalyses?.tabIDFor(state.activeTab);
    if (!customKey && !standardTabs.some(tab => tab.key === state.activeTab)) {
      state.activeTab = standardTabs[0]?.key || "summary";
    }
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
        if (key !== "custom-analysis:new") {
          await ensureTabLoaded(context, state, key, rerender);
        }
      },
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
    const resultTabs = tabsForArtifacts(
      options.resultDeclarations, options.artifacts,
    );
    if (!resultTabs.length || !supports(options.artifacts, options.resultDeclarations)) {
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
          customAnalyses: options.customAnalyses || null,
          productGroupRef: productGroupRef(
            options.configuration, options.productGroupRef,
          ),
          artifacts: options.artifacts, jobID: options.jobID,
          artifactQuery: options.artifactQuery || "",
          resultDeclarations: options.resultDeclarations || [],
          payloads: {}, loadToken: 0,
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
