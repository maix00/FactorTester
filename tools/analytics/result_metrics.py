"""Registry for result-level performance metrics.

This module intentionally stays separate from ``tools.traderules``. Trading
rules affect execution, ledger state, fees, margin, and settlement. Result
metrics are derived after the run from already-produced curves.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping, cast

import pandas as pd


MetricValue = float | int | str | None
MetricFunction = Callable[["ResultMetricContext"], MetricValue]


@dataclass(frozen=True)
class ResultMetricContext:
    equity: pd.Series
    returns: pd.Series


@dataclass(frozen=True)
class ResultMetric:
    key: str
    label: str
    compute: MetricFunction
    description: str = ""


_RESULT_METRICS: dict[str, ResultMetric] = {}
_DEFAULT_METRICS_REGISTERED = False
_EPS = 1e-12


def register_result_metric(metric: ResultMetric) -> ResultMetric:
    if not metric.key:
        raise ValueError("metric key is required")
    _RESULT_METRICS[str(metric.key)] = metric
    return metric


def unregister_result_metric(key: str) -> None:
    _RESULT_METRICS.pop(str(key), None)


def registered_result_metrics() -> Mapping[str, ResultMetric]:
    _ensure_default_metrics()
    return dict(_RESULT_METRICS)


def result_metric_manifest() -> list[dict[str, object]]:
    _ensure_default_metrics()
    return [
        {
            "key": metric.key,
            "label": metric.label,
            "description": metric.description,
        }
        for metric in _RESULT_METRICS.values()
    ]


def compute_result_metrics(equity: pd.Series, returns: pd.Series) -> dict[str, MetricValue]:
    _ensure_default_metrics()
    ctx = ResultMetricContext(equity=equity, returns=returns)
    return {key: metric.compute(ctx) for key, metric in _RESULT_METRICS.items()}


def _ensure_default_metrics() -> None:
    global _DEFAULT_METRICS_REGISTERED
    if _DEFAULT_METRICS_REGISTERED:
        return
    for metric in (
        ResultMetric("annual_return", "年化收益率", _annual_return),
        ResultMetric("sharpe_ratio", "夏普比率", _sharpe_ratio),
        ResultMetric("max_drawdown", "最大回撤", _max_drawdown),
        ResultMetric("sortino_ratio", "索提诺比率", _sortino_ratio),
        ResultMetric("calmar_ratio", "卡玛比率", _calmar_ratio),
        ResultMetric("win_rate", "胜率", _win_rate),
        ResultMetric("skewness", "偏度", _skewness),
        ResultMetric("kurtosis", "峰度", _kurtosis),
        ResultMetric("avg_turnover", "平均换手", _avg_turnover),
    ):
        register_result_metric(metric)
    _DEFAULT_METRICS_REGISTERED = True


def _annual_return(ctx: ResultMetricContext) -> float:
    equity = ctx.equity.dropna()
    if len(equity) < 2:
        return 0.0
    start = float(cast(float, equity.iloc[0]))
    end = float(cast(float, equity.iloc[-1]))
    if start <= 0 or end <= 0:
        return 0.0
    start_ts = pd.Timestamp(equity.index[0])
    end_ts = pd.Timestamp(equity.index[-1])
    elapsed_days = (end_ts - start_ts).total_seconds() / 86400.0
    if elapsed_days <= 0:
        return 0.0
    return float((end / start) ** (365.25 / elapsed_days) - 1.0)


def _sharpe_ratio(ctx: ResultMetricContext) -> float:
    returns = ctx.returns
    if returns.empty:
        return 0.0
    mean_return = float(cast(float, returns.mean()))
    std = float(cast(float, returns.std()))
    return mean_return / std if pd.notna(std) and std > _EPS else 0.0


def _max_drawdown(ctx: ResultMetricContext) -> float:
    equity = ctx.equity
    if equity.empty:
        return 0.0
    cummax = equity.cummax()
    drawdown = equity / cummax - 1.0
    return float(cast(float, drawdown.min()))


def _sortino_ratio(ctx: ResultMetricContext) -> float:
    returns = ctx.returns
    if returns.empty:
        return 0.0
    downside = returns[returns < 0]
    downside_std = float(cast(float, downside.std()))
    mean_return = float(cast(float, returns.mean()))
    return mean_return / downside_std if pd.notna(downside_std) and downside_std > _EPS else 0.0


def _calmar_ratio(ctx: ResultMetricContext) -> float:
    max_drawdown = _max_drawdown(ctx)
    if not max_drawdown:
        return 0.0
    return _annual_return(ctx) / abs(max_drawdown)


def _win_rate(ctx: ResultMetricContext) -> float:
    returns = ctx.returns
    if returns.empty:
        return 0.0
    return float(cast(float, (returns > 0).mean()))


def _skewness(ctx: ResultMetricContext) -> float:
    returns = ctx.returns
    return float(cast(float, returns.skew())) if len(returns) >= 3 else 0.0


def _kurtosis(ctx: ResultMetricContext) -> float:
    returns = ctx.returns
    return float(cast(float, returns.kurt())) if len(returns) >= 4 else 0.0


def _avg_turnover(ctx: ResultMetricContext) -> float:
    return 0.0
