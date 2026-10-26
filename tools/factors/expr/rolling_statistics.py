"""Batch kernels for robust and regression-based rolling statistics."""

from __future__ import annotations

import pandas as pd

from .rolling_mad import rolling_mad_batch
from .rolling_regression import ROLLING_LINEAR_METRICS, rolling_linear_metric
from .rolling_skew import rolling_skew_batch

ROLLING_ROBUST_STATISTICS = frozenset(
    {
        "rolling_median",
        "rolling_quantile",
        "rolling_mad",
    }
)
ROLLING_STATISTICS = ROLLING_ROBUST_STATISTICS | ROLLING_LINEAR_METRICS


def apply_rolling_statistic(
    op: str,
    data: pd.DataFrame,
    window: int,
    *,
    quantile: float | None = None,
    min_periods: int | None = None,
    propagate_nan: bool = True,
) -> pd.DataFrame:
    if op in ROLLING_LINEAR_METRICS:
        return rolling_linear_metric(
            data, window, op,
            min_periods=min_periods, propagate_nan=propagate_nan,
        )
    if op == "rolling_skew":
        return rolling_skew_batch(data, window)
    minimum = max(1, window if min_periods is None else min_periods)
    if op == "rolling_median":
        return data.rolling(window, min_periods=minimum).median()
    if op == "rolling_quantile":
        if quantile is None:
            raise ValueError("rolling_quantile requires q")
        return data.rolling(window, min_periods=minimum).quantile(quantile)
    if op == "rolling_mad":
        return rolling_mad_batch(data, window, min_periods=minimum)
    raise ValueError(f"Unknown rolling statistic: {op}")
