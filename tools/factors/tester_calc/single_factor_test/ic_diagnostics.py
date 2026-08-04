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
        "meaning": "按显式 temporal-support 解析 lag 后的 Newey-West 均值 t 值。",
        "scope": "signal-level",
        "unit": "t-stat",
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
        "name": "forward_ic_half_life",
        "meaning": "不同 forward-return horizon 的 IC 均值相对基准半幅交叉，单位是 horizon 时间。",
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
)


def metric_semantics_catalog() -> list[dict[str, Any]]:
    """Return a JSON-safe copy for the IC response."""

    return [dict(item) for item in IC_METRIC_SEMANTICS]


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
    if not acf_values or len(acf_values) < 2:
        return None
    for lag in range(1, len(acf_values)):
        previous = acf_values[lag - 1]
        current = acf_values[lag]
        if current < 0.5:
            if current == previous:
                return float(lag - 1)
            return float(lag - 1 + (0.5 - previous) / (current - previous))
    return float("inf")


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
    acf_half_life = _acf_half_life(acf_values)

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

    result: dict[str, Any] = {
        "diagnostics_schema": IC_DIAGNOSTICS_SCHEMA,
        "n_signal_observations": n,
        "mean_ic": mean,
        "median_ic": median,
        "std_ic": std,
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
        "acf_vals": acf_values,
        **hac_resolution,
        **hac,
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
