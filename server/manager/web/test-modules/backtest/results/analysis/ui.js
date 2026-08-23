(() => {
  function finite(value) {
    const number = Number(value);
    return value == null || value === "" || !Number.isFinite(number) ? null : number;
  }

  function percent(value, digits = 3) {
    const number = finite(value);
    return number == null ? "—" : `${(number * 100).toFixed(digits)}%`;
  }

  function basisPoints(value) {
    const number = finite(value);
    return number == null ? "—" : `${(number * 10000).toFixed(5)} bp`;
  }

  function number(value, digits = 4) {
    const result = finite(value);
    return result == null ? "—" : result.toLocaleString(undefined, {
      maximumFractionDigits: digits,
    });
  }

  function product(value) {
    if (!value) return "—";
    if (typeof value === "string") return value;
    const name = String(value.name || value.alias || "");
    const description = String(value.desc || value.description || "");
    return description && description !== name ? `${name} · ${description}` : name || "—";
  }

  function timestamp(value) {
    return window.FTUI.formatDate(value) || String(value || "—");
  }

  function dialog(context, title, subtitle = "") {
    const root = document.createElement("dialog");
    root.className = "backtest-analysis-dialog";
    const card = document.createElement("article");
    card.className = "dialog-card backtest-analysis-card";
    const close = document.createElement("button");
    close.type = "button"; close.className = "dialog-close";
    close.textContent = "×"; close.title = context.t("关闭");
    const heading = document.createElement("header");
    heading.className = "backtest-analysis-title";
    const name = document.createElement("h2"); name.textContent = context.t(title);
    heading.append(name);
    if (subtitle) {
      const copy = document.createElement("p"); copy.textContent = subtitle; heading.append(copy);
    }
    const body = document.createElement("div"); body.className = "backtest-analysis-body";
    if (body.dataset) body.dataset.ftScrollState = "backtest-analysis";
    close.addEventListener("click", () => root.close());
    root.addEventListener("close", () => root.remove());
    root.addEventListener("cancel", event => { event.preventDefault(); root.close(); });
    card.append(close, heading, body); root.append(card); document.body.append(root);
    root.showModal();
    return {root, card, body, heading};
  }

  function cards(context, rows) {
    const root = document.createElement("div"); root.className = "backtest-analysis-cards";
    rows.forEach(([label, value]) => {
      const item = document.createElement("div"); item.className = "backtest-analysis-card-item";
      const name = document.createElement("small"); name.textContent = context.t(label);
      const result = document.createElement("strong"); result.textContent = String(value ?? "—");
      item.append(name, result); root.append(item);
    });
    return root;
  }

  function table(context, columns, rows, options = {}) {
    if (!Array.isArray(rows) || !rows.length) {
      const empty = document.createElement("p"); empty.className = "backtest-domain-empty";
      empty.textContent = context.t(options.empty || "暂无数据"); return empty;
    }
    const result = window.FTUI.table(columns.map(column => context.t(column.label)));
    result.shell.classList.add("backtest-analysis-table");
    rows.forEach(row => {
      const element = window.FTUI.appendRow(result.body, columns.map(column => {
        const value = typeof column.value === "function" ? column.value(row) : row?.[column.key];
        return value instanceof Node ? value : String(value ?? "—");
      }));
      const rowClass = typeof options.rowClass === "function"
        ? options.rowClass(row) : options.rowClass;
      if (rowClass) element.classList.add(...String(rowClass).split(/\s+/).filter(Boolean));
    });
    return result.shell;
  }

  function section(context, title, summary, render, open = false) {
    const details = document.createElement("details");
    details.className = "backtest-analysis-section"; details.open = open;
    const heading = document.createElement("summary");
    const titleNode = document.createElement("strong"); titleNode.textContent = context.t(title);
    const summaryNode = document.createElement("span"); summaryNode.textContent = context.t(summary);
    heading.append(titleNode, summaryNode);
    const body = document.createElement("div"); body.className = "backtest-analysis-section-body";
    let loaded = false;
    const load = () => {
      if (loaded) return;
      loaded = true;
      try {
        const value = render();
        if (value) body.append(value);
      } catch (error) {
        body.append(Object.assign(document.createElement("p"), {textContent: error.message}));
      }
    };
    details.addEventListener("toggle", () => { if (details.open) load(); });
    details.append(heading, body); if (open) queueMicrotask(load);
    return details;
  }

  function chart(target, options, stock = false) {
    queueMicrotask(() => {
      if (!window.Highcharts) {
        target.textContent = "Highcharts 组件未加载"; return;
      }
      target._ftChart?.destroy?.();
      target._ftChart = stock && window.Highcharts.stockChart
        ? window.Highcharts.stockChart(target, options)
        : window.Highcharts.chart(target, options);
    });
    return target;
  }

  function chartNode(className = "") {
    const target = document.createElement("div");
    target.className = `backtest-analysis-chart ${className}`.trim();
    return target;
  }

  function baseChart(series, yTitle = "") {
    return {
      chart: {backgroundColor: "transparent", zooming: {type: "x"}},
      time: {useUTC: false},
      title: {text: null}, credits: {enabled: false},
      legend: {enabled: true}, xAxis: {type: "datetime", ordinal: false},
      yAxis: {title: {text: yTitle}}, tooltip: {shared: true},
      plotOptions: {series: {animation: false, boostThreshold: 1000, turboThreshold: 0}},
      series,
    };
  }

  window.FTBacktestAnalysisUI = Object.freeze({
    baseChart, basisPoints, cards, chart, chartNode, dialog, finite,
    number, percent, product, section, table, timestamp,
  });
})();
