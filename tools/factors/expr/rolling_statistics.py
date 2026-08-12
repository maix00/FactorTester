"""Batch kernels for robust and regression-based rolling statistics."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .rolling_regression import ROLLING_LINEAR_METRICS, rolling_linear_metric


ROLLING_ROBUST_STATISTICS = frozenset({
    "rolling_median",
    "rolling_quantile",
    "rolling_mad",
})
ROLLING_STATISTICS = ROLLING_ROBUST_STATISTICS | ROLLING_LINEAR_METRICS


def apply_rolling_statistic(
    op: str,
    data: pd.DataFrame,
    window: int,
    *,
    quantile: float | None = None,
) -> pd.DataFrame:
    if op in ROLLING_LINEAR_METRICS:
        return rolling_linear_metric(data, window, op)
    minimum = max(1, window // 2)
    if op == "rolling_median":
        return data.rolling(window, min_periods=minimum).median()
    if op == "rolling_quantile":
        if quantile is None:
            raise ValueError("rolling_quantile requires q")
        return data.rolling(window, min_periods=minimum).quantile(quantile)
    if op == "rolling_mad":
        return data.rolling(window, min_periods=minimum).apply(
            lambda values: np.nanmedian(
                np.abs(values - np.nanmedian(values))
            ),
            raw=True,
        )
    raise ValueError(f"Unknown rolling statistic: {op}")
