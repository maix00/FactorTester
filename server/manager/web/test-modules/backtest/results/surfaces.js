(() => {
  const chartViews = Object.freeze({
    equity_curve_data: {view: "equity", label: "净值", viewer: "equity_curve"},
    returns_over_time_data: {view: "returns", label: "收益率", viewer: "line_chart"},
    metrics_over_time_data: {view: "metrics", label: "滚动指标", viewer: "metrics_chart"},
    cash_detail_data: {
      view: "cash", label: "现金", fields: ["cash", "cash_after"],
      labels: {cash: "现金", cash_after: "变动后现金"},
    },
    margin_detail_data: {
      view: "margin", label: "策略保证金占权益比例", fields: ["margin_utilization"],
      labels: {margin_utilization: "策略保证金占权益比例"},
      percentFields: ["margin_utilization"],
      aggregate: "strategy_margin_equity_ratio",
    },
    exposure_detail_data: {
      view: "exposure", label: "风险敞口", fields: ["gross_exposure", "net_exposure"],
      labels: {
        gross_exposure: "总敞口", net_exposure: "净敞口",
      },
    },
    turnover_detail_data: {
      view: "turnover", label: "换手率", fields: ["average", "total", "turnover"],
      labels: {average: "平均换手率", total: "累计换手率", turnover: "换手率"},
      percentFields: ["average", "total", "turnover"],
    },
  });

  function available(state, definitions) {
    return [...state.model.resultViews.entries()].flatMap(([artifact, registered]) => {
      const renderer = definitions[artifact];
      if (!renderer || !state.artifactsByName.has(artifact)) return [];
      return [[artifact, {...renderer, ...registered}]];
    }).sort((left, right) => left[1].order - right[1].order);
  }

  function strategyControl(context, state) {
    if (!state.model.strategies.length) return null;
    return window.FTBacktestStrategySelection.control(context, {
      strategies: state.model.strategies,
      selected: state.strategySelection,
      onApply: values => {
        state.strategySelection = values;
        state.strategySelections[state.activeTab] = values;
        const pagePrefix = {
          execution_account: "executionView:", return_analysis: "returnView:",
        }[state.activeTab];
        Object.keys(state.tablePages).forEach(key => {
          if (key === state.activeTab || (pagePrefix && key.startsWith(pagePrefix))) {
            delete state.tablePages[key];
          }
        });
        state.rerender();
      },
    }).element;
  }

  function filterRow(context, label, control) {
    const row = document.createElement("div");
    row.className = "backtest-surface-filter-row";
    const title = document.createElement("div");
    title.className = "backtest-surface-filter-label";
    title.textContent = context.t(label);
    const value = document.createElement("div");
    value.className = "backtest-surface-filter-value";
    value.append(control);
    row.append(title, value);
    return row;
  }

  function toolbar(context, state, additions = []) {
    const root = document.createElement("div");
    root.className = "backtest-surface-toolbar";
    const strategy = strategyControl(context, state);
    if (strategy) root.append(filterRow(context, "策略", strategy));
    additions.filter(Boolean).forEach(item => {
      if (item.element && item.label) {
        root.append(filterRow(context, item.label, item.element));
      } else root.append(item);
    });
    return root;
  }

  const dimensions = Object.freeze([
    {key: "account", label: "账户", fields: ["account_id", "account_ref", "account", "ledger_id", "ledger"]},
    {key: "cash_pool", label: "资金池", fields: ["cash_pool_id", "cash_pool", "pool_id"]},
    {
      key: "account_currency", label: "账户币种",
      fields: ["account_currency", "ledger_currency", "currency"],
    },
    {
      key: "cash_pool_base_currency", label: "资金池基准币种",
      fields: ["cash_pool_base_currency", "pool_base_currency", "base_currency"],
    },
  ]);

  function dimensionValue(row, definition) {
    const value = definition.fields.map(field => row?.[field])
      .find(item => item != null && String(item).trim());
    return String(value ?? "").trim();
  }

  function dimensionFilters(context, state, rows, key) {
    const root = document.createElement("div");
    root.className = "backtest-dimension-filters";
    state.dimensionSelections[key] = state.dimensionSelections[key] || {};
    const predicates = [];
    dimensions.forEach(definition => {
      const values = [...new Set(rows.map(row => dimensionValue(row, definition)).filter(Boolean))]
        .sort((left, right) => left.localeCompare(right, "zh-CN"));
      if (!values.length) return;
      const all = `__all_${definition.key}__`;
      let selected = state.dimensionSelections[key][definition.key] || [all];
      selected = selected.filter(value => value === all || values.includes(value));
      if (!selected.length || selected.includes(all)) selected = [all];
      state.dimensionSelections[key][definition.key] = selected;
      const selectedSet = selected.includes(all) ? null : new Set(selected);
      predicates.push(row => !selectedSet || selectedSet.has(dimensionValue(row, definition)));
      const control = window.FTMultiSelectFilter.create(context, {
        title: context.t(definition.label), compact: true, multi: true,
        className: "backtest-dimension-filter",
        items: [{
          value: all, label: context.t(`全部${definition.label}`), exclusive: true,
          description: context.t(`不按${definition.label}筛选`),
        }, ...values.map(value => ({value, label: value, description: value}))],
        selected,
        searchPlaceholder: context.t(`搜索${definition.label}…`),
        onApply: next => {
          state.dimensionSelections[key][definition.key] = next;
          delete state.tablePages[key];
          state.rerender();
        },
      }).element;
      root.append(filterRow(context, definition.label, control));
    });
    return {
      element: root,
      filterRows: values => values.filter(row => predicates.every(filter => filter(row))),
      rowFilter: row => predicates.every(filter => filter(row)),
    };
  }

  function firstValue(row, fields) {
    return String(fields.map(field => row?.[field])
      .find(item => item != null && String(item).trim()) ?? "").trim();
  }

  function relationshipRows(rows) {
    const accountDefinition = dimensions.find(item => item.key === "account");
    const poolDefinition = dimensions.find(item => item.key === "cash_pool");
    const relations = [];
    const seen = new Set();
    rows.forEach(row => {
      const strategy = String(row?.strategy_id || row?.strategy_ref || row?.strategy || "").trim();
      const account = dimensionValue(row, accountDefinition);
      const pool = dimensionValue(row, poolDefinition);
      const accountCurrency = firstValue(row, ["account_currency", "ledger_currency", "currency"]);
      const poolBaseCurrency = firstValue(row, [
        "cash_pool_base_currency", "pool_base_currency", "base_currency",
      ]);
      if (!account && !pool) return;
      const key = `${strategy}\u0000${account}\u0000${pool}\u0000${accountCurrency}\u0000${poolBaseCurrency}`;
      if (seen.has(key)) return;
      seen.add(key); relations.push({
        strategy, account, accountCurrency, pool, poolBaseCurrency,
      });
    });
    return relations;
  }

  function joined(values) {
    return [...new Set(values.filter(Boolean))].sort((left, right) => (
      left.localeCompare(right, "zh-CN")
    )).join("、");
  }

  function relationPerspective(relations, perspective, missing) {
    if (perspective === "strategy") return relations.map(item => ({
      策略: item.strategy || missing,
      账户: item.account || missing,
      账户币种: item.accountCurrency || missing,
      资金池: item.pool || missing,
      资金池基准币种: item.poolBaseCurrency || missing,
    }));
    const field = perspective === "account" ? "account" : "pool";
    const grouped = new Map();
    relations.forEach(item => {
      const key = item[field] || missing;
      const group = grouped.get(key) || [];
      group.push(item); grouped.set(key, group);
    });
    return [...grouped.entries()].map(([key, items]) => perspective === "account" ? ({
      账户: key,
      账户币种: joined(items.map(item => item.accountCurrency)) || missing,
      策略: joined(items.map(item => item.strategy)) || missing,
      资金池: joined(items.map(item => item.pool)) || missing,
      资金池基准币种: joined(items.map(item => item.poolBaseCurrency)) || missing,
    }) : ({
      资金池: key,
      资金池基准币种: joined(items.map(item => item.poolBaseCurrency)) || missing,
      账户: joined(items.map(item => item.account)) || missing,
      账户币种: joined(items.map(item => item.accountCurrency)) || missing,
      策略: joined(items.map(item => item.strategy)) || missing,
    }));
  }

  function relationshipView(context, state, rows, key) {
    const relations = relationshipRows(rows);
    const root = document.createElement("section");
    root.className = "backtest-account-relations";
    const heading = document.createElement("h3");
    heading.textContent = context.t("策略、账户与资金池关系");
    root.append(heading);
    if (!relations.length) {
      const note = document.createElement("p");
      note.textContent = context.t("当前生成物未登记账户或资金池层级");
      root.append(note); return root;
    }
    state.relationshipViews = state.relationshipViews || {};
    const active = state.relationshipViews[key] || "strategy";
    const navigation = document.createElement("div");
    navigation.className = "backtest-relation-tabs";
    [["strategy", "按策略"], ["account", "按账户"], ["pool", "按资金池"]]
      .forEach(([value, label]) => {
        const button = document.createElement("button");
        button.type = "button"; button.textContent = context.t(label);
        button.classList.toggle("active", value === active);
        button.addEventListener("click", () => {
          state.relationshipViews[key] = value;
          delete state.tablePages[`${key}:relations:${value}`];
          state.rerender();
        });
        navigation.append(button);
      });
    const tableRows = relationPerspective(relations, active, context.t("未登记"));
    const table = state.helpers.dataTable(
      context, tableRows, state, `${key}:relations:${active}`,
    );
    table.classList.add("backtest-relation-table");
    root.append(navigation, table);
    return root;
  }

  function lazyTarget(context, state, artifact, render) {
    const target = document.createElement("div");
    target.className = "backtest-result-lazy-target";
    const error = state.errors[artifact];
    if (error) target.append(state.helpers.message(context, error.message));
    else if (state.payloads[artifact]) render(target, state.payloads[artifact]);
    else {
      target.append(window.FTUI.loading(context.t("正在读取此结果…")));
      queueMicrotask(() => state.ensurePayloads([artifact]));
    }
    return target;
  }

  function chartCard(context, state, artifact, definition) {
    const section = document.createElement("section");
    section.className = "backtest-chart-card";
    const heading = document.createElement("h3");
    heading.textContent = context.t(definition.label);
    const content = lazyTarget(context, state, artifact, (target, payload) => {
      const filtered = state.strategyScope.filterPayload(payload);
      queueMicrotask(() => {
        try {
          const display = {
            ...state.evaluationWindow, showOutOfSample: state.showOutOfSample,
            hideMetricControl: true, hideTitle: true,
            selectedMetric: definition.metricKey || "",
            onPointClick: timestamp => state.openEventFlow(timestamp),
            chartRange: state.chartRange,
            onRangeChange: (min, max, source) => {
              if (!Number.isFinite(min) || !Number.isFinite(max)) return;
              state.chartRange = {min, max};
              for (const current of state.visibleCharts || []) {
                if (current === source) continue;
                current.xAxis?.[0]?.setExtremes(min, max, false, false, {trigger: "ft-sync"});
                current.redraw?.(false);
              }
            },
          };
          let mounted;
          if (definition.viewer) {
            mounted = window.FTJobHighcharts.mount(
              context, target, filtered, definition.viewer, display,
            );
          } else {
            mounted = window.FTJobHighcharts.mountRows(
              context, target, filtered, definition, display,
            );
          }
          if (mounted) state.visibleCharts?.add(mounted);
        } catch (error) {
          target.replaceChildren(state.helpers.message(context, error.message));
        }
      });
    });
    section.append(heading, content);
    return section;
  }

  function timeSeries(context, state) {
    const root = document.createElement("div");
    root.className = "backtest-time-series-surface";
    state.visibleCharts = new Set();
    const registered = available(state, chartViews);
    const metricsArtifact = registered.find(([, definition]) => (
      definition.viewer === "metrics_chart"
    ))?.[0];
    const metricsLoading = Boolean(
      metricsArtifact && !state.payloads[metricsArtifact] && !state.errors[metricsArtifact],
    );
    if (metricsLoading) {
      queueMicrotask(() => state.ensurePayloads([metricsArtifact]));
    }
    const choices = registered.flatMap(([artifact, definition]) => {
      if (definition.viewer === "equity_curve") return [
        [artifact, {...definition, view: "equity", label: "净值"}],
        [artifact, {...definition, view: "drawdown", label: "回撤", viewer: "drawdown_curve"}],
      ];
      if (definition.viewer !== "metrics_chart") return [[artifact, definition]];
      return window.FTJobHighcharts.metricChoices(state.payloads[artifact] || {})
        .map(metric => [artifact, {
          ...definition, view: `metric:${metric.key}`, label: metric.label,
          metricKey: metric.key,
        }]);
    });
    const allowed = new Set(choices.map(([, definition]) => definition.view));
    let selected = (state.chartSelection || []).filter(value => allowed.has(value));
    if (!selected.length && choices.length) selected = [choices[0][1].view];
    state.chartSelection = selected;
    const chartFilter = window.FTMultiSelectFilter.create(context, {
      title: context.t("曲线"), compact: true, multi: true,
      className: "backtest-result-chart-filter",
      items: choices.map(([, definition]) => ({
        value: definition.view, label: context.t(definition.label),
        description: context.t(`显示${definition.label}曲线`),
      })),
      selected,
      loading: metricsLoading,
      loadingText: context.t("正在读取曲线候选…"),
      searchPlaceholder: context.t("搜索曲线…"),
      onApply: values => { state.chartSelection = values; state.rerender(); },
    }).element;
    const controls = [{label: "曲线", element: chartFilter}];
    if (state.evaluationWindow) controls.push(window.FTUI.actionButton(
      context.t(state.showOutOfSample ? "仅显示样本内" : "显示样本外"),
      () => { state.showOutOfSample = !state.showOutOfSample; state.rerender(); },
      {variant: "secondary"},
    ));
    root.append(toolbar(context, state, controls));
    const charts = document.createElement("div");
    charts.className = "backtest-chart-grid";
    choices.filter(([, definition]) => selected.includes(definition.view))
      .forEach(([artifact, definition]) => charts.append(
        chartCard(context, state, artifact, definition),
      ));
    if (!charts.childElementCount) charts.append(
      state.helpers.message(context, "请至少选择一条曲线"),
    );
    root.append(charts);
    return root;
  }

  function registeredViews(state, surface) {
    return [...state.model.resultViews.entries()]
      .filter(([artifact, item]) => (
        item.surface === surface && state.artifactsByName.has(artifact)
      ))
      .sort((left, right) => left[1].order - right[1].order)
      .map(([artifact, item]) => [item.view, item.label, artifact]);
  }

  function innerSurface(context, state, definitions, stateKey) {
    const availableViews = definitions.filter(([, , artifact]) => (
      !artifact || state.artifactsByName.has(artifact)
    ));
    const active = availableViews.some(([key]) => key === state[stateKey])
      ? state[stateKey] : availableViews[0]?.[0];
    state[stateKey] = active;
    const root = document.createElement("div");
    root.className = "backtest-inner-surface";
    const navigation = document.createElement("div");
    navigation.className = "backtest-inner-tabs";
    availableViews.forEach(([key, label]) => {
      const button = document.createElement("button");
      button.type = "button"; button.textContent = context.t(label);
      button.classList.toggle("active", key === active);
      button.addEventListener("click", () => { state[stateKey] = key; state.rerender(); });
      navigation.append(button);
    });
    root.append(toolbar(context, state), navigation);
    const content = document.createElement("div");
    content.className = "backtest-inner-content";
    const selected = availableViews.find(([key]) => key === active);
    if (selected?.[0] === "event_flow") {
      const artifacts = window.FTBacktestEventFlow.coreSources
        .map(([artifact]) => artifact).filter(artifact => state.artifactsByName.has(artifact));
      const missing = artifacts.filter(artifact => !state.payloads[artifact]);
      if (missing.length) {
        content.append(window.FTUI.loading(context.t("正在读取交易事件…")));
        queueMicrotask(() => state.ensurePayloads(missing));
      } else {
        const rows = artifacts.flatMap(artifact => state.strategyScope.filterRows(
          state.payloads[artifact]?.rows || [],
        ));
        const filters = dimensionFilters(context, state, rows, `${stateKey}:event_flow`);
        content.append(relationshipView(
          context, state, rows, `${stateKey}:event_flow`,
        ));
        if (filters.element.childElementCount) content.append(filters.element);
        const flow = document.createElement("div");
        content.append(flow);
        window.FTBacktestEventFlow.render(
          context, flow, state.payloads, state.strategyScope,
          {rowFilter: filters.rowFilter},
        );
      }
    } else if (selected?.[2]) {
      content.append(lazyTarget(context, state, selected[2], (target, payload) => {
        const key = `${stateKey}:${selected[0]}`;
        const rows = state.strategyScope.filterRows(window.FTBacktestResultModel.rows(payload));
        if (stateKey === "executionView") {
          const filters = dimensionFilters(context, state, rows, key);
          target.append(relationshipView(context, state, rows, key));
          if (filters.element.childElementCount) target.append(filters.element);
          target.append(state.helpers.dataTable(context, filters.filterRows(rows), state, key));
        } else target.append(state.helpers.dataTable(context, rows, state, key));
      }));
    }
    root.append(content);
    return root;
  }

  function executionAccount(context, state) {
    return innerSurface(context, state, [
      ["event_flow", "事件流", ""],
      ...registeredViews(state, "execution_account"),
    ], "executionView");
  }

  function returnAnalysis(context, state) {
    return innerSurface(
      context, state, registeredViews(state, "return_analysis"), "returnView",
    );
  }

  window.FTBacktestResultSurfaces = Object.freeze({
    chartViews, executionAccount, returnAnalysis, strategyControl, timeSeries, toolbar,
  });
})();
