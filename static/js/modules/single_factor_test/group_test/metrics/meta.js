/**
 * Central metric metadata for GroupTest.
 *
 * Used by:
 * - sectioned metrics table (CN display names)
 * - hover popup (description + MathJax formula)
 */
(function() {
    var GT = window.GroupTest;
    if (!GT) return;

    GT.metrics = GT.metrics || {};

    var cn = {
        'Total Return': '总收益率',
        'Annual Return': '年化收益率',
        'Mean Return': '均值收益率',
        'Win Rate': '胜率',
        'Volatility': '年化波动率',
        'Max Drawdown': '最大回撤',
        'Sharpe Ratio': '夏普比率',
        'Calmar Ratio': 'Calmar比率',
        'Skewness': '偏度',
        'Kurtosis': '峰度',
        'Avg Turnover': '平均换手率',
        'Avg Turnover Accel': '换手加速度',
        'Avg Position Changes': '平均持仓变化数',
        'Up Ratio': '上涨占比',
    };

    var desc = {
        'Total Return': '整个回测期间的累计净收益率',
        'Annual Return': '年化收益率，基于几何平均折算',
        'Volatility': '收益率的年化标准差',
        'Sharpe Ratio': '夏普比率：衡量单位风险的超额回报',
        'Max Drawdown': '最大回撤：净值从峰值到谷底的最大跌幅',
        'Calmar Ratio': 'Calmar比率：年化收益率与最大回撤的比值',
        'Win Rate': '胜率：正收益周期占总周期的比例',
        'Mean Return': '单期收益率的算术平均值',
        'Skewness': '偏度：收益率分布的偏斜程度',
        'Kurtosis': '峰度：收益率分布的尾部厚度',
        'Avg Turnover': '平均换手率：相邻两期持仓变动的比例',
        'Avg Turnover Accel': '换手加速度：衡量交易活跃度的变化趋势（短期/长期换手的相对变化）',
        'Up Ratio': '上涨占比：累计上涨幅度占累计总波动幅度的比例',
        'Avg Position Changes': '平均持仓变化数：单期平均新增或退出的品种数',
    };

    var math = {
        // NOTE: JS 字符串里 `\\` 才会在运行时变成 LaTeX 的单个反斜杠 `\`。
        // 之前这里写成了 `\\\\text` 等，导致运行时变成 `\\text`，MathJax 会把它当普通文本打印出来。
        'Total Return': '$$R_{\\text{total}} = \\prod_t (1+r_t) - 1$$',
        'Annual Return': '$$R_{\\text{ann}} = (1+R_{\\text{total}})^{N_{\\text{year}}/n} - 1$$',
        'Volatility': '$$\\sigma_{\\text{ann}} = \\sigma_{\\text{period}} \\cdot \\sqrt{N_{\\text{year}}}$$',
        'Sharpe Ratio': '$$\\text{Sharpe} = \\frac{\\bar r_{\\text{period}} \\cdot N_{\\text{year}}}{\\sigma_{\\text{period}} \\cdot \\sqrt{N_{\\text{year}}}}$$',
        'Max Drawdown': '$$\\text{MDD} = \\max_t \\left( \\frac{\\text{Peak}_t - \\text{NAV}_t}{\\text{Peak}_t} \\right)$$',
        'Calmar Ratio': '$$\\text{Calmar} = \\frac{R_{\\text{ann}}}{|\\text{MDD}|}$$',
        'Win Rate': '$$\\text{WinRate} = \\frac{N_{\\text{positive}}}{N_{\\text{total}}}$$',
        'Mean Return': '$$\\bar{r} = \\frac{1}{n}\\sum_{t=1}^n r_t$$',
        'Skewness': '$$S = \\frac{1}{n}\\sum_{t=1}^n \\left(\\frac{r_t - \\bar{r}}{\\sigma}\\right)^3$$',
        'Kurtosis': '$$K = \\frac{1}{n}\\sum_{t=1}^n \\left(\\frac{r_t - \\bar{r}}{\\sigma}\\right)^4 - 3$$',
        'Avg Turnover': '$$\\text{Turnover} = \\frac{|\\text{持仓变动}|}{\\text{平均持仓数}}$$',
        'Avg Turnover Accel': '$$\\text{Accel} = \\frac{\\text{MA}(\\text{TO}, N_s)}{\\text{MA}(\\text{TO}, N_l)} - 1$$',
        'Up Ratio': '$$\\text{UpRatio} = \\frac{\\sum \\max(r_i, 0)}{\\sum |r_i|}$$',
        'Avg Position Changes': '$$\\bar{C} = \\frac{1}{n}\\sum_{t=1}^n (|\\text{new}_t| + |\\text{exit}_t|)$$',
    };

    GT.metrics.meta = {
        cn: cn,
        desc: desc,
        math: math,
    };
})();
