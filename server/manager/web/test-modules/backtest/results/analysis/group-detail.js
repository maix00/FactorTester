(() => {
  function summaryText(detail, key, fallback) {
    const values = {
      frequency: detail?.entry_frequency?.[0]
        ? `最高 ${FTBacktestAnalysisUI.product(detail.entry_frequency[0].product)} ${FTBacktestAnalysisUI.percent(detail.entry_frequency[0].frequency)}` : "",
      distribution: detail?.distribution?.quantiles
        ? `P50 ${FTBacktestAnalysisUI.percent(detail.distribution.quantiles.p50)} · P95 ${FTBacktestAnalysisUI.percent(detail.distribution.quantiles.p95)}` : "",
      rolling: detail?.rolling_analysis?.window_size
        ? `${detail.rolling_analysis.window_size} 期窗口` : "",
      capacity: detail?.capacity_analysis?.tiny_group_ratio != null
        ? `小样本期 ${FTBacktestAnalysisUI.percent(detail.capacity_analysis.tiny_group_ratio)}` : "",
      holding: detail?.holding_analysis?.median_periods != null
        ? `中位数 ${FTBacktestAnalysisUI.number(detail.holding_analysis.median_periods, 1)} 期` : "",
    };
    return values[key] || fallback;
  }

  function render(context, target, detail, options = {}, entry = null) {
    const p = Object.assign(
      {}, window.FTBacktestGroupDetailParts, window.FTBacktestGroupDetailProducts,
    );
    const section = (title, key, fallback, build, open = false) => (
      FTBacktestAnalysisUI.section(
        context, title, summaryText(detail, key, fallback), build, open,
      )
    );
    target.replaceChildren(
      section("核心指标", "", "该组收益、风险、胜率和换手", () => p.summary(context, detail.summary), true),
      section("收益曲线", "", "单期收益与累计净值", () => p.returnChart(context, detail.return_series), true),
      section("进入频率", "frequency", "哪些产品最常进入该组", () => p.frequency(
        context, detail.entry_frequency, {
          onCreateDerived: options.job && context.session ? async products => {
            if (!products.length) {
              context.showNotice(context.t("请至少选择一个品种"), true);
              return;
            }
            try {
              await FTJobActions.cloneRunWorkspace(context, {
                job: options.job,
                portQuery: options.portQuery,
                title: `${context.t("派生组配置")} · ${entry?.label || ""}`,
                derivedPrefill: {
                  parentID: String(entry?.strategy_id || entry?.group_id || entry?.key || ""),
                  products,
                  name: `${entry?.label || context.t("分组")} ${context.t("精选")}`,
                },
              });
            } catch (error) {
              context.showNotice(
                `${context.t("恢复冻结配置失败")}: ${error.message}`,
                true,
              );
            }
          } : null,
        },
      )),
      section("收益分布", "distribution", "收益直方图与分位数", () => p.distribution(context, detail.distribution)),
      section("滚动表现", "rolling", "不同时间窗口里是否持续有效", () => p.rolling(context, detail.rolling_analysis)),
      section("组容量", "capacity", "组内样本是否经常过小", () => p.capacity(context, detail.capacity_analysis)),
      section("成本承受力", "", "资金换手与成本承受力", () => p.tradability(context, detail.tradability_analysis)),
      section("日历分析", "", "按月、按月内日期、按年查看收益", () => p.calendar(context, detail.calendar_analysis)),
      section("持有期", "holding", "组内成员通常停留多久", () => p.holding(context, detail.holding_analysis)),
      section("风险解释", "", "系统归纳的主要风险", () => p.explanations(context, detail.explanations)),
      section("产品贡献", "", "哪些产品真正贡献了毛收益", () => p.productAnalysis(context, detail.product_analysis)),
      section("交易日贡献", "", "哪些交易日主导了结果", () => p.daily(context, detail.daily_analysis)),
      section("稳健性", "", "去掉头部时段后还剩多少", () => p.robustness(context, detail.robustness_summary, detail.period_robustness)),
      section("极端时段", "", "收益最高和最低的具体时段", () => p.stack(
        Object.assign(document.createElement("h4"), {textContent: context.t("最高时段")}),
        p.periods(context, detail.top_periods),
        Object.assign(document.createElement("h4"), {textContent: context.t("最低时段")}),
        p.periods(context, detail.bottom_periods),
      )),
      section("连续正收益段", "", "是否依赖少数连续正收益段", () => p.positiveRuns(context, detail.positive_run_analysis)),
      section("日内时刻贡献", "", "哪些分钟真正贡献了收益", () => p.intraday(context, detail.intraday_analysis)),
    );
  }

  async function load(context, options, entry) {
    const request = FTBacktestResultModel.groupRequest(entry, options.resultSummary);
    if (!request) throw new Error(context.t("该分组缺少可读取的执行身份"));
    return FTBacktestAnalysisAPI.detail(context, options, request);
  }

  async function open(context, options, entry) {
    const view = FTBacktestAnalysisUI.dialog(context, "分组详情", entry.label);
    view.body.append(FTUI.loading(context.t("正在读取分组详情…")));
    try {
      render(
        context, view.body, await load(context, options, entry),
        options, entry,
      );
    } catch (error) {
      view.body.replaceChildren(Object.assign(document.createElement("p"), {
        className: "backtest-domain-empty", textContent: error.message,
      }));
    }
  }

  window.FTBacktestGroupDetail = Object.freeze({load, open, render});
})();
