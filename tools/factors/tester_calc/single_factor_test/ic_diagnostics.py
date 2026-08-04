"""Explicitly named diagnostics for realised IC sequences.

The server keeps the historical short aliases (``mean``, ``IR``, ``t_stat``,
``half_life`` and ``ac1``) for existing clients, but new consumers should use
the fields returned here.  Every field states its unit and statistical level:
signal observations, IID benchmark, HAC inference, or realised-IC persistence.
"""

from __future__ import annotations

import math
import statistics
from typing import Any, Iterable

import numpy as np
import pandas as pd

from tools.factors.temporal_support import TemporalSupport, resolve_hac_lag
from tools.factors.tester_calc.single_factor_test.ic_half_life import (
    fit_ic_series_ar1_half_life,
)


IC_DIAGNOSTICS_SCHEMA = "ic-diagnostics-v1"


IC_METRIC_SEMANTICS: tuple[dict[str, Any], ...] = (
    {
        "name": "n_signal_observations",
        "meaning": "有效 IC 信号时间戳数量，不是产品行数、周期块数或 ESS。",
        "scope": "signal-level",
        "unit": "count",
    },
    {
        "name": "mean_ic",
        "meaning": "有效信号时间戳上的 IC 算术平均，表示平均方向和平均信息量。",
        "scope": "signal-level",
        "unit": "IC",
    },
    {
        "name": "std_ic",
        "meaning": "信号级 IC 的样本标准差（ddof=1），表示时间波动，不是横截面波动。",
        "scope": "signal-level",
        "unit": "IC",
    },
    {
        "name": "se_iid",
        "meaning": "std_ic / sqrt(n_signal_observations)；只是假设 IID 的均值标准误。",
        "scope": "signal-level",
        "unit": "IC",
    },
    {
        "name": "ci95_iid",
        "meaning": "mean_ic ± 1.96 × se_iid 的描述性正态近似区间；不替代 HAC 区间。",
        "scope": "signal-level",
        "unit": "IC",
    },
    {
        "name": "median_ic",
        "meaning": "信号级 IC 的中位数，降低单个极端观测对中心位置的影响。",
        "scope": "signal-level",
        "unit": "IC",
    },
    {
        "name": "mad_ic",
        "meaning": "IC 关于中位数的 median absolute deviation；是稳健离散度，不是标准差。",
        "scope": "signal-level",
        "unit": "IC",
    },
    {
        "name": "icir_signal",
        "meaning": "mean_ic / std_ic；是信号级一致性比率，不是交易组合 Sharpe。",
        "scope": "signal-level",
        "unit": "ratio",
    },
    {
        "name": "t_stat_iid",
        "meaning": "把信号级 IC 当作 IID 观测时的均值 t 值，只作基准，不处理序列相关。",
        "scope": "signal-level",
        "unit": "t-stat",
    },
    {
        "name": "t_stat_hac",
        "meaning": "按显式 temporal-support 解析 lag 后、Bartlett 核长期方差的均值 t 值；按渐近正态解释。",
        "scope": "signal-level",
        "unit": "t-stat",
    },
    {
        "name": "ci95_hac",
        "meaning": "mean_ic ± 1.96 × se_hac 的 HAC 描述性区间；lag、核函数和支持跨度必须同时审计。",
        "scope": "signal-level",
        "unit": "IC",
    },
    {
        "name": "direction_rate",
        "meaning": "在已声明 expected_sign 后，expected_sign × IC > 0 的信号比例；零值不算命中。",
        "scope": "signal-level",
        "unit": "proportion",
    },
    {
        "name": "positive_ic_rate",
        "meaning": "IC > 0 的信号比例；不使用因子方向声明。",
        "scope": "signal-level",
        "unit": "proportion",
    },
    {
        "name": "negative_ic_rate",
        "meaning": "IC < 0 的信号比例；不使用因子方向声明。",
        "scope": "signal-level",
        "unit": "proportion",
    },
    {
        "name": "zero_ic_rate",
        "meaning": "IC = 0 的信号比例；零值不计入 direction_rate 命中。",
        "scope": "signal-level",
        "unit": "proportion",
    },
    {
        "name": "ic_series_acf_half_life_signals",
        "meaning": "已实现 IC 序列 ACF 首次跌破 0.5 的信号步半衰期，不是 forward horizon 衰减。",
        "scope": "signal-level",
        "unit": "signal steps",
    },
    {
        "name": "ic_series_ar1_half_life_signals",
        "meaning": "已实现 IC 序列 AR(1) 持久性半衰期；仅在 0<rho<1 时估计，不是预测收益 horizon 半衰期。",
        "scope": "signal-level",
        "unit": "signal steps",
    },
    {
        "name": "ic_series_ar1_half_life_seconds",
        "meaning": "AR(1) 持久性半衰期乘以显式 signal_interval；间隔未知时不估计。",
        "scope": "signal-level",
        "unit": "seconds",
    },
    {
        "name": "forward_ic_half_life_exponential",
        "meaning": "对已计算的 forward-return horizon 平均 IC 做 log-linear 指数衰减拟合；单位是实际持有期时间，区别于 IC 序列 ACF/AR(1) 持久性。它是描述性模型化估计，不宣称地面真值或置信区间；重叠 horizon 下不能把 OLS 误差当独立样本推断。",
        "scope": "horizon-level",
        "unit": "seconds",
    },
    {
        "name": "forward_ic_half_life",
        "meaning": "不同 forward-return horizon 的 IC 均值相对基准半幅交叉，单位是实际持有期时间；只表示网格上的首次交叉。",
        "scope": "horizon-level",
        "unit": "duration",
    },
    {
        "name": "effective_n_capped",
        "meaning": "由 HAC 长期方差得到的 ESS raw 截断到 [1,n] 后的样本充足度诊断；不替代 HAC 区间。",
        "scope": "signal-level",
        "unit": "count",
    },
    {
        "name": "effective_n_raw",
        "meaning": "按 HAC 长期方差反推的未截断 ESS；负自相关可能使它大于 n，因此不能当作原始观测数。",
        "scope": "signal-level",
        "unit": "count",
    },
    {
        "name": "hac_lag",
        "meaning": "由显式 temporal-support 的重叠时长转换得到的信号步数，或明确请求的人工 lag；未知时不估计。",
        "scope": "signal-level",
        "unit": "signal steps",
    },
    {
        "name": "hac_lag_formula",
        "meaning": "自动 lag 使用 ceil((factor_input + label + holding + decay) / signal_interval) - 1；因子输入历史是依赖跨度，不是样本量。",
        "scope": "signal-level",
        "unit": "definition",
    },
    {
        "name": "hac_kernel",
        "meaning": "HAC 长期方差使用 Bartlett 权重；lag 不是仅凭因子参数名称猜出来的。",
        "scope": "signal-level",
        "unit": "definition",
    },
    {
        "name": "se_hac",
        "meaning": "Newey-West 长期方差下的 IC 均值标准误；不等同于 IID 标准误。",
        "scope": "signal-level",
        "unit": "IC",
    },
    {
        "name": "rolling_k_signals",
        "meaning": "尾随窗口内有效信号时间戳数量 K；与端点时间跨度分开记录。",
        "scope": "rolling",
        "unit": "count",
    },
    {
        "name": "rolling_actual_endpoint_span_seconds",
        "meaning": "滚动窗口首尾信号时间戳的实际墙钟跨度；可能受周末、交易休市和不规则信号影响。",
        "scope": "rolling",
        "unit": "seconds",
    },
    {
        "name": "rolling_expected_endpoint_span_seconds",
        "meaning": "按 K 个信号端点定义的期望跨度 (K-1)×signal_interval；明确区别于 K×interval 的覆盖约定。",
        "scope": "rolling",
        "unit": "seconds",
    },
    {
        "name": "rolling_expected_coverage_span_seconds",
        "meaning": "把 K 个信号步作为覆盖长度时的 K×signal_interval；不是首尾端点经过的时间。",
        "scope": "rolling",
        "unit": "seconds",
    },
    {
        "name": "period_estimability",
        "meaning": "周期块的观测数充足、HAC 可估计和块数量充足是三个不同状态。",
        "scope": "period",
        "unit": "status",
    },
    {
        "name": "ess_definition",
        "meaning": "ESS_raw = n × gamma0 / long_run_variance；负自相关可使 raw > n，因此另报 capped ESS。",
        "scope": "signal-level",
        "unit": "definition",
    },
    {
        "name": "acf_estimator",
        "meaning": "ACF 使用 statsmodels adjusted=False，即自协方差分母为 n；与样本 std(ddof=1) 是不同约定。",
        "scope": "signal-level",
        "unit": "definition",
    },
)

# Fields below are deliberately catalogued even when they are auxiliary
# status/definition columns in the report table.  A UI must not have to infer
# their meaning from a column name or from a legacy alias.
IC_METRIC_SEMANTICS += (
    {
        "name": "diagnostics_schema",
        "meaning": "诊断字段协议版本；用于判断字段语义版本，不是统计量。",
        "scope": "metadata",
        "unit": "schema",
    },
    {
        "name": "std_ic_ddof",
        "meaning": "std_ic 使用的自由度约定；当前固定为样本标准差 ddof=1。",
        "scope": "metadata",
        "unit": "integer",
        "formula": "ddof=1",
    },
    {
        "name": "ci95_iid_lower",
        "meaning": "IID 正态近似 95% 区间下界；mean_ic - 1.96×se_iid。",
        "scope": "signal-level",
        "unit": "IC",
    },
    {
        "name": "ci95_iid_upper",
        "meaning": "IID 正态近似 95% 区间上界；mean_ic + 1.96×se_iid。",
        "scope": "signal-level",
        "unit": "IC",
    },
    {
        "name": "ci95_hac_lower",
        "meaning": "HAC 正态近似 95% 区间下界；mean_ic - 1.96×se_hac。",
        "scope": "signal-level",
        "unit": "IC",
    },
    {
        "name": "ci95_hac_upper",
        "meaning": "HAC 正态近似 95% 区间上界；mean_ic + 1.96×se_hac。",
        "scope": "signal-level",
        "unit": "IC",
    },
    {
        "name": "hac_lag_source",
        "meaning": "HAC lag 的来源；应为 temporal_support_overlap、explicit 或 not estimable。",
        "scope": "metadata",
        "unit": "status",
    },
    {
        "name": "hac_status",
        "meaning": "HAC 是否可估计；not_estimable 时 HAC t、SE、ESS 和区间不可解释。",
        "scope": "metadata",
        "unit": "status",
    },
    {
        "name": "hac_reason",
        "meaning": "HAC 未估计或被限制时的机器可读原因。",
        "scope": "metadata",
        "unit": "text",
    },
    {
        "name": "hac_overlap_support_seconds",
        "meaning": "自动 HAC lag 使用的原始数据依赖跨度；不是 warm-up 样本数。",
        "scope": "signal-level",
        "unit": "seconds",
    },
    {
        "name": "hac_overlap_support_components_seconds",
        "meaning": "组成依赖跨度的 factor_input、label_horizon、holding、decay 四项明细。",
        "scope": "metadata",
        "unit": "seconds-map",
    },
    {
        "name": "effective_n_ratio",
        "meaning": "effective_n_raw / n_signal_observations；可因负自相关大于 1。",
        "scope": "signal-level",
        "unit": "ratio",
    },
    {
        "name": "effective_n_capped_ratio",
        "meaning": "effective_n_capped / n_signal_observations；按 [1,n] 截断后的比例。",
        "scope": "signal-level",
        "unit": "ratio",
    },
    {
        "name": "ess_exceeds_n",
        "meaning": "raw ESS 是否大于原始 n；通常表示估计到负序列相关，不是数据数量增加。",
        "scope": "metadata",
        "unit": "boolean",
    },
    {
        "name": "hac_lrv_to_iid_variance_ratio",
        "meaning": "HAC 长期方差 / IID 方差；大于 1 表示正序列相关使 IID 不确定性偏小。",
        "scope": "signal-level",
        "unit": "ratio",
    },
    {
        "name": "minimum_ic",
        "meaning": "信号级 IC 最小值；用于识别极端失败观测。",
        "scope": "signal-level",
        "unit": "IC",
    },
    {
        "name": "maximum_ic",
        "meaning": "信号级 IC 最大值；用于识别极端成功观测。",
        "scope": "signal-level",
        "unit": "IC",
    },
    {
        "name": "p10_ic",
        "meaning": "信号级 IC 的 10% 分位数。",
        "scope": "signal-level",
        "unit": "IC",
    },
    {
        "name": "p25_ic",
        "meaning": "信号级 IC 的 25% 分位数。",
        "scope": "signal-level",
        "unit": "IC",
    },
    {
        "name": "p50_ic",
        "meaning": "信号级 IC 的 50% 分位数，与 median_ic 同义。",
        "scope": "signal-level",
        "unit": "IC",
    },
    {
        "name": "p75_ic",
        "meaning": "信号级 IC 的 75% 分位数。",
        "scope": "signal-level",
        "unit": "IC",
    },
    {
        "name": "p90_ic",
        "meaning": "信号级 IC 的 90% 分位数。",
        "scope": "signal-level",
        "unit": "IC",
    },
    {
        "name": "skew_ic",
        "meaning": "IC 分布偏度；描述极端正/负观测的不对称性，不是稳定性分数。",
        "scope": "signal-level",
        "unit": "ratio",
    },
    {
        "name": "excess_kurtosis_ic",
        "meaning": "IC 超额峰度；描述尾部厚度，不是显著性检验。",
        "scope": "signal-level",
        "unit": "ratio",
    },
    {
        "name": "ic_series_acf1",
        "meaning": "已实现 IC 序列一阶自相关；衡量相邻 IC 观测的持久性。",
        "scope": "signal-level",
        "unit": "correlation",
    },
    {
        "name": "ic_series_acf_half_life_status",
        "meaning": "ACF 半衰期估计状态；not_reached 表示观测 lag 内未跌破 0.5。",
        "scope": "metadata",
        "unit": "status",
    },
    {
        "name": "ic_series_ar1_rho",
        "meaning": "IC_t 对 IC_(t-1) 的 AR(1) 斜率 rho；仅用于持久性诊断。",
        "scope": "signal-level",
        "unit": "coefficient",
    },
    {
        "name": "ic_series_ar1_r_squared",
        "meaning": "AR(1) 持久性回归的样本内 R²；不是因子预测 R²。",
        "scope": "signal-level",
        "unit": "ratio",
    },
    {
        "name": "ic_series_ar1_half_life_status",
        "meaning": "AR(1) 持久性半衰期状态；仅 0<rho<1 且样本足够时估计。",
        "scope": "metadata",
        "unit": "status",
    },
    {
        "name": "ic_series_ar1_n_signal_pairs",
        "meaning": "AR(1) 使用的相邻 IC 对数量，不是原始产品数量。",
        "scope": "signal-level",
        "unit": "count",
    },
    {
        "name": "ic_series_ar1_method",
        "meaning": "AR(1) 持久性估计方法标识；当前为带截距 OLS。",
        "scope": "metadata",
        "unit": "method",
    },
    {
        "name": "t_stat_hac_reference",
        "meaning": "HAC t 值的参考分布；当前按渐近正态使用，不宣称有限样本 t 分布。",
        "scope": "metadata",
        "unit": "method",
    },
    {
        "name": "forward_ic_half_life_status",
        "meaning": "网格半幅交叉的预测性衰减状态；不是 IC 序列 ACF 半衰期。",
        "scope": "horizon-level",
        "unit": "status",
    },
    {
        "name": "forward_ic_half_life_duration",
        "meaning": "网格半幅交叉估计出的 forward-return horizon 时间。",
        "scope": "horizon-level",
        "unit": "duration",
    },
    {
        "name": "forward_ic_half_life_crossing_seconds",
        "meaning": "网格半幅首次交叉的实际持有期秒数；需要至少两个有序 horizon，未交叉时为空。",
        "scope": "horizon-level",
        "unit": "seconds",
    },
    {
        "name": "forward_ic_half_life_exponential_status",
        "meaning": "log-linear forward-IC 指数衰减拟合状态；需要至少三个正的、同方向 horizon 均值。",
        "scope": "horizon-level",
        "unit": "status",
    },
    {
        "name": "forward_ic_half_life_exponential_duration",
        "meaning": "log-linear forward-IC 衰减拟合的半衰期可读 duration。",
        "scope": "horizon-level",
        "unit": "duration",
    },
    {
        "name": "forward_ic_half_life_exponential_seconds",
        "meaning": "log-linear forward-IC 衰减拟合的半衰期秒数；这是实际持有期尺度上的预测性衰减估计，不是信号序列持久性。",
        "scope": "horizon-level",
        "unit": "seconds",
    },
    {
        "name": "forward_ic_half_life_exponential_r_squared",
        "meaning": "log-linear forward-IC 衰减曲线的样本内 R²；用于判断指数模型是否贴合。",
        "scope": "horizon-level",
        "unit": "ratio",
    },
    {
        "name": "forward_ic_half_life_exponential_n_horizons",
        "meaning": "指数衰减拟合使用的有效持有期 horizon 数量。",
        "scope": "horizon-level",
        "unit": "count",
    },
    {
        "name": "forward_ic_half_life_baseline_horizon",
        "meaning": "持有期半衰计算所用的最短有效 forward-return horizon；半幅阈值以该 horizon 的 IC 均值为基准。",
        "scope": "horizon-level",
        "unit": "duration",
    },
    {
        "name": "forward_ic_half_life_baseline_seconds",
        "meaning": "持有期半衰计算基准 horizon 的秒数；与 baseline_horizon 同义但便于跨频率比较。",
        "scope": "horizon-level",
        "unit": "seconds",
    },
    {
        "name": "forward_ic_half_life_baseline_mean_ic",
        "meaning": "持有期半衰计算的基准 horizon 平均 IC；用于定义半幅阈值，不是全样本 IC 均值。",
        "scope": "horizon-level",
        "unit": "IC",
    },
    {
        "name": "forward_ic_half_life_expected_direction",
        "meaning": "由最短 horizon 基准 IC 决定的衰减方向；负 IC 会先乘以 -1 做方向对齐，遇到非正对齐值则拒绝指数拟合。",
        "scope": "horizon-level",
        "unit": "sign",
    },
    {
        "name": "forward_ic_half_life_curve_monotonic_nonincreasing",
        "meaning": "方向对齐后的 horizon IC 是否单调不增；指数拟合即使可估计也必须单独报告该诊断。",
        "scope": "horizon-level",
        "unit": "boolean",
    },
    {
        "name": "forward_ic_half_life_n_invalid_oriented_points",
        "meaning": "方向对齐后小于等于零的 horizon 点数；这些点会使 log-linear 指数拟合不可估计。",
        "scope": "horizon-level",
        "unit": "count",
    },
    {
        "name": "forward_ic_half_life_exponential_log_fit_rmse",
        "meaning": "log(IC) 指数拟合的样本内 RMSE；与 R² 一起衡量拟合误差，不是预测收益误差。",
        "scope": "horizon-level",
        "unit": "log-IC",
    },
    {
        "name": "forward_ic_half_life_crossing_n_nonpositive_oriented_points",
        "meaning": "网格半幅交叉曲线中，方向对齐后小于等于零的 horizon 点数；用于识别半幅交叉后是否发生符号反转。",
        "scope": "horizon-level",
        "unit": "count",
    },
    {
        "name": "forward_ic_half_life_crossing_baseline_horizon",
        "meaning": "网格半幅交叉使用的最短有效 forward-return horizon。",
        "scope": "horizon-level",
        "unit": "duration",
    },
    {
        "name": "forward_ic_half_life_crossing_baseline_seconds",
        "meaning": "网格半幅交叉基准 horizon 的秒数。",
        "scope": "horizon-level",
        "unit": "seconds",
    },
    {
        "name": "forward_ic_half_life_crossing_baseline_mean_ic",
        "meaning": "网格半幅交叉使用的基准 horizon 平均 IC；阈值为其方向对齐绝对值的一半。",
        "scope": "horizon-level",
        "unit": "IC",
    },
    {
        "name": "forward_ic_half_life_crossing_half_amplitude_ic",
        "meaning": "网格半幅交叉的方向对齐半幅阈值。",
        "scope": "horizon-level",
        "unit": "IC",
    },
    {
        "name": "forward_ic_half_life_crossing_first_horizon",
        "meaning": "首次达到或低于半幅阈值的右侧 horizon；不是精确交叉时间。",
        "scope": "horizon-level",
        "unit": "duration",
    },
    {
        "name": "forward_ic_half_life_crossing_curve_monotonic_nonincreasing",
        "meaning": "方向对齐后的网格 horizon IC 是否单调不增；网格交叉估计仍需结合该诊断阅读。",
        "scope": "horizon-level",
        "unit": "boolean",
    },
    {
        "name": "ic_method",
        "meaning": "横截面相关方法；rank 表示 Spearman Rank IC，pearson 表示 Pearson IC。",
        "scope": "metadata",
        "unit": "method",
    },
    {
        "name": "forward_return_horizon",
        "meaning": "因子值与未来收益标签之间的持有/预测 horizon；不是 IC 序列滚动窗口。",
        "scope": "horizon-level",
        "unit": "duration",
    },
    {
        "name": "entry_delay_bars",
        "meaning": "进入收益标签前的信号步延迟；不等同于 forward-return horizon。",
        "scope": "horizon-level",
        "unit": "signal steps",
    },
    {
        "name": "factor_alias",
        "meaning": "因子表达式别名；用于定位对象，不参与统计量计算。",
        "scope": "metadata",
        "unit": "reference",
    },
    {
        "name": "factor_ref",
        "meaning": "不可变因子表达式引用；用于追溯具体因子版本，不参与统计量计算。",
        "scope": "metadata",
        "unit": "reference",
    },
    {
        "name": "mean",
        "meaning": "兼容别名，等同于 mean_ic；新 UI 应显示 mean_ic。",
        "scope": "deprecated-alias",
        "unit": "IC",
        "deprecated": True,
        "alias_of": "mean_ic",
    },
    {
        "name": "std",
        "meaning": "兼容别名，等同于 std_ic；新 UI 应显示 std_ic。",
        "scope": "deprecated-alias",
        "unit": "IC",
        "deprecated": True,
        "alias_of": "std_ic",
    },
    {
        "name": "IR",
        "meaning": "兼容别名，等同于 icir_signal；不是交易组合 Sharpe。",
        "scope": "deprecated-alias",
        "unit": "ratio",
        "deprecated": True,
        "alias_of": "icir_signal",
    },
    {
        "name": "t_stat",
        "meaning": "兼容别名，等同于 t_stat_iid；不代表 HAC t。",
        "scope": "deprecated-alias",
        "unit": "t-stat",
        "deprecated": True,
        "alias_of": "t_stat_iid",
    },
    {
        "name": "ac1",
        "meaning": "兼容别名，等同于 ic_series_acf1。",
        "scope": "deprecated-alias",
        "unit": "correlation",
        "deprecated": True,
        "alias_of": "ic_series_acf1",
    },
    {
        "name": "half_life",
        "meaning": "兼容别名，等同于 ic_series_acf_half_life_signals；不是持有期半衰期。",
        "scope": "deprecated-alias",
        "unit": "signal steps",
        "deprecated": True,
        "alias_of": "ic_series_acf_half_life_signals",
    },
)


_IC_METRIC_DISPLAY_LABELS = {
    "n_signal_observations": "有效 IC 信号数",
    "mean_ic": "平均 IC",
    "median_ic": "IC 中位数",
    "std_ic": "IC 样本标准差",
    "se_iid": "IID 均值标准误",
    "se_hac": "HAC 均值标准误",
    "icir_signal": "信号级 ICIR",
    "t_stat_iid": "IID t 值",
    "t_stat_hac": "HAC t 值",
    "direction_rate": "预期方向命中率",
    "positive_ic_rate": "正 IC 比例",
    "negative_ic_rate": "负 IC 比例",
    "zero_ic_rate": "零 IC 比例",
    "effective_n_raw": "原始 ESS",
    "effective_n_capped": "截断 ESS",
    "ic_series_acf1": "IC 序列 ACF(1)",
    "ic_series_acf_half_life_signals": "ACF 持久性半衰期（信号步）",
    "ic_series_ar1_half_life_signals": "AR(1) 持久性半衰期（信号步）",
    "ic_series_ar1_half_life_seconds": "AR(1) 持久性半衰期（秒）",
    "forward_ic_half_life": "forward-IC 半幅半衰期",
    "forward_ic_half_life_exponential": "forward-IC 指数拟合半衰期",
    "forward_ic_half_life_exponential_seconds": "预测性持有期半衰期（秒）",
    "forward_return_horizon": "未来收益持有期",
    "entry_delay_bars": "入场延迟（信号步）",
    "hac_lag": "HAC lag（信号步）",
    "hac_status": "HAC 状态",
    "ess_exceeds_n": "raw ESS 是否超过 n",
    "skew_ic": "IC 偏度",
    "excess_kurtosis_ic": "IC 超额峰度",
}


# ``ic_metric_selection`` is deliberately a projection contract.  The IC
# engine may compute the complete diagnostic set once, while the immutable
# response/report keeps only the requested fields.  This avoids changing the
# numerical meaning of existing jobs and makes the selected set auditable.
_IC_METRIC_GROUPS: dict[str, tuple[str, ...]] = {
    "core": (
        "n_signal_observations", "mean_ic", "median_ic", "std_ic",
        "std_ic_ddof", "se_iid", "ci95_iid_lower", "ci95_iid_upper",
        "mad_ic", "icir_signal", "t_stat_iid", "mean", "std", "IR", "t_stat",
    ),
    "direction": (
        "expected_sign", "expected_sign_source", "direction_rate",
        "direction_rate_status", "positive_ic_rate", "negative_ic_rate",
        "zero_ic_rate",
    ),
    "distribution": (
        "minimum_ic", "maximum_ic", "p10_ic", "p25_ic", "p50_ic",
        "p75_ic", "p90_ic", "skew_ic", "excess_kurtosis_ic",
        "minimum", "maximum",
    ),
    "inference": (
        "t_stat_hac", "se_hac", "ci95_hac_lower", "ci95_hac_upper",
        "hac_lag", "hac_lag_source", "hac_lag_formula", "hac_kernel",
        "hac_status", "hac_reason", "hac_overlap_support_seconds",
        "hac_overlap_support_components_seconds", "effective_n_raw",
        "effective_n_capped", "effective_n_ratio", "effective_n_capped_ratio",
        "ess_exceeds_n", "hac_lrv_to_iid_variance_ratio", "ess_definition",
        "t_stat_hac_reference",
    ),
    "persistence": (
        "ic_series_acf1", "acf_estimator", "ic_series_acf_half_life_signals",
        "ic_series_acf_half_life_status", "ic_series_ar1_rho",
        "ic_series_ar1_r_squared", "ic_series_ar1_half_life_status",
        "ic_series_ar1_half_life_signals", "ic_series_ar1_half_life_seconds",
        "ic_series_ar1_n_signal_pairs", "ic_series_ar1_method", "ac1", "half_life",
    ),
    "holding_half_life": tuple(
        str(item["name"])
        for item in IC_METRIC_SEMANTICS
        if str(item["name"]).startswith("forward_ic_half_life")
    ),
    "metadata": (
        "diagnostics_schema", "rolling_k_signals", "rolling_actual_endpoint_span_seconds",
        "rolling_expected_endpoint_span_seconds", "rolling_expected_coverage_span_seconds",
        "period_estimability", "hac_lag_formula", "acf_estimator", "std_ic_ddof",
        "forward_return_horizon", "entry_delay_bars", "ic_method",
    ),
}

_IC_METRIC_NAMES = frozenset(
    str(item["name"]) for item in IC_METRIC_SEMANTICS
)
_IC_METRIC_SELECTION_NAMES = frozenset(
    set(_IC_METRIC_NAMES).union(*_IC_METRIC_GROUPS.values())
)


def _expand_ic_metric_tokens(tokens: Iterable[Any]) -> set[str]:
    expanded: set[str] = set()
    for raw in tokens:
        token = str(raw or "").strip()
        if not token:
            continue
        if token == "all":
            expanded.update(_IC_METRIC_NAMES)
            continue
        group = _IC_METRIC_GROUPS.get(token)
        if group is not None:
            expanded.update(group)
            continue
        if token == "ci95_iid":
            expanded.update({"ci95_iid_lower", "ci95_iid_upper"})
            continue
        if token == "ci95_hac":
            expanded.update({"ci95_hac_lower", "ci95_hac_upper"})
            continue
        if token in {"forward_ic_half_life", "forward_ic_half_life_exponential"}:
            expanded.update(
                name for name in _IC_METRIC_NAMES
                if name.startswith(token)
            )
            continue
        if token not in _IC_METRIC_SELECTION_NAMES:
            raise ValueError(
                f"unsupported IC metric {token!r}; available fields: "
                + ", ".join(sorted(_IC_METRIC_NAMES))
                + "; groups: " + ", ".join(sorted(_IC_METRIC_GROUPS))
            )
        expanded.add(token)
    return expanded


def normalize_ic_metric_selection(value: Any = None) -> dict[str, Any]:
    """Normalize per-run IC metric projection; omitted means all metrics.

    Accepted forms are ``["core", "inference"]`` or
    ``{"include": [...], "exclude": [...]}``.  Groups expand to stable
    canonical field names, and the normalized set is persisted with the
    result so a report reader never has to infer what was omitted.
    """

    if value in (None, ""):
        return {
            "mode": "all", "requested": [], "excluded": [],
            "resolved": sorted(_IC_METRIC_NAMES),
        }
    if (
        isinstance(value, dict)
        and value.get("mode") in {"all", "selected"}
        and isinstance(value.get("resolved"), list)
    ):
        resolved = _expand_ic_metric_tokens(value.get("resolved") or ())
        return {
            "mode": "all" if value.get("mode") == "all" else "selected",
            "requested": [str(item) for item in value.get("requested") or ()],
            "excluded": [str(item) for item in value.get("excluded") or ()],
            "resolved": sorted(resolved),
            "implicit_dependencies": [
                str(item) for item in value.get("implicit_dependencies") or ()
            ],
        }
    if isinstance(value, (list, tuple)):
        include = list(value)
        exclude: list[Any] = []
    elif isinstance(value, dict):
        mode = str(value.get("mode") or "").strip().lower()
        include_raw = value.get("include", value.get("metrics"))
        exclude_raw = value.get("exclude", [])
        if include_raw is None and mode not in {"all", ""}:
            raise ValueError("ic_metric_selection.include must be an array")
        include = list(include_raw) if isinstance(include_raw, (list, tuple)) else (
            [include_raw] if include_raw not in (None, "") else []
        )
        exclude = list(exclude_raw) if isinstance(exclude_raw, (list, tuple)) else (
            [exclude_raw] if exclude_raw not in (None, "") else []
        )
    else:
        raise ValueError("ic_metric_selection must be an array or object")

    requested = [str(item).strip() for item in include if str(item).strip()]
    excluded = [str(item).strip() for item in exclude if str(item).strip()]
    include_set = _expand_ic_metric_tokens(requested) if requested else set(_IC_METRIC_NAMES)
    exclude_set = _expand_ic_metric_tokens(excluded)
    resolved = include_set - exclude_set
    implicit_dependencies = (
        ["mean_ic"]
        if any(name.startswith("forward_ic_half_life") for name in resolved)
        else []
    )
    return {
        "mode": "all" if not requested and not excluded else "selected",
        "requested": requested,
        "excluded": excluded,
        "resolved": sorted(resolved),
        "implicit_dependencies": implicit_dependencies,
    }


def ic_metric_selected(selection: dict[str, Any] | None, name: str) -> bool:
    """Return whether one output field survives the normalized projection."""

    if not isinstance(selection, dict) or selection.get("mode") == "all":
        return True
    return str(name) in set(selection.get("resolved") or ())


def filter_ic_metric_mapping(
    payload: dict[str, Any], selection: dict[str, Any] | None,
    *, preserve: Iterable[str] = (),
) -> dict[str, Any]:
    """Filter a flat stats mapping while preserving identity/structural keys."""

    if not isinstance(payload, dict) or not isinstance(selection, dict) or selection.get("mode") == "all":
        return dict(payload)
    keep = {str(item) for item in preserve}
    resolved = set(selection.get("resolved") or ())
    # The horizon half-life fit is a projection over forward-horizon mean IC;
    # retain that dependency even when the caller selected only the fit fields.
    if any(name.startswith("forward_ic_half_life") for name in resolved):
        resolved.add("mean_ic")
    return {
        key: value for key, value in payload.items()
        if key in keep or key in resolved
    }


def ic_metric_selection_catalog() -> list[dict[str, Any]]:
    """Return selectable groups and fields for CLI/UI clients."""

    return [
        {
            "name": group,
            "kind": "group",
            "metrics": list(fields),
            "display_label": group,
        }
        for group, fields in sorted(_IC_METRIC_GROUPS.items())
    ] + [
        {
            "name": name,
            "kind": "field",
            "metrics": [name],
            "display_label": _IC_METRIC_DISPLAY_LABELS.get(name, name),
        }
        for name in sorted(_IC_METRIC_NAMES)
    ]


def metric_semantics_catalog() -> list[dict[str, Any]]:
    """Return a JSON-safe copy for the IC response."""

    return [
        {
            **dict(item),
            "display_label": _IC_METRIC_DISPLAY_LABELS.get(
                str(item["name"]), str(item["name"]),
            ),
        }
        for item in IC_METRIC_SEMANTICS
    ]


def expected_sign_for_factor(factor: Any) -> tuple[int, str]:
    """Return the explicit direction convention used by the server response.

    ``$Rev`` is a factor construction direction flag.  It is reported as the
    source of the convention; it is never used for temporal/HAC lag inference.
    """

    alias = str(getattr(factor, "alias", "") or "")
    if "|$Rev" in alias or "$Rev:" in alias:
        return -1, "factor_alias:$Rev"
    return 1, "factor_alias:raw"


def _finite_values(values: Iterable[Any]) -> list[float]:
    output: list[float] = []
    for value in values:
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number):
            output.append(number)
    return output


def _quantile(values: list[float], probability: float) -> float | None:
    if not values:
        return None
    return float(np.quantile(np.asarray(values, dtype=float), probability))


def _mad(values: list[float]) -> float | None:
    if not values:
        return None
    center = float(statistics.median(values))
    return float(statistics.median([abs(value - center) for value in values]))


def _skewness(values: list[float]) -> float | None:
    if len(values) < 3:
        return None
    mean = statistics.mean(values)
    variance = statistics.mean([(value - mean) ** 2 for value in values])
    return statistics.mean([(value - mean) ** 3 for value in values]) / variance ** 1.5 if variance > 0 else None


def _excess_kurtosis(values: list[float]) -> float | None:
    if len(values) < 4:
        return None
    mean = statistics.mean(values)
    variance = statistics.mean([(value - mean) ** 2 for value in values])
    return statistics.mean([(value - mean) ** 4 for value in values]) / variance ** 2 - 3.0 if variance > 0 else None


def _acf(values: list[float]) -> list[float] | None:
    if len(values) <= 2:
        return None
    try:
        from statsmodels.tsa.stattools import acf

        nlags = min(20, max(1, len(values) // 2 - 1))
        return [float(value) for value in acf(np.asarray(values), nlags=nlags, fft=False)]
    except Exception:
        return None


def _acf_half_life(acf_values: list[float] | None) -> float | None:
    value, _status = _acf_half_life_diagnostic(acf_values)
    return value


def _acf_half_life_diagnostic(acf_values: list[float] | None) -> tuple[float | None, str]:
    if not acf_values or len(acf_values) < 2:
        return None, "not_estimable"
    if any(not math.isfinite(float(value)) for value in acf_values):
        return None, "not_estimable"
    for lag in range(1, len(acf_values)):
        previous = acf_values[lag - 1]
        current = acf_values[lag]
        # Reaching 0.5 is already the half-life boundary.  Treat equality as
        # a crossing so an exactly geometric sequence is not reported as
        # ``not_reached`` merely because of a strict comparison.
        if current <= 0.5:
            if current == previous:
                return float(lag - 1), "estimated"
            return float(lag - 1 + (0.5 - previous) / (current - previous)), "estimated"
    return float("inf"), "not_reached"


def _newey_west(values: list[float], lag: int | None) -> dict[str, Any]:
    n = len(values)
    if n < 2 or lag is None:
        return {
            "hac_lag": lag,
            "se_hac": None,
            "t_stat_hac": None,
            "effective_n_raw": None,
            "effective_n_capped": None,
            "effective_n_ratio": None,
            "effective_n_capped_ratio": None,
            "hac_lrv_to_iid_variance_ratio": None,
            "ess_exceeds_n": None,
        }
    mean = sum(values) / n
    centered = [value - mean for value in values]
    gamma0 = sum(value * value for value in centered) / n
    used_lag = max(0, min(int(lag), n - 1))
    long_run_variance = gamma0
    for current_lag in range(1, used_lag + 1):
        gamma = sum(
            centered[index] * centered[index - current_lag]
            for index in range(current_lag, n)
        ) / n
        weight = 1.0 - current_lag / (used_lag + 1.0)
        long_run_variance += 2.0 * weight * gamma
    long_run_variance = max(0.0, long_run_variance)
    se_hac = math.sqrt(long_run_variance / n) if long_run_variance > 0 else None
    t_stat_hac = mean / se_hac if se_hac not in (None, 0) else None
    effective_n_raw = (
        n * gamma0 / long_run_variance
        if long_run_variance > 0 and gamma0 > 0 else None
    )
    effective_n_capped = (
        min(float(n), max(1.0, effective_n_raw))
        if effective_n_raw is not None else None
    )
    return {
        "hac_lag": used_lag,
        "se_hac": se_hac,
        "t_stat_hac": t_stat_hac,
        "effective_n_raw": effective_n_raw,
        "effective_n_capped": effective_n_capped,
        "effective_n_ratio": effective_n_raw / n if effective_n_raw is not None else None,
        "effective_n_capped_ratio": effective_n_capped / n if effective_n_capped is not None else None,
        "hac_lrv_to_iid_variance_ratio": long_run_variance / gamma0 if gamma0 > 0 else None,
        "ess_exceeds_n": effective_n_raw is not None and effective_n_raw > n,
    }


def summarize_ic_series(
    ic_series: pd.Series,
    *,
    expected_sign: int | None = None,
    expected_sign_source: str | None = None,
    temporal_support: TemporalSupport | None = None,
    requested_hac_lag: int | None = None,
    max_hac_lag: int = 512,
) -> dict[str, Any]:
    """Compute explicit signal-level diagnostics for one realised IC series."""

    values = _finite_values(ic_series.tolist())
    n = len(values)
    mean = float(statistics.mean(values)) if values else None
    std = float(statistics.stdev(values)) if len(values) > 1 else None
    median = float(statistics.median(values)) if values else None
    icir = mean / std if mean is not None and std not in (None, 0) else None
    t_stat_iid = mean / (std / math.sqrt(n)) if mean is not None and std not in (None, 0) and n > 1 else None
    acf_values = _acf(values)
    ac1 = acf_values[1] if acf_values and len(acf_values) > 1 else None
    acf_half_life, acf_half_life_status = _acf_half_life_diagnostic(acf_values)
    ar1 = fit_ic_series_ar1_half_life(
        values,
        signal_interval_seconds=(
            temporal_support.signal_interval_seconds
            if temporal_support is not None else None
        ),
    )

    se_iid = std / math.sqrt(n) if std is not None and n > 1 else None
    ci95_iid = (
        (mean - 1.96 * se_iid, mean + 1.96 * se_iid)
        if mean is not None and se_iid is not None else (None, None)
    )

    if temporal_support is None:
        hac_resolution = {
            "hac_lag": None,
            "hac_lag_source": "temporal_support",
            "hac_status": "not_estimable",
            "hac_reason": "missing temporal support contract",
        }
    else:
        hac_resolution = resolve_hac_lag(
            temporal_support,
            requested_lag=requested_hac_lag,
            max_lag=max_hac_lag,
        ).to_dict()
    hac = _newey_west(values, hac_resolution.get("hac_lag"))
    se_hac = hac.get("se_hac")
    ci95_hac = (
        (mean - 1.96 * se_hac, mean + 1.96 * se_hac)
        if mean is not None and se_hac is not None else (None, None)
    )
    if temporal_support is None:
        hac_formula = None
        hac_overlap_support = None
        hac_overlap_components = None
    else:
        hac_formula = "ceil((factor_input + label + holding + decay) / signal_interval) - 1"
        hac_overlap_support = temporal_support.overlap_support_seconds
        hac_overlap_components = temporal_support.overlap_support_components_seconds

    result: dict[str, Any] = {
        "diagnostics_schema": IC_DIAGNOSTICS_SCHEMA,
        "n_signal_observations": n,
        "mean_ic": mean,
        "median_ic": median,
        "std_ic": std,
        "std_ic_ddof": 1,
        "se_iid": se_iid,
        "ci95_iid_lower": ci95_iid[0],
        "ci95_iid_upper": ci95_iid[1],
        "mad_ic": _mad(values),
        "icir_signal": icir,
        "t_stat_iid": t_stat_iid,
        "positive_ic_rate": sum(value > 0 for value in values) / n if n else None,
        "negative_ic_rate": sum(value < 0 for value in values) / n if n else None,
        "zero_ic_rate": sum(value == 0 for value in values) / n if n else None,
        "expected_sign": expected_sign,
        "expected_sign_source": expected_sign_source,
        "direction_rate": (
            sum(expected_sign * value > 0 for value in values) / n
            if expected_sign in (-1, 1) and n else None
        ),
        "direction_rate_status": "declared" if expected_sign in (-1, 1) else "not_declared",
        "minimum_ic": min(values) if values else None,
        "maximum_ic": max(values) if values else None,
        "p10_ic": _quantile(values, 0.10),
        "p25_ic": _quantile(values, 0.25),
        "p50_ic": _quantile(values, 0.50),
        "p75_ic": _quantile(values, 0.75),
        "p90_ic": _quantile(values, 0.90),
        "skew_ic": _skewness(values),
        "excess_kurtosis_ic": _excess_kurtosis(values),
        "ic_series_acf1": ac1,
        "ic_series_acf_half_life_signals": acf_half_life,
        "ic_series_acf_half_life_status": acf_half_life_status,
        "acf_estimator": "statsmodels.acf(adjusted=False, fft=False; denominator=n)",
        "ic_series_ar1_rho": ar1.get("rho"),
        "ic_series_ar1_r_squared": ar1.get("r_squared"),
        "ic_series_ar1_half_life_status": ar1.get("status"),
        "ic_series_ar1_half_life_signals": ar1.get("half_life_signals"),
        "ic_series_ar1_half_life_seconds": ar1.get("half_life_seconds"),
        "ic_series_ar1_n_signal_pairs": ar1.get("n_signal_pairs"),
        "ic_series_ar1_method": ar1.get("method"),
        "acf_vals": acf_values,
        "hac_kernel": "bartlett",
        "hac_lag_formula": hac_formula,
        "hac_overlap_support_seconds": hac_overlap_support,
        "hac_overlap_support_components_seconds": hac_overlap_components,
        "ess_definition": "n * gamma0 / long_run_variance; capped to [1,n] for effective_n_capped",
        "t_stat_hac_reference": "asymptotic_normal",
        **hac_resolution,
        **hac,
        "ci95_hac_lower": ci95_hac[0],
        "ci95_hac_upper": ci95_hac[1],
        # Compatibility aliases.  New consumers must use the explicit fields.
        "mean": mean,
        "std": std,
        "IR": icir,
        "t_stat": t_stat_iid,
        "max": max(values) if values else None,
        "min": min(values) if values else None,
        "ac1": ac1,
        "half_life": acf_half_life,
        "ic_series_acf_half_life": acf_half_life,
    }
    return result
