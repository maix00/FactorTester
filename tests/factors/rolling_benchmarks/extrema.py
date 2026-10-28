"""Benchmarks for long-window extrema and bounded batch arg-extrema memory."""

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

import tools.factors.expr.rolling_arg_extrema as rolling_module
from tests.factors._scope_extrema_oracle import _prefix_arg_extreme_loop
from tools.factors.expr.streaming.rolling_extrema import RollingMinMaxState


def _measure(function: Callable[[], np.ndarray], repeats: int = 3) -> float:
    timings = []
    for _ in range(repeats):
        started = time.perf_counter()
        function()
        timings.append(time.perf_counter() - started)
    return statistics.median(timings)


def _scan_minmax(rows: np.ndarray, operation: str, window: int) -> np.ndarray:
    width = rows.shape[1]
    is_min = operation == "rolling_min"
    sentinel = np.inf if is_min else -np.inf
    ring = np.full((window, width), sentinel)
    count = np.zeros(width, dtype=np.int64)
    output = np.full(rows.shape, np.nan)
    cursor = 0
    length = 0
    for row_index, row in enumerate(rows):
        if length == window:
            count -= np.isfinite(ring[cursor])
        finite = np.isfinite(row)
        ring[cursor] = np.where(finite, row, sentinel)
        count += finite
        cursor = (cursor + 1) % window
        length = min(window, length + 1)
        reduced = np.min(ring, axis=0) if is_min else np.max(ring, axis=0)
        ready = count > 0
        output[row_index, ready] = reduced[ready]
    return output


def _deque_minmax(rows: np.ndarray, operation: str, window: int) -> np.ndarray:
    state = RollingMinMaxState(operation, window, rows.shape[1])
    return np.asarray([state.update(row) for row in rows])


def _benchmark_long_minmax(rng: np.random.Generator) -> None:
    rows, width, window = 2_500, 32, 4_096
    values = rng.normal(size=(rows, width))
    values[::97, 0] = np.nan
    values[::131, 1] = np.inf
    print(f"long live extrema shape={rows}x{width}, W={window}")
    for operation in ("rolling_min", "rolling_max"):
        scan = _scan_minmax(values, operation, window)
        queued = _deque_minmax(values, operation, window)
        np.testing.assert_allclose(queued, scan, equal_nan=True)
        scan_time = _measure(
            lambda operation=operation: _scan_minmax(values, operation, window),
        )
        queue_time = _measure(
            lambda operation=operation: _deque_minmax(values, operation, window),
        )
        print(
            f"{operation:<14s} vectorized scan={scan_time:7.4f}s "
            f"monotonic queue={queue_time:7.4f}s speedup={scan_time / queue_time:5.2f}x"
        )


def _benchmark_bounded_arg_extrema(rng: np.random.Generator) -> None:
    rows, width, window = 12_000, 8, 255
    values = rng.normal(size=(rows, width))
    values[::113, 0] = np.nan
    values[::157, 1] = np.inf
    frame = pd.DataFrame(values)
    previous_budget = rolling_module._ARG_EXTREMA_TEMP_BUDGET_BYTES
    expected = None
    print(f"batch argmax shape={rows}x{width}, W={window}; temporary budget sweep")
    try:
        for budget_mib in (2, 8, 32):
            rolling_module._ARG_EXTREMA_TEMP_BUDGET_BYTES = budget_mib * 1024 * 1024

            def run() -> np.ndarray:
                return rolling_module.rolling_argmaxmin(
                    frame,
                    window,
                    "rolling_argmax",
                ).to_numpy()

            result = run()
            if expected is None:
                expected = result
            else:
                np.testing.assert_allclose(result, expected, equal_nan=True)
            elapsed = _measure(run)
            print(f"budget={budget_mib:2d} MiB elapsed={elapsed:7.4f}s")
    finally:
        rolling_module._ARG_EXTREMA_TEMP_BUDGET_BYTES = previous_budget


def _legacy_truncated_arg_extreme(
    values: np.ndarray,
    operation: str,
    start: int,
    end: int,
) -> np.ndarray:
    output = np.full(len(values), np.nan)
    best_index = -1
    for position in range(start, len(values)):
        limit = min(position, end)
        if position == start:
            best_index = start
        elif limit > best_index:
            candidates = values[best_index + 1:limit + 1]
            valid = np.flatnonzero(~np.isnan(candidates))
            if valid.size:
                observed = candidates[valid]
                offset = np.argmax(observed) if operation == "argmax" else np.argmin(observed)
                challenger = best_index + 1 + int(valid[offset])
                current = values[best_index]
                candidate = values[challenger]
                if np.isnan(current) or (
                    candidate > current if operation == "argmax" else candidate < current
                ):
                    best_index = challenger
        if not np.isnan(values[position]):
            span = position - start
            output[position] = 0.0 if span == 0 else (position - best_index) / span
    return output


def _benchmark_truncated_arg_extreme_tail(rng: np.random.Generator) -> None:
    source = rng.normal(size=100_000)
    start, end = 2, 7
    print(
        f"groupby arg-extreme truncated tail rows={len(source)}, "
        f"active span={end - start + 1}"
    )
    for operation in ("argmax", "argmin"):
        values = source.copy()
        values[start] = np.nan
        values[start + 1] = 100.0 if operation == "argmax" else -100.0
        values[start + 2:end + 1] = 0.0
        def reference(operation=operation, values=values):
            return _legacy_truncated_arg_extreme(values, operation, start, end)

        def optimized(operation=operation, values=values):
            return _prefix_arg_extreme_loop(values, operation, start, end)

        np.testing.assert_allclose(optimized(), reference(), equal_nan=True)
        old_time = _measure(reference)
        new_time = _measure(optimized)
        print(
            f"{operation:<14s} repeated scan={old_time:7.4f}s "
            f"single pass={new_time:7.4f}s speedup={old_time / new_time:5.2f}x"
        )


def main() -> None:
    print(
        f"Python {platform.python_version()} | NumPy {np.__version__} | "
        f"pandas {pd.__version__} | CPU {platform.processor() or 'unknown'}"
    )
    rng = np.random.default_rng(423_14)
    _benchmark_long_minmax(rng)
    _benchmark_bounded_arg_extrema(rng)
    _benchmark_truncated_arg_extreme_tail(rng)


if __name__ == "__main__":
    main()
