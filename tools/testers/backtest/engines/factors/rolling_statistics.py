"""Streaming nodes for robust statistics and time-trend regressions."""
from __future__ import annotations

from collections import deque
from typing import Any

import numpy as np

from tools.factors.expr.rolling_regression import (
    ROLLING_LINEAR_METRICS,
    linear_metric,
)
from tools.factors.expr.rolling_statistics import ROLLING_STATISTICS


class RollingStatisticsNode:
    def __init__(
        self,
        op: str,
        child: Any,
        window: int,
        width: int,
        *,
        quantile: float | None = None,
    ) -> None:
        self.op = op
        self.child = child
        self.window = window
        self.width = width
        self.quantile = quantile
        self.history: deque[np.ndarray] = deque(maxlen=window)

    def update(self, market, cache: dict[int, np.ndarray]) -> np.ndarray:
        key = id(self)
        if key in cache:
            return cache[key]
        self.history.append(self.child.update(market, cache).copy())
        values = np.asarray(self.history, dtype=float)
        output = np.full(self.width, np.nan, dtype=float)
        minimum = (
            max(3, self.window // 2)
            if self.op in ROLLING_LINEAR_METRICS
            else max(1, self.window // 2)
        )
        for column in range(self.width):
            sample = values[:, column]
            finite = sample[np.isfinite(sample)]
            if len(finite) < minimum:
                continue
            if self.op == "rolling_median":
                output[column] = np.median(finite)
            elif self.op == "rolling_quantile":
                output[column] = np.quantile(finite, self.quantile)
            elif self.op == "rolling_mad":
                median = np.median(finite)
                output[column] = np.median(np.abs(finite - median))
            else:
                output[column] = linear_metric(sample, self.op, minimum)
        cache[key] = output
        return output
