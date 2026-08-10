(() => {
  const tabLabels = Object.freeze({
    summary: "回测汇总", equity: "净值与回撤", returns: "收益率",
    metrics: "时变指标", fees: "手续费", margin: "保证金",
    ratios: "收益与费用",
  });

  function relevantArtifacts(artifacts) {
    const names = new Set(window.FTBacktestResultModel.payloadNames);
    return (artifacts || []).filter(item => (
      item.state === "active" && names.has(String(item.name || ""))
    ));
  }

  function supports(artifacts) {
    return relevantArtifacts(artifacts).length > 0;
  }

  function previewPath(jobID, artifact, portQuery) {
    return `/api/jobs/${encodeURIComponent(jobID)}/artifacts/${encodeURIComponent(artifact.name)}/preview${portQuery}`;
  }

  async function loadPayloads(context, artifacts, jobID, portQuery) {
    const pairs = await Promise.all(relevantArtifacts(artifacts).map(async artifact => {
      const response = await context.raw(previewPath(jobID, artifact, portQuery));
      return [artifact.name, JSON.parse(await response.text())];
    }));
    return Object.fromEntries(pairs);
  }

  function message(context, value) {
    const node = document.createElement("p");
    node.className = "backtest-domain-empty";
    node.textContent = context.t(value);
    return node;
  }

  function format(value, kind = "number", currency = "") {
    const number = window.FTBacktestResultModel.finite(value);
    if (number == null) return "—";
    if (kind === "percent") return `${(number * 100).toFixed(2)}%`;
    if (kind === "currency") {
      return `${number.toLocaleString(undefined, {maximumFractionDigits: 2})} ${currency}`.trim();
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

  function chart(context, viewer, payload) {
    if (!payload) return message(context, "暂无曲线数据");
    const target = document.createElement("div");
    target.className = "backtest-domain-chart interactive-artifact-chart";
    queueMicrotask(() => {
      try { window.FTJobHighcharts.mount(context, target, payload, viewer); }
      catch (error) { target.replaceChildren(message(context, error.message)); }
    });
    return target;
  }

  function dataTable(context, rows) {
    if (!rows.length) return message(context, "暂无明细");
    const columns = [...new Set(rows.slice(0, 500).flatMap(row => Object.keys(row)))];
    return window.FTReportTables.render({
      columns, rows: rows.slice(0, 500), context,
      className: "backtest-domain-table",
      renderHeader: key => window.FTRichText.inline(String(key), context),
      renderCell: value => value && typeof value === "object"
        ? window.FTUI.code(value)
        : window.FTRichText.inline(String(value ?? ""), context),
      values: row => columns.map(key => row[key]),
    });
  }

  function tabContent(context, state) {
    const payloads = state.model.payloads;
    if (state.activeTab === "summary") return summaryTable(context, state.model);
    if (state.activeTab === "equity") {
      return chart(context, "equity_curve", payloads.equity_curve_data);
    }
    if (state.activeTab === "returns") {
      return chart(context, "line_chart", payloads.returns_over_time_data);
    }
    if (state.activeTab === "metrics") {
      return chart(context, "metrics_chart", payloads.metrics_over_time_data);
    }
    const artifact = {
      fees: "fee_detail_data", margin: "margin_detail_data",
      ratios: "ratio_detail_data",
    }[state.activeTab];
    return dataTable(context, window.FTBacktestResultModel.scopedRows(
      payloads[artifact], state.activeGroup,
    ));
  }

  function renderLoaded(context, target, state) {
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
    const content = document.createElement("div"); content.className = "backtest-domain-content";
    content.append(tabContent(context, state));
    target.replaceChildren(header, content);
  }

  function section(context, options) {
    if (!supports(options.artifacts)) return null;
    const root = document.createElement("section");
    root.className = "job-section backtest-domain-results";
    const heading = document.createElement("h2"); heading.textContent = context.t("回测结果");
    const target = document.createElement("div");
    target.append(window.FTUI.loading(context.t("正在读取回测结果…")));
    root.append(heading, target);
    queueMicrotask(async () => {
      try {
        const model = window.FTBacktestResultModel.build(await loadPayloads(
          context, options.artifacts, options.jobID, options.portQuery,
        ));
        renderLoaded(context, target, {
          model, activeTab: model.tabs[0] || "summary", activeGroup: "",
        });
      } catch (error) { target.replaceChildren(message(context, error.message)); }
    });
    return root;
  }

  window.FTBacktestResults = Object.freeze({relevantArtifacts, section, supports});
})();
