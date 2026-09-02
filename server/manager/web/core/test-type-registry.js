(() => {
  const definitions = Object.freeze({
    ic: Object.freeze({
      kind: "ic", application: "ic_test", nav: "ic-test", title: "IC 测试",
      route: "/ic-test", aliases: ["ic", "ic_test", "ic-test", "information_coefficient"],
      pageID: "ic-test", description: "配置并运行因子 IC 测试",
      icon: "IC", sfSymbol: "chart.xyaxis.line", requiresAuth: true,
      resultGroup: "job-detail-ic", resultGlobal: "FTICResults",
    }),
    backtest: Object.freeze({
      kind: "backtest", application: "group_test", nav: "backtest", title: "回测",
      route: "/backtest",
      aliases: ["backtest", "group_backtest", "group-test", "group_test", "portfolio"],
      pageID: "backtest", description: "配置并运行分组回测",
      icon: "BT", sfSymbol: "chart.line.uptrend.xyaxis", requiresAuth: true,
      resultGroup: "job-detail-backtest", resultGlobal: "FTBacktestResults",
    }),
    factor_evaluation: Object.freeze({
      kind: "factor_evaluation", application: "factor_evaluation", nav: "jobs",
      title: "查看因子序列", route: "/factor-series",
      aliases: ["factor_evaluation", "factor-evaluation", "factor_series", "factor-series"],
      pageID: "factor-series", description: "计算并查看因子值、价格与合约区间",
      icon: "FS", sfSymbol: "waveform.path.ecg", requiresAuth: false,
      resultGroup: "job-detail-factor-series", resultGlobal: "FTFactorSeriesResults",
    }),
  });
  const aliases = new Map(Object.values(definitions).flatMap(definition => (
    definition.aliases.map(alias => [alias, definition.kind])
  )));

  function normalize(value) {
    const raw = String(value || "").trim().toLowerCase();
    if (aliases.has(raw)) return aliases.get(raw);
    if (raw.includes("factor_evaluation") || (raw.includes("factor") && raw.includes("series"))) {
      return "factor_evaluation";
    }
    if (raw.includes("information_coefficient") || raw.includes("ic")) return "ic";
    if (raw.includes("backtest") || raw.includes("group_test") || raw.includes("portfolio")) {
      return "backtest";
    }
    return "";
  }

  function get(value) {
    return definitions[normalize(value)] || null;
  }

  function resultViewer(value) {
    const definition = get(value);
    return definition ? {
      group: definition.resultGroup, global: definition.resultGlobal,
    } : null;
  }

  window.FTTestTypeRegistry = Object.freeze({definitions, get, normalize, resultViewer});
})();
