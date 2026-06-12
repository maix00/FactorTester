"""
分组测试元数据 — 单一数据源 (Single Source of Truth)

阶段顺序、中文标签、指标名称等统一在此定义。
后端在 emit_start 时携带 GROUP_TEST_PHASES，前端据此渲染进度条。
"""

# ── 阶段元数据 ──

GROUP_TEST_PHASES = [
    {"key": "factor_eval",     "label": "因子计算"},
    {"key": "returns_eval",    "label": "收益率计算"},
    {"key": "membership",      "label": "分组隶属"},
    {"key": "flat_membership", "label": "展开隶属"},
    {"key": "remap",           "label": "产品映射"},
    {"key": "trade_data",      "label": "交易数据"},
    {"key": "liquidity",       "label": "流动性容量"},
    {"key": "simulate",        "label": "模拟中"},
    {"key": "batch",           "label": "批次结果"},
    {"key": "serialize",       "label": "序列化"},
]

# ── 指标元数据 ──

# report_df 指标列名 → 中文名 + 描述 + LaTeX 公式
# 前端 metrics/meta.js 曾硬编码这些，现已统一到此文件，通过 emit_result 传递

GROUP_TEST_METRICS_CN = {
    "Total Return":              "总收益率",
    "Annual Return":             "年化收益率",
    "Mean Return":               "均值收益率",
    "Win Rate":                  "胜率",
    "Volatility":                "年化波动率",
    "Max Drawdown":              "最大回撤",
    "Sharpe Ratio":              "夏普比率",
    "Calmar Ratio":              "Calmar比率",
    "Skewness":                  "偏度",
    "Kurtosis":                  "峰度",
    "Avg Turnover":              "平均换手率",
    "Avg Turnover Accel":        "换手加速度",
    "Avg Position Changes":      "平均持仓变化数",
    "Up Ratio":                  "上涨占比",
}

GROUP_TEST_METRICS_DESC = {
    "Total Return":              "整个回测期间的累计净收益率",
    "Annual Return":             "年化收益率，基于几何平均折算",
    "Volatility":                "收益率的年化标准差",
    "Sharpe Ratio":              "夏普比率：衡量单位风险的超额回报",
    "Max Drawdown":              "最大回撤：净值从峰值到谷底的最大跌幅",
    "Calmar Ratio":              "Calmar比率：年化收益率与最大回撤的比值",
    "Win Rate":                  "胜率：正收益周期占总周期的比例",
    "Mean Return":               "单期收益率的算术平均值",
    "Skewness":                  "偏度：收益率分布的偏斜程度",
    "Kurtosis":                  "峰度：收益率分布的尾部厚度",
    "Avg Turnover":              "平均换手率：相邻两期持仓变动的比例",
    "Avg Turnover Accel":        "换手加速度：衡量交易活跃度的变化趋势（短期/长期换手的相对变化）",
    "Up Ratio":                  "上涨占比：累计上涨幅度占累计总波动幅度的比例",
    "Avg Position Changes":      "平均持仓变化数：单期平均新增或退出的品种数",
}

GROUP_TEST_METRICS_MATH = {
    "Total Return":              r"$$R_{\text{total}} = \prod_t (1+r_t) - 1$$",
    "Annual Return":             r"$$R_{\text{ann}} = (1+R_{\text{total}})^{N_{\text{year}}/n} - 1$$",
    "Volatility":                r"$$\sigma_{\text{ann}} = \sigma_{\text{period}} \cdot \sqrt{N_{\text{year}}}$$",
    "Sharpe Ratio":              r"$$\text{Sharpe} = \frac{\bar r_{\text{period}} \cdot N_{\text{year}}}{\sigma_{\text{period}} \cdot \sqrt{N_{\text{year}}}}$$",
    "Max Drawdown":              r"$$\text{MDD} = \max_t \left( \frac{\text{Peak}_t - \text{NAV}_t}{\text{Peak}_t} \right)$$",
    "Calmar Ratio":              r"$$\text{Calmar} = \frac{R_{\text{ann}}}{|\text{MDD}|}$$",
    "Win Rate":                  r"$$\text{WinRate} = \frac{N_{\text{positive}}}{N_{\text{total}}}$$",
    "Mean Return":               r"$$\bar{r} = \frac{1}{n}\sum_{t=1}^n r_t$$",
    "Skewness":                  r"$$S = \frac{1}{n}\sum_{t=1}^n \left(\frac{r_t - \bar{r}}{\sigma}\right)^3$$",
    "Kurtosis":                  r"$$K = \frac{1}{n}\sum_{t=1}^n \left(\frac{r_t - \bar{r}}{\sigma}\right)^4 - 3$$",
    "Avg Turnover":              r"$$\text{Turnover} = \frac{|\text{持仓变动}|}{\text{平均持仓数}}$$",
    "Avg Turnover Accel":        r"$$\text{Accel} = \frac{\text{MA}(\text{TO}, N_s)}{\text{MA}(\text{TO}, N_l)} - 1$$",
    "Up Ratio":                  r"$$\text{UpRatio} = \frac{\sum \max(r_i, 0)}{\sum |r_i|}$$",
    "Avg Position Changes":      r"$$\bar{C} = \frac{1}{n}\sum_{t=1}^n (|\text{new}_t| + |\text{exit}_t|)$$",
}

# 聚合字典，方便一次传给前端
GROUP_TEST_METRICS_META = {
    "cn": GROUP_TEST_METRICS_CN,
    "desc": GROUP_TEST_METRICS_DESC,
    "math": GROUP_TEST_METRICS_MATH,
}
