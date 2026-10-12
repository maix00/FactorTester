"""Benchmark precomputed rolling kernels against scalar reference paths.

Run with ``conda run -n GTHT python tests/factors/bench_rolling_kernels.py``.
It checks numerical parity before timing and has no hardware-specific limits.
"""

from __future__ import annotations

import platform
import statistics
import sys
import time
from collections.abc import Callable
from pathlib import Path

import numpy as np
import pandas as pd

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tools.factors.expr.rolling_mad import rolling_mad_batch
from tools.factors.expr.rolling_regression import (
    linear_metric,
    rolling_linear_metric,
)
from tools.factors.expr.rolling_skew import rolling_skew_batch


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


def _reference_mad(frame: pd.DataFrame, window: int, minimum: int) -> pd.DataFrame:
    return frame.rolling(window, min_periods=minimum).apply(
        lambda sample: np.nanmedian(np.abs(sample - np.nanmedian(sample))),
        raw=True,
    )


def _scalar_rolling_slope(values: np.ndarray, window: int) -> np.ndarray:
    minimum = max(3, window // 2)
    result = np.full(values.shape, np.nan, dtype=float)
    for row in range(len(values)):
        start = max(0, row - window + 1)
        for column in range(values.shape[1]):
            result[row, column] = linear_metric(
                values[start : row + 1, column],
                "rolling_linreg_slope",
                minimum,
            )
    return result


def _report(label: str, reference: float, optimized: float) -> None:
    print(
        f"{label:<42s} reference={reference:8.4f}s  "
        f"optimized={optimized:8.4f}s  speedup={reference / optimized:6.2f}x"
    )


def main() -> None:
    rng = np.random.default_rng(423)
    warmups, repeats = 1, 3
    print(
        f"Python {platform.python_version()} | NumPy {np.__version__} | "
        f"pandas {pd.__version__} | CPU {platform.processor() or 'unknown'}"
    )
    print(f"warmups={warmups}, repeats={repeats}; median elapsed time")

    rows, width, window = 20_000, 16, 63
    values = rng.normal(size=(rows, width))
    values[::97, 0] = np.nan
    values[::113, 1] = np.inf
    frame = pd.DataFrame(values)
    minimum = max(1, window // 2)
    expected = _reference_mad(frame, window, minimum).to_numpy()
    actual = rolling_mad_batch(frame, window, min_periods=minimum).to_numpy()
    np.testing.assert_allclose(
        actual,
        expected,
        rtol=1e-12,
        atol=1e-12,
        equal_nan=True,
    )
    reference_time = _measure(
        lambda: _reference_mad(frame, window, minimum).to_numpy(),
        warmups=warmups,
        repeats=repeats,
    )
    optimized_time = _measure(
        lambda: rolling_mad_batch(frame, window, min_periods=minimum).to_numpy(),
        warmups=warmups,
        repeats=repeats,
    )
    _report(f"batch MAD {rows}x{width}, W={window}", reference_time, optimized_time)

    rows, width, window = 2_000, 8, 63
    values = rng.normal(loc=10_000.0, scale=3.0, size=(rows, width))
    values[::109, 2] = np.nan
    values[::149, 3] = np.inf
    frame = pd.DataFrame(values)
    expected = _scalar_rolling_slope(values, window)
    actual = rolling_linear_metric(
        frame,
        window,
        "rolling_linreg_slope",
    ).to_numpy()
    np.testing.assert_allclose(
        actual,
        expected,
        rtol=2e-7,
        atol=2e-7,
        equal_nan=True,
    )
    reference_time = _measure(
        lambda: _scalar_rolling_slope(values, window),
        warmups=warmups,
        repeats=repeats,
    )
    optimized_time = _measure(
        lambda: rolling_linear_metric(
            frame,
            window,
            "rolling_linreg_slope",
        ).to_numpy(),
        warmups=warmups,
        repeats=repeats,
    )
    _report(
        f"batch slope vs scalar OLS {rows}x{width}, W={window}",
        reference_time,
        optimized_time,
    )

    rows, width, window = 20_000, 16, 255
    values = rng.normal(size=(rows, width))
    values[::97, 0] = np.nan
    values[::131, 1] = np.inf
    frame = pd.DataFrame(values)

    def reference() -> pd.DataFrame:
        return frame.rolling(window, min_periods=window // 2).skew()

    actual = rolling_skew_batch(frame, window)
    np.testing.assert_allclose(
        actual.to_numpy(),
        reference().to_numpy(),
        rtol=2e-7,
        atol=2e-7,
        equal_nan=True,
    )
    reference_time = _measure(reference, warmups=warmups, repeats=repeats)
    optimized_time = _measure(
        lambda: rolling_skew_batch(frame, window),
        warmups=warmups,
        repeats=repeats,
    )
    _report(
        f"batch skew clean-path check {rows}x{width}, W={window}",
        reference_time,
        optimized_time,
    )


if __name__ == "__main__":
    main()
