"""Benchmark fixed-window live kernels against the previous rescan path."""

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

from tools.testers.backtest.engines.factors.incremental import RollingWindowNode


class _Rows:
    def __init__(self, values: np.ndarray) -> None:
        self.values = values
        self.position = 0

    def update(self, _market, _cache: dict[int, np.ndarray]) -> np.ndarray:
        value = self.values[self.position]
        self.position += 1
        return value


def _legacy(operation: str, inputs: tuple[np.ndarray, ...], window: int) -> np.ndarray:
    width = inputs[0].shape[1]
    histories = [deque(maxlen=window) for _ in inputs]
    output = np.full((len(inputs[0]), width), np.nan, dtype=float)
    for index in range(len(output)):
        for history, values in zip(histories, inputs, strict=True):
            history.append(values[index].copy())
        values = np.asarray(histories[0], dtype=float)
        finite = np.isfinite(values)
        count = finite.sum(axis=0)
        result = output[index]
        if operation in {"rolling_std", "rolling_var"}:
            mean = np.divide(
                np.where(finite, values, 0.0).sum(axis=0), count,
                out=np.zeros(width), where=count > 0,
            )
            centered = np.where(finite, values - mean, 0.0)
            variance = np.sum(centered * centered, axis=0) / np.maximum(count - 1, 1)
            ready = (count >= max(1, window // 2)) & (count > 1)
            result[ready] = np.sqrt(variance[ready]) if operation == "rolling_std" else variance[ready]
        elif operation == "rolling_skew":
            mean = np.divide(
                np.where(finite, values, 0.0).sum(axis=0), count,
                out=np.zeros(width), where=count > 0,
            )
            centered = np.where(finite, values - mean, 0.0)
            second = np.sum(centered * centered, axis=0) / np.maximum(count, 1)
            third = np.sum(centered * centered * centered, axis=0) / np.maximum(count, 1)
            valid = (count >= max(1, window // 2)) & (count >= 3) & (second > 0.0)
            with np.errstate(divide="ignore", invalid="ignore"):
                skew = third / np.power(second, 1.5)
            corrected = np.sqrt(count * np.maximum(count - 1, 0)) / np.maximum(count - 2, 1)
            result[valid] = corrected[valid] * skew[valid]
        elif operation in {"rolling_min", "rolling_max"}:
            safe = np.where(finite, values, np.inf if operation == "rolling_min" else -np.inf)
            reduced = np.min(safe, axis=0) if operation == "rolling_min" else np.max(safe, axis=0)
            result[count > 0] = reduced[count > 0]
        elif operation in {"rolling_argmax", "rolling_argmin", "rolling_argmax_raw", "rolling_argmin_raw"}:
            if window > 1 and len(values) < window:
                continue
            for column in range(width):
                sample = values[:, column]
                if np.isnan(sample).all():
                    result[column] = 0.0
                    continue
                extreme = np.nanmax(sample) if "argmax" in operation else np.nanmin(sample)
                position = np.flatnonzero(sample == extreme)[-1]
                result[column] = (
                    position / max(1, window - 1)
                    if not operation.endswith("_raw") else position
                )
        elif operation in {"rolling_cov", "rolling_corr"}:
            right = np.asarray(histories[1], dtype=float)
            if len(values) < window:
                continue
            pair_finite = np.isfinite(values) & np.isfinite(right)
            ready = pair_finite.sum(axis=0) == window
            if not ready.any():
                continue
            left_centered = values - np.mean(values, axis=0)
            right_centered = right - np.mean(right, axis=0)
            co_moment = np.sum(left_centered * right_centered, axis=0)
            if operation == "rolling_cov":
                result[ready] = co_moment[ready] / (window - 1)
            else:
                left_m2 = np.sum(left_centered * left_centered, axis=0)
                right_m2 = np.sum(right_centered * right_centered, axis=0)
                denominator = np.sqrt(left_m2 * right_m2)
                valid = ready & (denominator > 0.0)
                result[valid] = co_moment[valid] / denominator[valid]
        else:
            raise ValueError(f"unsupported operation: {operation}")
    return output


def _optimized(
    operation: str,
    inputs: tuple[np.ndarray, ...],
    window: int,
) -> np.ndarray:
    node = RollingWindowNode(
        operation,
        tuple(_Rows(values) for values in inputs),
        window,
        inputs[0].shape[1],
    )
    return np.asarray([node.update(None, {}) for _ in range(len(inputs[0]))])


def _measure(function: Callable[[], np.ndarray], repeats: int) -> float:
    function()
    elapsed = []
    for _ in range(repeats):
        started = time.perf_counter()
        function()
        elapsed.append(time.perf_counter() - started)
    return statistics.median(elapsed)


def main() -> None:
    rng = np.random.default_rng(423)
    rows, width = 6_000, 16
    left = 10_000.0 + rng.normal(scale=3.0, size=(rows, width))
    right = 5_000.0 + 0.8 * (left - 10_000.0) + rng.normal(scale=2.0, size=left.shape)
    left[::101, 0] = np.nan
    right[::137, 1] = np.nan
    print(
        f"Python {platform.python_version()} | NumPy {np.__version__} | "
        f"CPU {platform.processor() or 'unknown'}"
    )
    print(f"shape={rows}x{width}, warmups=1, repeats=3; median elapsed time")

    for window in (63, 127, 128, 255):
        for operation in (
            "rolling_std", "rolling_var", "rolling_skew", "rolling_min", "rolling_max",
            "rolling_argmax", "rolling_cov", "rolling_corr",
        ):
            inputs = (left, right) if operation in {"rolling_cov", "rolling_corr"} else (left,)
            expected = _legacy(operation, inputs, window)
            actual = _optimized(operation, inputs, window)
            np.testing.assert_allclose(actual, expected, rtol=3e-6, atol=2e-8, equal_nan=True)
            old_time = _measure(
                lambda operation=operation, inputs=inputs, window=window: _legacy(
                    operation, inputs, window,
                ),
                repeats=3,
            )
            new_time = _measure(
                lambda operation=operation, inputs=inputs, window=window: _optimized(
                    operation, inputs, window,
                ),
                repeats=3,
            )
            print(
                f"{operation:<14s} W={window:<3d} reference={old_time:7.4f}s "
                f"current={new_time:7.4f}s ratio={old_time / new_time:5.2f}x"
            )


if __name__ == "__main__":
    main()
