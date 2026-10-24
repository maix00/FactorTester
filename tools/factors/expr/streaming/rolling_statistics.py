"""Streaming nodes for robust statistics and time-trend regressions."""

from __future__ import annotations

from typing import Any

import numpy as np

from tools.factors.expr.rolling_regression import (
    ROLLING_LINEAR_METRICS,
)
from tools.factors.expr.rolling_regression_state import RollingLinearState
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
        if op not in ROLLING_STATISTICS:
            raise ValueError(f"Unknown rolling statistic: {op}")
        self.op = op
        self.child = child
        self.window = window
        self.width = width
        self.quantile = quantile
        self._linear_state = (
            RollingLinearState(window, width, op)
            if op in ROLLING_LINEAR_METRICS
            else None
        )
        self._history = (
            None
            if self._linear_state is not None
            else np.full((width, window), np.nan, dtype=float)
        )
        self._cursor = 0
        self._length = 0

    def update(self, market, cache: dict[int, np.ndarray]) -> np.ndarray:
        key = id(self)
        if key in cache:
            return cache[key]
        values = np.asarray(self.child.update(market, cache), dtype=float)
        if values.shape != (self.width,):
            raise ValueError("streaming rolling input width changed unexpectedly")
        if self._linear_state is not None:
            output = self._linear_state.update(values)
            cache[key] = output
            return output

        assert self._history is not None
        self._history[:, self._cursor] = values
        self._cursor = (self._cursor + 1) % self.window
        self._length = min(self.window, self._length + 1)
        window_values = self._history[:, : self._length]
        output = np.full(self.width, np.nan, dtype=float)
        minimum = max(1, self.window // 2)
        if self.op == "rolling_quantile" and self.quantile is None:
            raise ValueError("rolling_quantile requires q")
        for product_index, history in enumerate(window_values):
            sample = history[np.isfinite(history)]
            if sample.size < minimum:
                continue
            if self.op == "rolling_median":
                output[product_index] = np.median(
                    sample,
                    overwrite_input=True,
                )
            elif self.op == "rolling_quantile":
                output[product_index] = np.quantile(
                    sample,
                    self.quantile,
                    overwrite_input=True,
                )
            elif self.op == "rolling_mad":
                median = np.median(sample, overwrite_input=True)
                np.subtract(sample, median, out=sample)
                np.abs(sample, out=sample)
                output[product_index] = np.median(
                    sample,
                    overwrite_input=True,
                )
            else:
                raise ValueError(f"Unknown rolling statistic: {self.op}")
        cache[key] = output
        return output
