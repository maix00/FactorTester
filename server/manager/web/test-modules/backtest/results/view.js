(() => {
  const tabLabels = Object.freeze({
    overview: "概览", strategy_stats: "策略统计", time_series: "时变指标",
    execution_account: "交易与账户", return_analysis: "收益与风险",
    runtime_summary: "运行摘要",
  });

  function relevantArtifacts(artifacts) {
    const names = new Set(window.FTBacktestResultModel.payloadNames);
    return (artifacts || []).filter(item => (
      item.state === "active" && names.has(String(item.name || ""))
    ));
  }

  function supports(artifacts, summary = {}, declarations = []) {
    return relevantArtifacts(artifacts).length > 0
      || Boolean(summary?.metrics && Object.keys(summary.metrics).length)
      || Boolean(window.FTRuntimeSummary?.rows?.(summary).length)
      || declarations.some(item => item?.result_surface);
  }

  function artifactPath(jobID, artifact, artifactQuery) {
    return `/api/jobs/${encodeURIComponent(jobID)}/artifacts/${encodeURIComponent(artifact.name)}${artifactQuery}`;
  }

  function artifactDataPath(state, name) {
    return artifactPath(
      state.options.jobID, state.artifactsByName.get(name),
      state.options.artifactQuery || "",
    );
  }

  function chartQueryMode(name) {
    return ["equity_curve_data", "returns_over_time_data"].includes(name)
      ? "series" : "time_rows";
  }

  async function ensureChartPayloads(context, state, names) {
    const pending = [...new Set(names)].filter(name => (
      state.artifactsByName.has(name)
      && !state.chartPayloads[name]
      && !state.chartLoading.has(name)
    ));
    if (!pending.length) return;
    pending.forEach(name => state.chartLoading.add(name));
    await Promise.all(pending.map(async name => {
      try {
        const source = window.FTJobArtifactQuery.timeSource(
          context, artifactDataPath(state, name),
          {mode: chartQueryMode(name), maxPoints: 800},
        );
        const payload = await source.load();
        if (payload) state.chartPayloads[name] = payload;
        delete state.chartErrors[name];
      } catch (error) {
        if (error?.name !== "AbortError") state.chartErrors[name] = error;
      } finally {
        state.chartLoading.delete(name);
      }
    }));
    if (state.target?.isConnected !== false) renderLoaded(context, state.target, state);
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

  function remoteDataTable(
    context, state, artifact, pageKey, request = {}, options = {},
  ) {
    const target = document.createElement("div");
    target.className = "backtest-result-lazy-target";
    const page = Number(state.tablePages[pageKey] || 1);
    const fingerprint = JSON.stringify({artifact, page, request});
    const cached = state.remoteTableData.get(pageKey);
    const error = state.remoteTableErrors.get(fingerprint);
    const ready = cached?.fingerprint === fingerprint ? cached.data : null;
    if (error) target.append(message(context, error.message || String(error)));
    else if (!ready) {
      target.append(window.FTUI.loading(context.t("正在读取当前页…")));
      if (!state.remoteTableLoading.has(fingerprint)) {
        state.remoteTableLoading.add(fingerprint);
        queueMicrotask(async () => {
          try {
            let source = state.tableSources.get(artifact);
            if (!source) {
              source = window.FTJobArtifactQuery.tableSource(
                context, artifactDataPath(state, artifact), {pageSize: 20},
              );
              state.tableSources.set(artifact, source);
            }
            const data = await source.page(page, request);
            state.remoteTableData.set(pageKey, {fingerprint, data});
            state.remoteTableErrors.delete(fingerprint);
          } catch (loadError) {
            state.remoteTableErrors.set(fingerprint, loadError);
          } finally {
            state.remoteTableLoading.delete(fingerprint);
          }
          if (state.target?.isConnected !== false) {
            renderLoaded(context, state.target, state);
          }
        });
      }
    } else {
      target.append(window.FTJobArtifactQuery.pagedTable(context, ready, {
        className: "backtest-domain-table",
        renderCell(value) {
          return value && typeof value === "object"
            ? window.FTUI.code(value)
            : window.FTRichText.inline(String(value ?? ""), context);
        },
        onPageChange(next) {
          state.tablePages[pageKey] = next;
          state.remoteTableData.delete(pageKey);
          renderLoaded(context, state.target, state);
        },
      }));
    }
    return {element: target, data: ready};
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
    const standard = FTJobResultTabs.standardContent(
      context, state.activeTab, state.model.summary, {
        filterRows: rows => state.strategyScope.filterRows(rows),
        page: state.tablePages.runtime,
        onPageChange: next => { state.tablePages.runtime = next; renderLoaded(context, state.target, state); },
      },
    );
    if (standard) return standard;
    if (["time_series", "execution_account", "return_analysis"].includes(state.activeTab)) {
      const declarations = (state.options.resultDeclarations || []).filter(item => (
        String(item?.result_surface || "") === state.activeTab
      ));
      const available = declarations.some(item => (
        state.artifactsByName.has(String(item?.canonical_artifact || ""))
      ));
      if (declarations.length && !available) {
        const requests = declarations.map(item => String(item.name || "")).filter(Boolean);
        const canGenerate = requests.length > 0
          && declarations.every(item => item.after_run === true);
        return FTJobResultTabs.missingOutput(context, {
          canGenerate,
          onGenerate: canGenerate ? () => FTJobGeneration.generate(context, {
            jobID: state.options.jobID,
            artifactQuery: state.options.artifactQuery,
            executionQuery: state.options.executionQuery,
            onGenerated: state.options.onGenerated,
          }, requests) : null,
        });
      }
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

  async function queryEventPayloads(context, state, names, range = null) {
    const output = {};
    await Promise.all(names.map(async name => {
      let source = state.eventSources.get(name);
      if (!source) {
        source = window.FTJobArtifactQuery.timeSource(
          context, artifactDataPath(state, name), {
            mode: "time_rows", maxPoints: 200,
          },
        );
        state.eventSources.set(name, source);
      }
      const request = range ? {min: range.min, max: range.max, maxPoints: 200} : {
        maxPoints: 200,
      };
      const data = await source.load(request);
      if (data) output[name] = data;
    }));
    return output;
  }

  async function ensureEventPayloads(context, state, names) {
    const pending = [...new Set(names)].filter(name => (
      state.artifactsByName.has(name) && !state.eventLoading.has(name)
    ));
    if (!pending.length) return;
    pending.forEach(name => state.eventLoading.add(name));
    try {
      Object.assign(
        state.eventPayloads,
        await queryEventPayloads(context, state, pending),
      );
      pending.forEach(name => delete state.eventErrors[name]);
    } catch (error) {
      pending.forEach(name => { state.eventErrors[name] = error; });
    } finally {
      pending.forEach(name => state.eventLoading.delete(name));
    }
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
    state.ensureChartPayloads = names => ensureChartPayloads(context, state, names);
    state.ensureEventPayloads = names => ensureEventPayloads(context, state, names);
    state.chartSource = (artifact, definition) => {
      const key = `${artifact}:${definition.view || definition.viewer || "series"}`;
      if (!state.chartSources.has(key)) {
        state.chartSources.set(key, window.FTJobArtifactQuery.timeSource(
          context, artifactDataPath(state, artifact), {
            mode: chartQueryMode(artifact), maxPoints: 800,
          },
        ));
      }
      return state.chartSources.get(key);
    };
    state.openEventFlow = timestamp => {
      const view = window.FTBacktestAnalysisUI.dialog(context, "交易事件", "");
      view.body.append(window.FTUI.loading(context.t("正在读取交易事件…")));
      const names = window.FTBacktestEventFlow.coreSources
        .map(([name]) => name).filter(name => state.artifactsByName.has(name));
      const exact = Number(timestamp);
      const range = Number.isFinite(exact) ? {min: exact, max: exact} : null;
      void queryEventPayloads(context, state, names, range)
        .then(payloads => {
          if (view.root.isConnected) window.FTBacktestEventFlow.render(
            context, view.body, payloads, state.strategyScope, {timestamp},
          );
        })
        .catch(error => {
          if (view.root.isConnected) view.body.replaceChildren(
            message(context, error?.message || String(error)),
          );
        });
    };
    state.helpers = {dataTable, message, remoteDataTable};
    const customTabs = state.customAnalyses?.tabs({
      onDeleted: () => {
        state.activeTab = state.model.tabs[0] || "overview";
        renderLoaded(context, target, state);
      },
    }) || [];
    const tabs = FTJobResultTabs.compose({
      tabs: state.model.tabs.map(key => ({key, label: tabLabels[key]})),
      resultSummary: state.model.summary, customTabs,
    });
    state.activeTab = FTJobResultTabs.active(tabs, state.activeTab, "overview");
    const header = window.FTJobResultTabs.create(context, {
      className: "backtest-domain-header",
      tabs,
      active: state.activeTab,
      onChange: key => void FTJobResultTabs.activate(context, key, {
        customAnalyses: state.customAnalyses,
        onActive: next => { state.activeTab = next; renderLoaded(context, target, state); },
      }),
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
    if (!supports(
      options.artifacts, options.resultSummary, options.resultDeclarations || [],
    )) return null;
    const root = document.createElement("section");
    root.className = "job-section backtest-domain-results";
    const target = document.createElement("div");
    target.append(window.FTUI.loading(context.t("正在准备回测结果选项卡…")));
    root.append(target);
    queueMicrotask(() => {
      try {
        const relevant = relevantArtifacts(options.artifacts);
        const artifactsByName = new Map(relevant.map(item => [String(item.name), item]));
        const model = window.FTBacktestResultModel.build(
          {}, options.resultSummary || {}, [...artifactsByName.keys()],
          options.resultDeclarations || [],
        );
        renderLoaded(context, target, {
          model, artifactsByName,
          chartPayloads: {}, chartErrors: {}, chartLoading: new Set(),
          chartSources: new Map(),
          eventPayloads: {}, eventErrors: {}, eventLoading: new Set(),
          eventSources: new Map(),
          tableSources: new Map(), remoteTableData: new Map(),
          remoteTableErrors: new Map(), remoteTableLoading: new Set(),
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
