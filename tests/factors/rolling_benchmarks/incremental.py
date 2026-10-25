"""Benchmark live rolling kernels against the previous deque-based loop.

Run with ``conda run -n GTHT python tests/factors/bench_rolling_kernels.py``.
Parity is checked first; elapsed-time results are descriptive, not CI gates.
"""

from __future__ import annotations

import platform
import statistics
import sys
import time
from collections import deque
from collections.abc import Callable
from pathlib import Path

import numpy as np

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tools.factors.expr.rolling_regression import (
    ROLLING_LINEAR_METRICS,
    linear_metric,
)
from tools.factors.expr.streaming.rolling_statistics import (
    RollingStatisticsNode,
)


class _Rows:
    def __init__(self, values: np.ndarray) -> None:
        self.values = values
        self.position = 0

    def update(self, _market, _cache: dict[int, np.ndarray]) -> np.ndarray:
        value = self.values[self.position]
        self.position += 1
        return value


def _measure(
    function: Callable[[], np.ndarray],
    *,
    warmups: int,
    repeats: int,
) -> float:
    for _ in range(warmups):
        function()
    timings = []
    for _ in range(repeats):
        started = time.perf_counter()
        function()
        timings.append(time.perf_counter() - started)
    return statistics.median(timings)


def _reference(
    operation: str,
    rows: np.ndarray,
    window: int,
    *,
    quantile: float | None = None,
) -> np.ndarray:
    width = rows.shape[1]
    minimum = (
        max(3, window // 2)
        if operation in ROLLING_LINEAR_METRICS
        else max(1, window // 2)
    )
    history: deque[np.ndarray] = deque(maxlen=window)
    output = np.full(rows.shape, np.nan, dtype=float)
    for time_index, row in enumerate(rows):
        history.append(row.copy())
        window_values = np.asarray(history, dtype=float)
        for product_index in range(width):
            sample = window_values[:, product_index]
            finite = np.isfinite(sample)
            if finite.sum() < minimum:
                continue
            if operation in ROLLING_LINEAR_METRICS:
                output[time_index, product_index] = linear_metric(
                    sample,
                    operation,
                    minimum,
                )
                continue
            sample = sample[finite]
            if operation == "rolling_mad":
                median = np.median(sample)
                output[time_index, product_index] = np.median(
                    np.abs(sample - median),
                )
            elif operation == "rolling_median":
                output[time_index, product_index] = np.median(sample)
            elif operation == "rolling_quantile":
                if quantile is None:
                    raise ValueError("quantile must be provided")
                output[time_index, product_index] = np.quantile(
                    sample,
                    quantile,
                )
            else:
                raise ValueError(f"unsupported benchmark operation: {operation}")
    return output


def _run_node(
    operation: str,
    rows: np.ndarray,
    window: int,
    *,
    quantile: float | None = None,
) -> np.ndarray:
    node = RollingStatisticsNode(
        operation,
        _Rows(rows),
        window,
        rows.shape[1],
        quantile=quantile,
    )
    output = np.empty(rows.shape, dtype=float)
    for index in range(len(rows)):
        output[index] = node.update(None, {})
    return output


def main() -> None:
    rng = np.random.default_rng(423)
    warmups, repeats = 1, 3
    print(
        f"Python {platform.python_version()} | NumPy {np.__version__} | "
        f"CPU {platform.processor() or 'unknown'}"
    )
    print(f"warmups={warmups}, repeats={repeats}; median elapsed time")

    rows, width, window = 2_000, 8, 63
    values = rng.normal(loc=10_000.0, scale=3.0, size=(rows, width))
    values[::101, 0] = np.nan
    values[::137, 1] = np.inf
    operations = (
        ("rolling_median", None),
        ("rolling_quantile", 0.35),
        ("rolling_mad", None),
        ("rolling_linreg_slope", None),
        ("rolling_linreg_r2", None),
        ("rolling_linreg_tstat", None),
        ("rolling_linreg_resid_std", None),
    )
    for operation, quantile in operations:
        expected = _reference(operation, values, window, quantile=quantile)
        actual = _run_node(operation, values, window, quantile=quantile)
        np.testing.assert_allclose(
            actual,
            expected,
            rtol=2e-7,
            atol=2e-7,
            equal_nan=True,
        )
        reference_time = _measure(
            lambda operation=operation, quantile=quantile: _reference(
                operation,
                values,
                window,
                quantile=quantile,
            ),
            warmups=warmups,
            repeats=repeats,
        )
        optimized_time = _measure(
            lambda operation=operation, quantile=quantile: _run_node(
                operation,
                values,
                window,
                quantile=quantile,
            ),
            warmups=warmups,
            repeats=repeats,
        )
        print(
            f"incremental {operation:<25s} {rows}x{width}, W={window}  "
            f"reference={reference_time:8.4f}s  optimized={optimized_time:8.4f}s  "
            f"speedup={reference_time / optimized_time:6.2f}x"
        )


if __name__ == "__main__":
    main()
