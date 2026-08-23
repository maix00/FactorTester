(() => {
  const tabLabels = Object.freeze({
    overview: "概览", strategy_stats: "策略统计", time_series: "时变指标",
    execution_account: "交易与账户", return_analysis: "收益与风险",
  });

  function relevantArtifacts(artifacts) {
    const names = new Set(window.FTBacktestResultModel.payloadNames);
    return (artifacts || []).filter(item => (
      item.state === "active" && names.has(String(item.name || ""))
    ));
  }

  function supports(artifacts, summary = {}) {
    return relevantArtifacts(artifacts).length > 0
      || Boolean(summary?.metrics && Object.keys(summary.metrics).length)
      || Boolean(window.FTBacktestRuntimeModel?.rows?.(summary).length);
  }

  function artifactPath(jobID, artifact, artifactQuery) {
    return `/api/jobs/${encodeURIComponent(jobID)}/artifacts/${encodeURIComponent(artifact.name)}${artifactQuery}`;
  }

  async function loadPayload(context, artifact, jobID, artifactQuery) {
    const response = await FTJobArtifacts.fetch(
      context, artifactPath(jobID, artifact, artifactQuery),
    );
    return JSON.parse(await response.text());
  }

  function message(context, value) {
    const node = document.createElement("p");
    node.className = "backtest-domain-empty";
    node.textContent = context.t(value);
    return node;
  }

  function format(value, kind = "number", currency = "") {
    if (kind === "text") return String(value ?? "");
    const number = window.FTBacktestResultModel.finite(value);
    if (number == null) return "—";
    if (kind === "percent") return `${(number * 100).toFixed(2)}%`;
    if (kind === "currency") {
      return `${number.toLocaleString(undefined, {maximumFractionDigits: 2})} ${currency}`.trim();
    }
    return number.toLocaleString(undefined, {maximumFractionDigits: 4});
  }

  const metricNames = Object.freeze({
    "Total Return": "总收益率", "Annual Return": "年化收益率",
    "Mean Return": "平均收益率", "Win Rate": "胜率",
    "Sharpe Ratio": "Sharpe ratio", "Calmar Ratio": "Calmar ratio",
    Volatility: "波动率", "Max Drawdown": "历史最大回撤",
    Skewness: "偏度", Kurtosis: "峰度", "Avg Turnover": "平均换手率",
    "Avg Turnover Accel": "平均换手加速度",
    "Avg Position Changes": "平均持仓变化次数", "Up Ratio": "上涨期占比",
  });

  function metricDisplay(metric, value) {
    const number = window.FTBacktestResultModel.finite(value);
    if (number == null) return "—";
    if (["Total Return", "Annual Return", "Win Rate", "Volatility", "Max Drawdown"]
      .includes(metric)) return `${number.toFixed(Math.abs(number) < 1 ? 4 : 2)}%`;
    if (metric === "Mean Return") {
      const basisPoints = number * 100;
      return `${basisPoints.toFixed(Math.abs(basisPoints) < 1 ? 3 : 2)} bp`;
    }
    if (["Avg Turnover", "Avg Turnover Accel", "Up Ratio"].includes(metric)) {
      return `${(number * 100).toFixed(2)}%`;
    }
    return number.toLocaleString(undefined, {maximumFractionDigits: 4});
  }

  function summaryTable(context, state) {
    const rows = state.strategyScope.filterRows(
      state.model.summaryRows, row => row.series,
    );
    if (!rows.length) return message(context, "暂无回测汇总");
    const columns = [
      ["series", "策略", "text"], ["initial_equity", "初始权益", "currency"],
      ["final_equity", "期末权益", "currency"], ["total_return", "总收益率", "percent"],
      ["annual_return", "年化收益率", "percent"], ["sharpe_ratio", "Sharpe ratio", "number"],
      ["max_drawdown", "历史最大回撤", "percent"],
    ];
    return window.FTReportTables.render({
      columns: columns.map(item => item[0]), rows, context,
      className: "backtest-domain-table",
      renderHeader: key => document.createTextNode(
        context.t(columns.find(item => item[0] === key)?.[1] || key),
      ),
      renderCell: (value, row, key) => {
        const column = columns.find(item => item[0] === key);
        return document.createTextNode(format(value, column?.[2], row.currency));
      },
      values: row => columns.map(item => row[item[0]]),
    });
  }

  function runtimeTable(context, state) {
    const rows = state.strategyScope.filterRows(
      window.FTBacktestRuntimeModel.rows(state.model.summary),
    );
    if (!rows.length) return null;
    const section = document.createElement("section");
    section.className = "backtest-runtime-summary";
    const heading = document.createElement("h3");
    heading.textContent = context.t("策略运行摘要");
    const page = Number(state.tablePages.runtime || 1);
    const table = window.FTUI.pagedTable(
      [context.t("类型"), context.t("状态"), context.t("说明")],
      rows.map(row => [row.type, row.status, row.detail].map(value => (
        window.FTRichText.inline(String(value ?? ""), context)
      ))),
      {
        page, pageSize: 20,
        previousLabel: context.t("上一页"), nextLabel: context.t("下一页"),
        pageLabel: (current, total) => `${current} / ${total}`,
        totalLabel: total => `${context.t("共")} ${total} ${context.t("行")}`,
        onPageChange: next => {
          state.tablePages.runtime = next;
          renderLoaded(context, state.target, state);
        },
      },
    );
    table.shell.classList.add(
      "backtest-domain-table", "backtest-runtime-table",
    );
    const visibleRows = rows.slice(table.start, table.start + table.pageSize);
    Array.from(table.body.rows).forEach((row, index) => {
      const level = String(visibleRows[index]?.level || "info");
      row.dataset.level = level;
    });
    section.append(heading, table.shell);
    return section;
  }

  function groupMetricsTable(context, state) {
    const baseMatrix = state.model.metricMatrix;
    const matrix = {
      ...baseMatrix,
      entries: state.strategyScope.filterEntries(baseMatrix.entries),
    };
    if (!matrix.entries.length) return message(context, "暂无分组指标");
    const result = window.FTUI.table([
      context.t("指标"), ...matrix.entries.map(item => item.label),
    ]);
    result.shell.classList.add("backtest-metric-matrix");
    [...result.table.tHead.rows[0].cells].slice(1).forEach((cell, index) => {
      const entry = matrix.entries[index];
      const button = document.createElement("button");
      button.type = "button"; button.textContent = entry.label;
      button.title = context.t("查看策略分析");
      button.className = "backtest-group-heading";
      button.addEventListener("click", () => {
        window.FTBacktestStrategyAnalysis.open(context, state.options, entry);
      });
      cell.replaceChildren(button);
    });
    matrix.sections.forEach(section => {
      const sectionRow = result.body.insertRow();
      sectionRow.className = "backtest-metric-section";
      const sectionCell = sectionRow.insertCell(); sectionCell.colSpan = matrix.entries.length + 1;
      sectionCell.textContent = context.t(section.title);
      section.metrics.forEach(metric => {
        const best = window.FTBacktestResultModel.bestMetricIndex(matrix, metric);
        const row = result.body.insertRow();
        const label = row.insertCell();
        label.textContent = context.t(state.model.summary?.metrics_meta?.cn?.[metric]
          || metricNames[metric] || metric);
        label.className = "backtest-metric-name";
        matrix.entries.forEach((entry, index) => {
          const cell = row.insertCell();
          cell.textContent = metricDisplay(
            metric, window.FTBacktestResultModel.metricValue(matrix, entry, metric),
          );
          if (index === best) cell.classList.add("best");
        });
      });
    });
    return result.shell;
  }

  function dataTable(context, rows, state, pageKey = state.activeTab) {
    if (!rows.length) return message(context, "暂无明细");
    const columns = [...new Set(rows.slice(0, 500).flatMap(row => Object.keys(row)))];
    const page = Number(state.tablePages[pageKey] || 1);
    const pageSize = 20;
    const start = Math.max(0, (page - 1) * pageSize);
    const values = rows.slice(start, start + pageSize).map(row => columns.map(key => {
      const value = row[key];
      return value && typeof value === "object"
        ? window.FTUI.code(value)
        : window.FTRichText.inline(String(value ?? ""), context);
    }));
    const table = window.FTUI.pagedTable(columns.map(key => context.t(key)), values, {
      page, pageSize, remote: true, total: rows.length,
      previousLabel: context.t("上一页"), nextLabel: context.t("下一页"),
      pageLabel: (current, total) => `${current} / ${total}`,
      totalLabel: total => `${context.t("共")} ${total} ${context.t("行")}`,
      onPageChange: next => {
        state.tablePages[pageKey] = next;
        renderLoaded(context, state.target, state);
      },
    });
    table.shell.classList.add("backtest-domain-table");
    return table.shell;
  }

  function tabContent(context, state) {
    if (state.customAnalyses) {
      const customID = state.customAnalyses.tabIDFor(state.activeTab);
      if (customID) {
        const target = document.createElement("div");
        state.customAnalyses.render(customID, target, {
          onTabsChanged: () => renderLoaded(context, state.target, state),
          onDeleted: () => {
            state.activeTab = state.model.tabs[0] || "overview";
            renderLoaded(context, state.target, state);
          },
        });
        return target;
      }
    }
    if (state.activeTab === "overview") {
      const root = document.createElement("div");
      root.className = "backtest-overview-surface";
      root.append(window.FTBacktestResultSurfaces.toolbar(context, state));
      const runtime = runtimeTable(context, state);
      if (runtime) root.append(runtime);
      if (state.model.summaryRows.length) root.append(summaryTable(context, state));
      if (window.FTBacktestResultModel.initialSnapshot(state.model.summary)) {
        const actions = document.createElement("div");
        actions.className = "backtest-domain-actions";
        actions.append(window.FTUI.actionButton(context.t("持仓快照"), () => (
          window.FTBacktestSnapshotView.open(context, state.options)
        ), {variant: "secondary"}));
        root.prepend(actions);
      }
      return root.childElementCount ? root : message(context, "暂无回测汇总");
    }
    if (state.activeTab === "strategy_stats") {
      const root = document.createElement("div");
      root.className = "backtest-overview-surface";
      root.append(
        window.FTBacktestResultSurfaces.toolbar(context, state),
        groupMetricsTable(context, state),
      );
      return root;
    }
    if (state.activeTab === "time_series") {
      return window.FTBacktestResultSurfaces.timeSeries(context, state);
    }
    if (state.activeTab === "execution_account") {
      return window.FTBacktestResultSurfaces.executionAccount(context, state);
    }
    if (state.activeTab === "return_analysis") {
      return window.FTBacktestResultSurfaces.returnAnalysis(context, state);
    }
    return message(context, "暂无结果");
  }

  async function ensurePayloads(context, state, names) {
    const pending = [...new Set(names)].filter(name => (
      state.artifactsByName.has(name) && !state.payloads[name] && !state.loading.has(name)
    ));
    if (!pending.length) return;
    pending.forEach(name => state.loading.add(name));
    await Promise.all(pending.map(async name => {
      try {
        state.payloads[name] = await loadPayload(
          context, state.artifactsByName.get(name), state.options.jobID,
          state.options.artifactQuery || "",
        );
        delete state.errors[name];
      } catch (error) {
        state.errors[name] = error;
      } finally {
        state.loading.delete(name);
      }
    }));
    state.model = window.FTBacktestResultModel.build(
      state.payloads, state.model.summary, [...state.artifactsByName.keys()],
      state.options.resultDeclarations || [],
    );
    if (state.target?.isConnected !== false) renderLoaded(context, state.target, state);
  }

  function renderLoaded(context, target, state) {
    state.target = target;
    state.strategySelection = window.FTBacktestStrategySelection.normalize(
      state.strategySelections[state.activeTab]
        || [window.FTBacktestStrategySelection.ALL_STRATEGIES],
      state.model.strategies,
    );
    state.strategySelections[state.activeTab] = state.strategySelection;
    state.strategyScope = window.FTBacktestStrategySelection.createScope(
      state.model.strategies, state.strategySelection,
    );
    state.rerender = () => renderLoaded(context, target, state);
    state.ensurePayloads = names => ensurePayloads(context, state, names);
    state.openEventFlow = timestamp => {
      const view = window.FTBacktestAnalysisUI.dialog(context, "交易事件", "");
      view.body.append(window.FTUI.loading(context.t("正在读取交易事件…")));
      const names = window.FTBacktestEventFlow.coreSources
        .map(([name]) => name).filter(name => state.artifactsByName.has(name));
      void ensurePayloads(context, state, names).then(() => {
        if (view.root.isConnected) window.FTBacktestEventFlow.render(
          context, view.body, state.payloads, state.strategyScope, {timestamp},
        );
      });
    };
    state.helpers = {dataTable, message};
    const customTabs = state.customAnalyses?.tabs({
      onDeleted: () => {
        state.activeTab = state.model.tabs[0] || "overview";
        renderLoaded(context, target, state);
      },
    }) || [];
    const header = window.FTJobResultTabs.create(context, {
      className: "backtest-domain-header",
      tabs: [
        ...state.model.tabs.map(key => ({key, label: tabLabels[key]})),
        ...customTabs,
      ],
      active: state.activeTab,
      onChange: async key => {
        if (key === "custom-analysis:new") {
          try {
            const analysis = await state.customAnalyses.add();
            state.activeTab = state.customAnalyses.keyFor(analysis.tab_id);
          } catch (error) {
            context.showNotice?.(error.message || String(error), true);
          }
          renderLoaded(context, target, state);
          return;
        }
        state.activeTab = key;
        renderLoaded(context, target, state);
      },
    }).header;
    const content = document.createElement("div"); content.className = "backtest-domain-content";
    content.append(tabContent(context, state));
    target.replaceChildren(header, content);
    const requested = state.requestedSupplemental;
    if (requested && !state.supplementalRequestConsumed) {
      state.supplementalRequestConsumed = true;
      const targetInfo = requested.target || {};
      const entry = window.FTBacktestResultModel.resolveGroup(
        state.model.summary, targetInfo.strategy_id,
      );
      if (entry) {
        queueMicrotask(() => window.FTBacktestStrategyAnalysis.open(
          context, state.options, entry, targetInfo.analysis_tab || "overview",
        ));
      } else {
        context.showNotice?.(context.t("无法定位补充任务对应的策略"), true);
      }
    }
  }

  function section(context, options) {
    if (!supports(options.artifacts, options.resultSummary)) return null;
    const root = document.createElement("section");
    root.className = "job-section backtest-domain-results";
    const heading = document.createElement("h2"); heading.textContent = context.t("回测结果");
    const target = document.createElement("div");
    target.append(window.FTUI.loading(context.t("正在准备回测结果选项卡…")));
    root.append(heading, target);
    queueMicrotask(() => {
      try {
        const relevant = relevantArtifacts(options.artifacts);
        const artifactsByName = new Map(relevant.map(item => [String(item.name), item]));
        const model = window.FTBacktestResultModel.build(
          {}, options.resultSummary || {}, [...artifactsByName.keys()],
          options.resultDeclarations || [],
        );
        renderLoaded(context, target, {
          model, payloads: {}, artifactsByName, errors: {}, loading: new Set(),
          tablePages: {},
          activeTab: options.customAnalyses?.state?.requestedKey
            || model.tabs[0] || "summary",
          strategySelections: {},
          evaluationWindow: window.FTBacktestResultModel.evaluationWindow(
            model.summary, options.configuration || {},
          ),
          showOutOfSample: false,
          chartSelection: [], executionView: "orders", returnView: "cost_ratios",
          dimensionSelections: {},
          customAnalyses: options.customAnalyses || null,
          requestedSupplemental: options.supplementalRequest || null,
          supplementalRequestConsumed: false,
          options: {...options, resultSummary: model.summary},
        });
      } catch (error) {
        const failure = message(context, "回测结果初始化失败");
        const detail = String(error?.message || error || "").trim();
        if (detail) failure.append(document.createTextNode(`: ${detail}`));
        target.replaceChildren(failure);
      }
    });
    return root;
  }

  window.FTBacktestResults = Object.freeze({relevantArtifacts, section, supports});
})();
