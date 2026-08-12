"""Shared return metrics for event and vectorized portfolio projections."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from tools.data.types.time_index import DataIndex


PORTFOLIO_METRIC_SEMANTICS: tuple[dict[str, str], ...] = (
    {"name": "Total Return", "meaning": "单位权益下各期收益复合后的累计收益", "unit": "percent", "scope": "portfolio"},
    {"name": "Annual Return", "meaning": "按有效观测频率年化的累计收益", "unit": "percent", "scope": "portfolio"},
    {"name": "Volatility", "meaning": "各期收益样本标准差按有效观测频率年化", "unit": "percent", "scope": "portfolio"},
    {"name": "Sharpe Ratio", "meaning": "平均期收益除以期收益标准差并年化", "unit": "ratio", "scope": "portfolio"},
    {"name": "Max Drawdown", "meaning": "单位权益曲线相对历史峰值的最大回撤", "unit": "percent", "scope": "portfolio"},
    {"name": "Calmar Ratio", "meaning": "年化收益率与最大回撤的比值", "unit": "ratio", "scope": "portfolio"},
    {"name": "Win Rate", "meaning": "正收益期占有效收益期的比例", "unit": "percent", "scope": "portfolio"},
    {"name": "Mean Return", "meaning": "有效期收益的算术平均", "unit": "percent", "scope": "portfolio"},
    {"name": "Skewness", "meaning": "有效期收益分布偏度", "unit": "ratio", "scope": "portfolio"},
    {"name": "Kurtosis", "meaning": "有效期收益分布超额峰度", "unit": "ratio", "scope": "portfolio"},
    {"name": "Avg Turnover", "meaning": "相邻观测组合名义权重绝对变化的平均值；具体口径由 turnover_semantics 声明", "unit": "decimal_ratio", "scope": "portfolio_turnover"},
)


def portfolio_metric_semantics_catalog() -> list[dict[str, str]]:
    return [dict(item) for item in PORTFOLIO_METRIC_SEMANTICS]


def infer_periods_per_year(index_like: Any) -> float:
    index = DataIndex(pd.Index(index_like)).signal_index.dropna()
    if len(index) < 2:
        return 252.0
    per_day = pd.Series(1, index=index.normalize()).groupby(level=0).sum()
    median_per_day = float(per_day.median()) if not per_day.empty else 1.0
    if median_per_day > 1:
        return median_per_day * 252.0
    days = pd.DatetimeIndex(per_day.index).sort_values()
    if len(days) < 2:
        return 252.0
    business_days = np.busday_count(
        days[0].date().isoformat(),
        (days[-1] + pd.Timedelta(days=1)).date().isoformat(),
    )
    return max(1.0, len(days) / business_days * 252.0) if business_days > 0 else 252.0


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if np.isfinite(number) else None


def compute_return_metrics(
    returns: Any,
    *,
    index_like: Any = None,
    avg_turnover: Any = None,
) -> dict[str, Any]:
    """Return the canonical grouped-backtest metrics.

    ``returns`` are decimal period returns. Percentage-valued fields retain the
    historical event-projection convention, so both paths can be compared
    without a second formula implementation.
    """
    series = pd.Series(np.asarray(returns, dtype=float)).replace([np.inf, -np.inf], np.nan).dropna()
    if series.empty:
        return {}
    periods = infer_periods_per_year(index_like) if index_like is not None else 252.0
    wealth = (1.0 + series).cumprod()
    drawdown = (wealth.cummax() - wealth) / wealth.cummax()
    annual_return = _finite((wealth.iloc[-1] ** (periods / len(series)) - 1.0) * 100) if len(series) > 1 else None
    std = float(series.std())
    return {
        "Total Return": _finite((wealth.iloc[-1] - 1.0) * 100),
        "Annual Return": annual_return,
        "Volatility": _finite(std * periods**0.5 * 100),
        "Sharpe Ratio": _finite(series.mean() * periods / (std * periods**0.5)) if std else None,
        "Max Drawdown": _finite(drawdown.max() * 100),
        "Calmar Ratio": _finite(float(annual_return) / float(drawdown.max() * 100)) if annual_return and drawdown.max() else None,
        "Win Rate": _finite((series > 0).mean() * 100),
        "Mean Return": _finite(series.mean() * 100),
        "Skewness": _finite(series.skew()),
        "Kurtosis": _finite(series.kurtosis()),
        "Avg Turnover": _finite(avg_turnover),
    }


__all__ = [
    "PORTFOLIO_METRIC_SEMANTICS", "portfolio_metric_semantics_catalog",
    "infer_periods_per_year", "compute_return_metrics",
]
