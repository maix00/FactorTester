(() => {
  function number(value) {
    if (value == null) return "—";
    if (!Number.isFinite(Number(value))) return String(value);
    const numeric = Number(value);
    return Math.abs(numeric) >= 1000 ? numeric.toLocaleString()
      : numeric.toFixed(6).replace(/0+$/, "").replace(/\.$/, "");
  }

  function table(context, rows) {
    if (!rows.length) {
      const node = document.createElement("p");
      node.className = "ic-domain-empty";
      node.textContent = context.t("暂无分组组合统计");
      return node;
    }
    const columns = [
      "portfolio_mode", "portfolio_kind", "group_index", "total_return",
      "annual_return", "volatility", "sharpe_ratio", "max_drawdown",
      "calmar_ratio", "win_rate", "avg_turnover", "turnover_proxy",
      "monotonic_period_ratio", "descending_period_ratio",
      "target_margin_utilization", "initial_capital",
    ];
    const labels = {
      portfolio_mode: "模式", portfolio_kind: "组合", group_index: "组",
      total_return: "总收益", annual_return: "年化收益", volatility: "波动率",
      sharpe_ratio: "Sharpe", max_drawdown: "最大回撤", calmar_ratio: "Calmar",
      win_rate: "胜率", avg_turnover: "平均换手", turnover_proxy: "换手代理",
      monotonic_period_ratio: "单调比例", descending_period_ratio: "降序比例",
      target_margin_utilization: "目标保证金利用率", initial_capital: "初始金额",
    };
    const percentColumns = new Set([
      "total_return", "annual_return", "volatility", "max_drawdown", "win_rate",
      "mean_return", "avg_turnover", "turnover_proxy", "monotonic_period_ratio",
      "descending_period_ratio", "target_margin_utilization",
    ]);
    const decimalRatioColumns = new Set([
      "avg_turnover", "turnover_proxy", "monotonic_period_ratio",
      "descending_period_ratio", "target_margin_utilization",
    ]);
    return window.FTReportTables.render({
      columns, rows: rows.slice(0, 500), context,
      className: "ic-domain-data-table ic-quantile-portfolio-table",
      renderHeader: key => window.FTRichText.inline(labels[key] || key, context),
      renderCell: (value, _row, key) => {
        const numeric = number(decimalRatioColumns.has(key) ? Number(value) * 100 : value);
        return window.FTRichText.inline(
          numeric === "—" || !percentColumns.has(key) ? numeric : `${numeric}%`,
          context,
        );
      },
      values: row => columns.map(key => row[key]),
    });
  }

  window.FTICPortfolioView = Object.freeze({table});
})();
