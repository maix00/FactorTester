(() => {
  const tabLabels = Object.freeze({
    runtime: "策略运行摘要", summary: "回测汇总", group_metrics: "策略统计",
    equity: "净值与回撤", returns: "收益率",
    metrics: "时变指标", fees: "手续费", margin: "保证金",
    ratios: "收益与费用", orders: "订单", fills: "成交与结算",
    cash: "现金", positions: "持仓", exposure: "风险敞口",
    turnover: "换手率", drawdowns: "回撤区间", period_returns: "周期收益",
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

  function summaryTable(context, model) {
    if (!model.summaryRows.length) return message(context, "暂无回测汇总");
    const columns = [
      ["series", "组合", "text"], ["initial_equity", "初始权益", "currency"],
      ["final_equity", "期末权益", "currency"], ["total_return", "总收益率", "percent"],
      ["annual_return", "年化收益率", "percent"], ["sharpe_ratio", "Sharpe ratio", "number"],
      ["max_drawdown", "历史最大回撤", "percent"],
    ];
    return window.FTReportTables.render({
      columns: columns.map(item => item[0]), rows: model.summaryRows, context,
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

  function runtimeTable(context, model) {
    const rows = window.FTBacktestRuntimeModel.rows(model.summary);
    if (!rows.length) return null;
    const section = document.createElement("section");
    section.className = "backtest-runtime-summary";
    const heading = document.createElement("h3");
    heading.textContent = context.t("策略运行摘要");
    const table = window.FTReportTables.render({
      columns: ["type", "status", "detail"], rows, context,
      className: "backtest-domain-table backtest-runtime-table",
      renderHeader: key => document.createTextNode(context.t({
        type: "类型", status: "状态", detail: "说明",
      }[key])),
      renderCell: value => window.FTRichText.inline(String(value ?? ""), context),
      values: row => [row.type, row.status, row.detail],
    });
    section.append(heading, table);
    return section;
  }

  function chart(context, viewer, payload, displayOptions = {}) {
    if (!payload) return message(context, "暂无曲线数据");
    const target = document.createElement("div");
    target.className = "backtest-domain-chart interactive-artifact-chart";
    queueMicrotask(() => {
      try { window.FTJobHighcharts.mount(context, target, payload, viewer, displayOptions); }
      catch (error) { target.replaceChildren(message(context, error.message)); }
    });
    return target;
  }

  function groupMetricsTable(context, state) {
    const matrix = state.model.metricMatrix;
    if (!matrix.entries.length) return message(context, "暂无分组指标");
    const result = window.FTUI.table([
      context.t("指标"), ...matrix.entries.map(item => item.label),
    ]);
    result.shell.classList.add("backtest-metric-matrix");
    [...result.table.tHead.rows[0].cells].slice(1).forEach((cell, index) => {
      const entry = matrix.entries[index];
      const button = document.createElement("button");
      button.type = "button"; button.textContent = entry.label;
      button.title = context.t("查看分组详情");
      button.className = "backtest-group-heading";
      button.classList.toggle("active", state.activeGroup === entry.label);
      button.addEventListener("click", () => {
        window.FTBacktestGroupDetail.open(context, state.options, entry);
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
          if (state.activeGroup && state.activeGroup === entry.label) {
            cell.classList.add("selected-group");
          }
        });
      });
    });
    return result.shell;
  }

  function dataTable(context, rows, state) {
    if (!rows.length) return message(context, "暂无明细");
    const columns = [...new Set(rows.slice(0, 500).flatMap(row => Object.keys(row)))];
    const page = Number(state.tablePages[state.activeTab] || 1);
    const values = rows.map(row => columns.map(key => {
      const value = row[key];
      return value && typeof value === "object"
        ? window.FTUI.code(value)
        : window.FTRichText.inline(String(value ?? ""), context);
    }));
    const table = window.FTUI.pagedTable(columns.map(key => context.t(key)), values, {
      page, pageSize: 20,
      previousLabel: context.t("上一页"), nextLabel: context.t("下一页"),
      pageLabel: (current, total) => `${current} / ${total}`,
      totalLabel: total => `${context.t("共")} ${total} ${context.t("行")}`,
      onPageChange: next => {
        state.tablePages[state.activeTab] = next;
        renderLoaded(context, state.target, state);
      },
    });
    table.shell.classList.add("backtest-domain-table");
    return table.shell;
  }

  function tabContent(context, state) {
    const payloads = state.model.payloads;
    if (state.activeTab === "runtime") {
      return runtimeTable(context, state.model) || message(context, "暂无策略运行摘要");
    }
    if (state.activeTab === "summary") return summaryTable(context, state.model);
    if (state.activeTab === "group_metrics") return groupMetricsTable(context, state);
    if (state.activeTab === "equity") {
      return chart(context, "equity_curve", payloads.equity_curve_data, {
        ...state.evaluationWindow, showOutOfSample: state.showOutOfSample,
      });
    }
    if (state.activeTab === "returns") {
      return chart(context, "line_chart", payloads.returns_over_time_data, {
        ...state.evaluationWindow, showOutOfSample: state.showOutOfSample,
      });
    }
    if (state.activeTab === "metrics") {
      return chart(context, "metrics_chart", payloads.metrics_over_time_data, {
        ...state.evaluationWindow, showOutOfSample: state.showOutOfSample,
      });
    }
    const artifact = window.FTBacktestResultModel.tabPayloads[state.activeTab];
    return dataTable(context, window.FTBacktestResultModel.scopedRows(
      payloads[artifact], state.activeGroup,
    ), state);
  }

  function activeArtifact(state) {
    const name = window.FTBacktestResultModel.tabPayloads[state.activeTab];
    if (!name || state.payloads[name]) return null;
    return state.artifactsByName.get(name) || null;
  }

  function loadActiveTab(context, state) {
    const artifact = activeArtifact(state);
    if (!artifact || state.loading.has(artifact.name)) return;
    state.loading.add(artifact.name);
    loadPayload(
      context, artifact, state.options.jobID, state.options.artifactQuery || "",
    ).then(payload => {
      state.payloads[artifact.name] = payload;
      state.model = window.FTBacktestResultModel.build(
        state.payloads, state.model.summary, [...state.artifactsByName.keys()],
      );
    }).catch(error => {
      state.errors[artifact.name] = error;
    }).finally(() => {
      state.loading.delete(artifact.name);
      if (state.target?.isConnected !== false) renderLoaded(context, state.target, state);
    });
  }

  function renderLoaded(context, target, state) {
    state.target = target;
    const header = document.createElement("div");
    header.className = "backtest-domain-header";
    const tabs = document.createElement("div"); tabs.className = "backtest-domain-tabs";
    state.model.tabs.forEach(key => {
      const button = document.createElement("button"); button.type = "button";
      button.textContent = context.t(tabLabels[key]);
      button.classList.toggle("active", state.activeTab === key);
      button.addEventListener("click", () => {
        state.activeTab = key; renderLoaded(context, target, state);
      });
      tabs.append(button);
    });
    header.append(tabs);
    if (state.model.groups.length > 1) {
      const select = document.createElement("select");
      select.append(new Option(context.t("全部组合"), ""));
      state.model.groups.forEach(group => select.append(new Option(group, group)));
      select.value = state.activeGroup;
      select.addEventListener("change", () => {
        state.activeGroup = select.value; renderLoaded(context, target, state);
      });
      header.append(select);
    }
    if (state.evaluationWindow) {
      header.append(window.FTUI.actionButton(
        context.t(state.showOutOfSample ? "仅显示样本内" : "显示样本外"),
        () => {
          state.showOutOfSample = !state.showOutOfSample;
          renderLoaded(context, target, state);
        },
        {variant: "secondary"},
      ));
    }
    const activeEntry = window.FTBacktestResultModel.resolveGroup(
      state.model.summary, state.activeGroup || state.model.groupEntries[0]?.label,
    );
    if (activeEntry) {
      const actions = document.createElement("div");
      actions.className = "backtest-domain-actions";
      actions.append(
        window.FTUI.actionButton(context.t("分组详情"), () => (
          window.FTBacktestGroupDetail.open(context, state.options, activeEntry)
        ), {variant: "secondary"}),
        window.FTUI.actionButton(context.t("排序诊断"), () => (
          window.FTBacktestRankingView.open(context, state.options, activeEntry)
        ), {variant: "secondary"}),
      );
      if (window.FTBacktestResultModel.initialSnapshot(state.model.summary)) {
        actions.append(window.FTUI.actionButton(context.t("持仓快照"), () => (
          window.FTBacktestSnapshotView.open(context, state.options)
        ), {variant: "secondary"}));
      }
      header.append(actions);
    }
    const content = document.createElement("div"); content.className = "backtest-domain-content";
    const artifact = activeArtifact(state);
    const payloadName = window.FTBacktestResultModel.tabPayloads[state.activeTab];
    const error = payloadName ? state.errors[payloadName] : null;
    if (error) content.append(message(context, error.message));
    else if (artifact) {
      content.append(window.FTUI.loading(context.t("正在读取所选结果…")));
      queueMicrotask(() => loadActiveTab(context, state));
    } else content.append(tabContent(context, state));
    target.replaceChildren(header, content);
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
      const relevant = relevantArtifacts(options.artifacts);
      const artifactsByName = new Map(relevant.map(item => [String(item.name), item]));
      const model = window.FTBacktestResultModel.build(
        {}, options.resultSummary || {}, [...artifactsByName.keys()],
      );
      renderLoaded(context, target, {
        model, payloads: {}, artifactsByName, errors: {}, loading: new Set(),
        tablePages: {}, activeTab: model.tabs[0] || "summary", activeGroup: "",
        evaluationWindow: window.FTBacktestResultModel.evaluationWindow(
          model.summary, options.configuration || {},
        ),
        showOutOfSample: false,
        options: {...options, resultSummary: model.summary},
      });
    });
    return root;
  }

  window.FTBacktestResults = Object.freeze({relevantArtifacts, section, supports});
})();
