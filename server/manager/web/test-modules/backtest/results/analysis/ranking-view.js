(() => {
  function spreadChart(context, rows) {
    const target = FTBacktestAnalysisUI.chartNode();
    const points = (key, scale = 1) => (rows || []).flatMap((row, index) => {
      const value = FTBacktestAnalysisUI.finite(row?.[key]);
      const timestamp = window.FTChartTimeline.timestamp(row?.timestamp, Number.NaN);
      return value == null ? [] : [[Number.isFinite(timestamp) ? timestamp : index, value * scale]];
    });
    const options = FTBacktestAnalysisUI.baseChart([
      {name: context.t("单期 Top-Bottom"), type: "column", data: points("spread", 100)},
      {name: context.t("累计净值"), type: "line", yAxis: 1, data: points("cumulative_return")},
    ], context.t("组差（%）"));
    options.yAxis = [options.yAxis, {title: {text: context.t("累计净值")}, opposite: true}];
    return FTBacktestAnalysisUI.chart(target, options, true);
  }

  function monotonicChart(context, rows) {
    const target = FTBacktestAnalysisUI.chartNode("compact");
    const data = (rows || []).map((row, index) => ({
      x: index, y: row.is_monotonic ? 1 : 0,
      color: row.is_descending ? "#2f855a" : row.is_monotonic ? "#7c9fe6" : "#d0d5dd",
      name: FTBacktestAnalysisUI.timestamp(row.timestamp),
    }));
    return FTBacktestAnalysisUI.chart(target, {
      chart: {type: "column", backgroundColor: "transparent"}, title: {text: null},
      credits: {enabled: false}, legend: {enabled: false},
      xAxis: {categories: data.map(item => item.name), labels: {enabled: false}},
      yAxis: {min: 0, max: 1, tickPositions: [0, 1], title: {text: null},
        labels: {formatter() { return this.value ? context.t("单调") : context.t("非单调"); }}},
      tooltip: {pointFormat: "{point.name}<br>{point.y}"},
      series: [{name: context.t("单调性"), data}],
    });
  }

  function render(context, target, detail) {
    const section = (title, summary, build, open = false) => (
      FTBacktestAnalysisUI.section(context, title, summary, build, open)
    );
    const topBottom = detail.top_bottom || {};
    target.replaceChildren(
      section("整体排序质量", "跨期排序、覆盖与可比性", () => (
        FTBacktestAnalysisUI.cards(context, [
          ["可比较期数", FTBacktestAnalysisUI.number(detail.comparable_period_count, 0)],
          ["完整分组期占比", FTBacktestAnalysisUI.percent(detail.full_group_period_ratio)],
          ["平均非空组数", FTBacktestAnalysisUI.number(detail.mean_non_empty_group_count, 2)],
          ["平均秩相关", FTBacktestAnalysisUI.number(detail.mean_rank_correlation)],
          ["单调期占比", FTBacktestAnalysisUI.percent(detail.monotonic_period_ratio)],
          ["严格降序期占比", FTBacktestAnalysisUI.percent(detail.descending_period_ratio)],
        ])
      ), true),
      section("相邻组差", "相邻两组之间是否逐级拉开", () => (
        FTBacktestAnalysisUI.table(context, [
          {label: "从", key: "from_group"}, {label: "到", key: "to_group"},
          {label: "平均组差", value: row => FTBacktestAnalysisUI.percent(row.mean_spread)},
          {label: "正组差占比", value: row => FTBacktestAnalysisUI.percent(row.positive_ratio)},
        ], detail.adjacent_spreads || [])
      ), true),
      section("Top-Bottom", `平均组差 ${FTBacktestAnalysisUI.percent(topBottom.mean_spread)} · 正组差 ${FTBacktestAnalysisUI.percent(topBottom.positive_ratio)}`, () => (
        spreadChart(context, topBottom.series || [])
      ), true),
      section("逐期单调性", "每一期是否保持有序分组", () => (
        monotonicChart(context, detail.monotonic_series || [])
      )),
    );
  }

  async function load(context, options, entry) {
    const request = FTBacktestResultModel.groupRequest(entry, options.resultSummary);
    if (!request) throw new Error(context.t("缺少产品路径选择"));
    return FTBacktestAnalysisAPI.ranking(context, options, {
      product_path_selection_id: request.product_path_selection_id,
      strategy_configuration_id: entry.configurationID
        || entry.strategy_configuration_id || "",
    });
  }

  async function open(context, options, entry) {
    const view = FTBacktestAnalysisUI.dialog(context, "分组排序诊断", entry.label);
    view.body.append(FTUI.loading(context.t("正在读取排序诊断…")));
    try {
      render(context, view.body, await load(context, options, entry));
    } catch (error) {
      view.body.replaceChildren(Object.assign(document.createElement("p"), {
        className: "backtest-domain-empty", textContent: error.message,
      }));
    }
  }

  window.FTBacktestRankingView = Object.freeze({load, open, render});
})();
