(() => {
  const dataArtifactNames = new Set([
    "ic_series_data", "ic_statistics_data", "ic_statistics_summary_data",
    "ic_rolling_stability_data", "ic_period_diagnostics_data",
    "ic_holding_half_life_data",
  ]);
  const tabs = [
    ["summary", "IC 汇总"], ["series", "IC 序列"], ["decay", "IC 衰减"],
    ["autocorrelation", "自相关"], ["rolling", "Rolling IC"],
    ["periods", "分期诊断"], ["holding_half_life", "持有期半衰期"],
    ["distribution", "IC 分布"],
  ];

  function relevantArtifacts(artifacts) {
    return (artifacts || []).filter(item => (
      item.state === "active" && dataArtifactNames.has(String(item.name || ""))
    ));
  }

  function supports(artifacts) {
    const names = new Set(relevantArtifacts(artifacts).map(item => item.name));
    return names.has("ic_series_data") || names.has("ic_statistics_data");
  }

  function previewPath(jobID, artifact, portQuery) {
    return `/api/jobs/${encodeURIComponent(jobID)}/artifacts/${encodeURIComponent(artifact.name)}/preview${portQuery}`;
  }

  async function payloads(context, artifacts, jobID, portQuery) {
    const pairs = await Promise.all(relevantArtifacts(artifacts).map(async artifact => {
      const response = await context.raw(previewPath(jobID, artifact, portQuery));
      return [artifact.name, JSON.parse(await response.text())];
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
    const url = window.FTJobArtifactViewers.referenceURL("factor", factor.factorRef);
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
    const factor = activeFactor(state);
    if (!factor) return empty(context, "暂无 IC 因子结果");
    if (state.activeTab === "summary") return summaryView(context, state, rerender);
    if (state.activeTab === "series") {
      return factor.series.length
        ? chartView(context, window.FTICResultCharts.seriesOptions(factor, context), true)
        : empty(context, "暂无 IC 序列");
    }
    if (state.activeTab === "decay") {
      return window.FTICResultModel.decay(factor).length
        ? chartView(context, window.FTICResultCharts.decayOptions(factor, context))
        : empty(context, "暂无多周期 IC 衰减数据");
    }
    if (state.activeTab === "autocorrelation") {
      return window.FTICResultModel.autocorrelation(
        factor, 20, state.model.summaryRows,
      ).length
        ? chartView(context, window.FTICResultCharts.autocorrelationOptions(
          factor, context, state.model.summaryRows,
        ))
        : empty(context, "IC 序列不足，无法估计自相关");
    }
    if (state.activeTab === "distribution") {
      return window.FTICResultModel.histogram(factor, state.model.summaryRows).length
        ? chartView(context, window.FTICResultCharts.histogramOptions(
          factor, context, state.model.summaryRows,
        ))
        : empty(context, "暂无 IC 分布数据");
    }
    if (state.activeTab === "holding_half_life") {
      const selected = state.model.halfLifeRows.filter(row => rowMatchesFactor(row, factor));
      return dataTable(context, selected.length ? selected : state.model.halfLifeRows);
    }
    const sourceRows = state.activeTab === "rolling"
      ? state.model.rollingRows : state.model.periodRows;
    const selected = sourceRows.filter(row => rowMatchesFactor(row, factor));
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
    state.model = {...state.rawModel, factors: ordered};
    state.model.matrix = window.FTICResultModel.statisticMatrix(
      ordered, state.rawModel.summaryRows,
    );
    const nav = document.createElement("div"); nav.className = "ic-domain-tabs";
    const content = document.createElement("div"); content.className = "ic-domain-content";
    const rerender = () => renderLoaded(context, target, state);
    tabs.forEach(([key, label]) => {
      const button = document.createElement("button"); button.type = "button";
      button.classList.toggle("active", state.activeTab === key);
      button.textContent = context.t(label);
      button.addEventListener("click", () => { state.activeTab = key; rerender(); });
      nav.append(button);
    });
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
          context, options.artifacts, options.jobID, options.portQuery,
        ));
        const factorOrder = rawModel.factors.map(item => item.key);
        renderLoaded(context, target, {
          rawModel, model: rawModel, factorOrder,
          activeFactorKey: factorOrder[0] || "", activeTab: "summary",
        });
      } catch (error) { target.replaceChildren(empty(context, error.message)); }
    });
    return root;
  }

  window.FTICResults = Object.freeze({dataArtifactNames, relevantArtifacts, section, supports});
})();
