(() => {
  const ui = () => window.FTBacktestAnalysisUI;

  function stack(...nodes) {
    const root = document.createElement("div"); root.className = "backtest-analysis-stack";
    nodes.flat().filter(Boolean).forEach(node => root.append(node)); return root;
  }

  function note(value) {
    const node = document.createElement("p"); node.className = "backtest-analysis-note";
    node.textContent = value; return node;
  }

  function summary(context, value) {
    const rows = [
      ["总收益率", ui().percent(value?.["Total Return"])],
      ["平均收益率", ui().percent(value?.["Mean Return"])],
      ["胜率", ui().percent(value?.["Win Rate"])],
      ["年化波动率", ui().percent(value?.Volatility)],
      ["历史最大回撤", ui().percent(value?.["Max Drawdown"])],
      ["平均换手率", ui().percent(value?.["Avg Turnover"])],
      ["Sharpe ratio", ui().number(value?.["Sharpe Ratio"])],
      ["Calmar ratio", ui().number(value?.["Calmar Ratio"])],
    ];
    return ui().cards(context, rows);
  }

  function returnChart(context, rows) {
    const values = Array.isArray(rows) ? rows : [];
    const points = (key, scale = 1) => values.flatMap((row, index) => {
      const value = ui().finite(row?.[key]);
      const timestamp = Date.parse(String(row?.timestamp || ""));
      return value == null ? [] : [[Number.isFinite(timestamp) ? timestamp : index, value * scale]];
    });
    const target = ui().chartNode();
    const options = ui().baseChart([
      {name: context.t("单期收益"), type: "column", data: points("return", 100)},
      {name: context.t("累计净值"), type: "line", yAxis: 1, data: points("cumulative_return")},
    ], context.t("单期收益（%）"));
    options.yAxis = [options.yAxis, {title: {text: context.t("累计净值")}, opposite: true}];
    options.tooltip = {shared: true};
    return ui().chart(target, options, true);
  }

  function frequency(context, rows) {
    return ui().table(context, [
      {label: "产品", value: row => productIdentity(row.product)},
      {label: "产品描述", value: row => productDescription(row.product)},
      {label: "入组次数", value: row => ui().number(row.count, 0)},
      {label: "进入比例", value: row => ui().percent(row.frequency)},
      {label: "平均收益", value: row => ui().basisPoints(row.mean_return)},
      {label: "开仓费率", value: row => ui().basisPoints(row.product?.fee?.open)},
      {label: "平今费率", value: row => ui().basisPoints(row.product?.fee?.close_today)},
      {label: "平昨费率", value: row => ui().basisPoints(
        row.product?.fee?.close_yesterday ?? row.product?.fee?.close,
      )},
    ], rows, {empty: "暂无产品进入频率", rowClass: feeCoverageClass});
  }

  function distribution(context, value) {
    const histogram = value?.histogram || [];
    const target = ui().chartNode("compact");
    const options = {
      chart: {type: "column", backgroundColor: "transparent"},
      title: {text: null}, credits: {enabled: false}, legend: {enabled: false},
      xAxis: {categories: histogram.map(row => (
        `${ui().percent(row.left, 2)} – ${ui().percent(row.right, 2)}`
      )), labels: {rotation: -35}},
      yAxis: {title: {text: context.t("期数")}},
      series: [{name: context.t("期数"), data: histogram.map(row => row.count || 0)}],
    };
    const quantiles = value?.quantiles || {};
    return stack(
      ui().cards(context, [
        ["P05", ui().percent(quantiles.p05)], ["P25", ui().percent(quantiles.p25)],
        ["P50", ui().percent(quantiles.p50)], ["P75", ui().percent(quantiles.p75)],
        ["P95", ui().percent(quantiles.p95)], ["样本数", ui().number(value?.period_count, 0)],
      ]),
      ui().chart(target, options),
    );
  }

  function rolling(context, value) {
    const rows = value?.rows || [];
    const target = ui().chartNode("compact");
    const series = rows.flatMap((row, index) => {
      const result = ui().finite(row.return);
      const time = Date.parse(String(row.timestamp || ""));
      return result == null ? [] : [[Number.isFinite(time) ? time : index, result * 100]];
    });
    return stack(
      ui().cards(context, [
        ["窗口长度", ui().number(value?.window_size, 0)],
        ["负收益窗口占比", ui().percent(value?.negative_window_ratio)],
      ]),
      ui().chart(target, ui().baseChart([
        {name: context.t("窗口累计收益"), data: series},
      ], context.t("收益率（%）"))),
    );
  }

  function capacity(context, value) {
    return ui().cards(context, [
      ["平均成员数", ui().number(value?.mean_count, 2)],
      ["中位成员数", ui().number(value?.median_count, 2)],
      ["最少成员数", ui().number(value?.min_count, 0)],
      ["空组占比", ui().percent(value?.empty_ratio)],
      ["成员数不超过 2 的占比", ui().percent(value?.tiny_group_ratio)],
    ]);
  }

  function tradability(context, value) {
    return stack(
      ui().cards(context, [
        ["平均资金换手", ui().percent(value?.avg_trade_notional_ratio)],
        ["中位资金换手", ui().percent(value?.median_trade_notional_ratio)],
        ["平均实际费率成本", ui().percent(value?.avg_actual_fee_cost)],
        ["成交额加权实际费率", ui().basisPoints(value?.actual_fee_per_traded_notional)],
        ["Break-even 成本", ui().basisPoints(value?.break_even_fee)],
      ]),
      ui().table(context, [
        {label: "单边等比例成本", value: row => ui().basisPoints(row.fee)},
        {label: "累计收益", value: row => ui().percent(row.total_return)},
      ], value?.sensitivity || [], {empty: "暂无费率敏感性数据"}),
    );
  }

  function calendar(context, value) {
    const columns = key => [
      {label: key === "month" ? "月份" : key === "day" ? "月内日期" : "年份", key},
      {label: "期数", value: row => ui().number(row.count, 0)},
      {label: "平均收益", value: row => ui().percent(row.mean)},
      {label: "累计收益", value: row => ui().percent(row.sum)},
    ];
    const grid = document.createElement("div"); grid.className = "backtest-analysis-grid";
    grid.append(
      ui().table(context, columns("month"), value?.month_rows || []),
      ui().table(context, columns("day"), value?.day_rows || []),
      ui().table(context, columns("year"), value?.year_rows || []),
    );
    return stack(
      ui().cards(context, [["最强月份集中度", ui().percent(value?.month_concentration_ratio)]]),
      grid,
    );
  }

  function holding(context, value) {
    return ui().cards(context, [
      ["持有段数", ui().number(value?.run_count, 0)],
      ["平均持有期", ui().number(value?.mean_periods, 2)],
      ["中位持有期", ui().number(value?.median_periods, 2)],
      ["P95 持有期", ui().number(value?.p95_periods, 2)],
    ]);
  }

  function explanations(context, rows) {
    const list = document.createElement("ul"); list.className = "backtest-analysis-list";
    (rows || []).forEach(value => list.append(Object.assign(document.createElement("li"), {
      textContent: String(value),
    })));
    return list.children.length ? list : note(context.t("当前未识别到明显集中性风险"));
  }

  function productDescription(product) {
    if (!product || typeof product === "string") return "—";
    const name = String(product.name || product.alias || "");
    const description = String(product.desc || product.description || "");
    return description && description !== name ? description : "—";
  }

  function productIdentity(product) {
    if (!product || typeof product === "string") return ui().product(product);
    const root = document.createElement("div");
    root.className = "backtest-product-identity";
    const name = document.createElement("span");
    name.textContent = String(product.name || product.alias || "—");
    root.append(name);
    const sources = Array.isArray(product.source_names) ? product.source_names : [];
    if (sources.length) {
      const detail = document.createElement("small");
      detail.textContent = sources.join("、");
      root.append(detail);
    }
    return root;
  }

  function roundTripFee(row) {
    const fee = row?.product?.fee || {};
    const declared = ui().finite(fee.total);
    if (declared != null) return declared;
    const open = ui().finite(fee.open);
    const close = ui().finite(fee.close_today ?? fee.close_yesterday ?? fee.close);
    return open == null || close == null ? null : open + close;
  }

  function feeCoverageClass(row) {
    const returnValue = ui().finite(row?.mean_active_contribution ?? row?.mean_return);
    const fee = roundTripFee(row);
    return returnValue != null && fee != null && returnValue > fee
      ? "backtest-fee-covered" : "";
  }

  function contributionTable(context, rows) {
    const first = rows?.[0] || {};
    const weighted = Boolean(first.product?.fee?._is_weighted || first.market_rule?._is_weighted);
    const table = ui().table(context, [
      {label: "产品", value: row => productIdentity(row.product)},
      {label: "描述", value: row => productDescription(row.product)},
      {label: "平均收益", value: row => ui().basisPoints(row.mean_return)},
      {label: "开仓费率", value: row => ui().basisPoints(row.product?.fee?.open)},
      {label: "平今费率", value: row => ui().basisPoints(row.product?.fee?.close_today)},
      {label: "平昨费率", value: row => ui().basisPoints(
        row.product?.fee?.close_yesterday ?? row.product?.fee?.close,
      )},
      {label: "合约乘数", value: row => ui().number(row.market_rule?.multiplier)},
      {label: "最小手数", value: row => ui().number(row.market_rule?.lot_size)},
      {label: "保证金率", value: row => ui().percent(row.market_rule?.margin_ratio)},
      {label: "活跃期数", value: row => ui().number(row.active_period_count, 0)},
      {label: "毛收益贡献", value: row => ui().percent(row.gross_contribution)},
      {label: "活跃期平均贡献", value: row => ui().basisPoints(row.mean_active_contribution)},
    ], rows, {empty: "暂无产品贡献", rowClass: feeCoverageClass});
    return weighted ? stack(note(context.t("费率与市场规则为持仓加权值")), table) : table;
  }

  function productAnalysis(context, value) {
    const byLevel = value?.by_level || {};
    const levels = ["products", "contracts"].filter(key => byLevel[key]);
    let level = levels.includes(value?.default_level) ? value.default_level : levels[0];
    if (!level) return contributionTable(context, value?.rows || []);
    const root = document.createElement("div"); root.className = "backtest-analysis-stack";
    const buttons = document.createElement("div"); buttons.className = "backtest-analysis-switch";
    const content = document.createElement("div");
    const render = () => {
      const current = byLevel[level] || {};
      [...buttons.children].forEach(button => button.classList.toggle(
        "active", button.dataset.level === level,
      ));
      content.replaceChildren(
        note(`${context.t("最强 1 项贡献正毛收益")} ${ui().percent(current.top1_positive_contribution_ratio)} · ${context.t("最强 3 项")} ${ui().percent(current.top3_positive_contribution_ratio)}`),
        Object.assign(document.createElement("h4"), {textContent: context.t("正贡献")}),
        contributionTable(context, current.top_products || []),
        Object.assign(document.createElement("h4"), {textContent: context.t("负贡献")}),
        contributionTable(context, current.bottom_products || []),
      );
    };
    levels.forEach(key => {
      const button = document.createElement("button"); button.type = "button";
      button.dataset.level = key; button.textContent = context.t(key === "products" ? "品种" : "合约");
      button.addEventListener("click", () => { level = key; render(); }); buttons.append(button);
    });
    root.append(buttons, content); render(); return root;
  }

  function dayRows(context, rows) {
    return ui().table(context, [
      {label: "日期", value: row => row.date || ui().timestamp(row.timestamp)},
      {label: "期数", value: row => ui().number(row.count, 0)},
      {label: "平均收益", value: row => ui().percent(row.mean)},
      {label: "累计收益", value: row => ui().percent(row.sum)},
    ], rows);
  }

  function daily(context, value) {
    return stack(
      note(`${context.t("去掉最高 1 日")} ${ui().percent(value?.return_without_top1_day)} · ${context.t("去掉最高 5 日")} ${ui().percent(value?.return_without_top5_days)}`),
      Object.assign(document.createElement("h4"), {textContent: context.t("贡献最高")}),
      dayRows(context, value?.top_days || []),
      Object.assign(document.createElement("h4"), {textContent: context.t("贡献最低")}),
      dayRows(context, value?.bottom_days || []),
    );
  }

  function robustness(context, summaryValue, periods) {
    const issues = (summaryValue?.issues || []).join("、") || context.t("未见明显集中性风险");
    return stack(
      ui().cards(context, [
        ["去掉最好 1% 时段", ui().percent(periods?.without_top1pct?.remaining_return)],
        ["去掉最好 5% 时段", ui().percent(periods?.without_top5pct?.remaining_return)],
        ["脆弱性判断", summaryValue?.is_fragile ? context.t("存在集中性风险") : context.t("未见明显集中性风险")],
      ]), note(`${context.t("主要风险")}：${issues}`),
    );
  }

  function periods(context, rows) {
    return ui().table(context, [
      {label: "时间", value: row => ui().timestamp(row.timestamp)},
      {label: "收益", value: row => ui().percent(row.return)},
      {label: "产品", value: row => (row.products || []).map(ui().product).join("、")},
    ], rows);
  }

  function positiveRuns(context, value) {
    return stack(
      ui().cards(context, [
        ["连续正收益段", ui().number(value?.run_count, 0)],
        ["最强 1 段贡献", ui().percent(value?.top1_positive_contribution_ratio)],
        ["最强 3 段贡献", ui().percent(value?.top3_positive_contribution_ratio)],
        ["去掉最强 1 段", ui().percent(value?.return_without_top1_run)],
        ["去掉最强 3 段", ui().percent(value?.return_without_top3_runs)],
      ]),
      ui().table(context, [
        {label: "开始", value: row => ui().timestamp(row.start)},
        {label: "结束", value: row => ui().timestamp(row.end)},
        {label: "期数", value: row => ui().number(row.period_count, 0)},
        {label: "收益", value: row => ui().percent(row.return)},
      ], value?.top_runs || []),
    );
  }

  function summarizeIntradayWindow(rows, start, end) {
    const selected = (rows || []).filter(row => row.time >= start && row.time <= end);
    const total = (rows || []).reduce((sum, row) => sum + (ui().finite(row.sum) || 0), 0);
    const contribution = selected.reduce((sum, row) => sum + (ui().finite(row.sum) || 0), 0);
    return {
      label: `${start}-${end}`,
      count: selected.reduce((sum, row) => sum + (Number(row.count) || 0), 0),
      sum: contribution,
      share_of_total_sum: total !== 0 ? contribution / total : null,
    };
  }

  function intradayWindows(context, value) {
    const root = document.createElement("div");
    root.className = "backtest-analysis-stack";
    const controls = document.createElement("div");
    controls.className = "backtest-analysis-window-controls";
    const start = document.createElement("input"); start.type = "time";
    const end = document.createElement("input"); end.type = "time";
    const add = window.FTUI.actionButton(context.t("添加窗口"), () => {
      if (!start.value || !end.value || start.value > end.value) return;
      windows.push(summarizeIntradayWindow(value?.rows || [], start.value, end.value));
      draw();
    }, {variant: "secondary"});
    const windows = [];
    const output = document.createElement("div");
    const draw = () => output.replaceChildren(ui().table(context, [
      {label: "窗口", key: "label"},
      {label: "样本", value: row => ui().number(row.count, 0)},
      {label: "累计贡献", value: row => ui().percent(row.sum)},
      {label: "占总收益", value: row => ui().percent(row.share_of_total_sum)},
    ], windows, {empty: "尚未添加时间窗口"}));
    controls.append(
      Object.assign(document.createElement("label"), {textContent: context.t("开始")}), start,
      Object.assign(document.createElement("label"), {textContent: context.t("结束")}), end,
      add,
    );
    root.append(controls, output); draw(); return root;
  }

  function intraday(context, value) {
    const rows = data => ui().table(context, [
      {label: "时刻", key: "time"},
      {label: "期数", value: row => ui().number(row.count, 0)},
      {label: "平均收益", value: row => ui().percent(row.mean)},
      {label: "累计收益", value: row => ui().percent(row.sum)},
      {label: "t-like", value: row => ui().number(row.t_like)},
    ], data);
    return stack(
      intradayWindows(context, value),
      Object.assign(document.createElement("h4"), {textContent: context.t("贡献最高的时刻")}),
      rows(value?.top_times || []),
      Object.assign(document.createElement("h4"), {textContent: context.t("贡献最低的时刻")}),
      rows(value?.bottom_times || []),
    );
  }

  window.FTBacktestGroupDetailParts = Object.freeze({
    calendar, capacity, daily, distribution, explanations, frequency, holding,
    feeCoverageClass, intraday, periods, positiveRuns, productAnalysis,
    productDescription, returnChart, robustness, rolling, roundTripFee,
    stack, summary, summarizeIntradayWindow, tradability,
  });
})();
