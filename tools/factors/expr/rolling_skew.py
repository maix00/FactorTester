"""Stable rolling-skew state and batch fallback for missing-value runs."""

from __future__ import annotations

import numpy as np
import pandas as pd


class RollingSkewState:
    """O(products) add/remove updates with periodic fixed-window rebasing."""

    def __init__(self, window: int, width: int) -> None:
        self.window = window
        self.width = width
        self.minimum = max(1, window // 2)
        self._ring = np.full((window, width), np.nan, dtype=float)
        self._cursor = 0
        self._length = 0
        self._updates = 0
        self._count = np.zeros(width, dtype=np.int64)
        self._origin = np.zeros(width, dtype=float)
        self._mean = np.zeros(width, dtype=float)
        self._m2 = np.zeros(width, dtype=float)
        self._m3 = np.zeros(width, dtype=float)
        self._roundoff_scale = np.zeros(width, dtype=float)

    def update(self, value: np.ndarray) -> np.ndarray:
        value = np.asarray(value, dtype=float)
        if value.shape != (self.width,):
            raise ValueError("rolling skew input width changed unexpectedly")

        self._roundoff_scale.fill(0.0)
        if self._length == self.window:
            self._remove(self._ring[self._cursor])
        self._ring[self._cursor] = value
        self._add(value)
        self._cursor = (self._cursor + 1) % self.window
        self._length = min(self.window, self._length + 1)
        self._updates += 1

        tolerance = 32.0 * np.finfo(float).eps * self._roundoff_scale
        if np.any((self._m2 > 0.0) & (self._m2 <= tolerance)):
            self._rebase()
        if self._updates % 2048 == 0:
            self._rebase()

        count = self._count
        ready = (count >= self.minimum) & (count >= 3) & (self._m2 > 0.0)
        result = np.full(self.width, np.nan, dtype=float)
        second = self._m2 / np.maximum(count, 1)
        third = self._m3 / np.maximum(count, 1)
        with np.errstate(divide="ignore", invalid="ignore"):
            skew = third / np.power(second, 1.5)
        corrected = np.sqrt(count * np.maximum(count - 1, 0)) / np.maximum(count - 2, 1)
        result[ready] = corrected[ready] * skew[ready]
        return result

    def _remove(self, value: np.ndarray) -> None:
        valid = np.isfinite(value) & (self._count > 0)
        shifted = value - self._origin
        remaining = self._count - 1
        singleton = valid & (remaining == 0)
        self._mean[singleton] = 0.0
        self._m2[singleton] = 0.0
        self._m3[singleton] = 0.0
        self._count[singleton] = 0

        multiple = valid & (remaining > 0)
        if not multiple.any():
            return
        old_mean = self._mean[multiple].copy()
        delta = shifted[multiple] - old_mean
        next_mean = old_mean - delta / remaining[multiple]
        removed_m2 = delta * (shifted[multiple] - next_mean)
        removed_m3 = (
            delta**3
            * (remaining[multiple] + 1)
            * (remaining[multiple] + 2)
            / remaining[multiple] ** 2
            - 3.0 * delta * self._m2[multiple] / remaining[multiple]
        )
        self._m2[multiple] -= removed_m2
        self._m3[multiple] -= removed_m3
        self._roundoff_scale[multiple] += np.abs(removed_m2)
        self._mean[multiple] = next_mean
        self._count[multiple] = remaining[multiple]

    def _add(self, value: np.ndarray) -> None:
        valid = np.isfinite(value)
        if not valid.any():
            return
        empty = valid & (self._count == 0)
        self._origin[empty] = value[empty]
        shifted = value - self._origin
        old_count = self._count[valid]
        count = old_count + 1
        delta = shifted[valid] - self._mean[valid]
        delta_n = delta / count
        term = delta * delta_n * old_count
        self._m3[valid] += term * delta_n * (old_count - 1) - 3.0 * delta_n * self._m2[valid]
        self._m2[valid] += term
        self._roundoff_scale[valid] += np.abs(term)
        self._mean[valid] += delta_n
        self._count[valid] = count

    def _rebase(self) -> None:
        finite = np.isfinite(self._ring)
        count = finite.sum(axis=0)
        first = np.argmax(finite, axis=0)
        anchor = self._ring[first, np.arange(self.width)]
        anchor = np.where(count > 0, anchor, 0.0)
        delta = np.where(finite, self._ring - anchor, 0.0)
        mean = delta.sum(axis=0) / np.maximum(count, 1)
        centered = np.where(finite, delta - mean, 0.0)
        self._count = count
        self._origin = anchor
        self._mean = mean
        self._m2 = np.sum(centered * centered, axis=0)
        self._m3 = np.sum(centered * centered * centered, axis=0)


def rolling_skew_batch(data: pd.DataFrame, window: int) -> pd.DataFrame:
    """Use pandas' C kernel unless adjacent missing values poison its state."""
    minimum = max(1, window // 2)
    result = data.rolling(window, min_periods=minimum).skew()
    values = data.to_numpy(dtype=float, copy=False)
    missing = ~np.isfinite(values)
    affected = np.flatnonzero(np.any(missing[1:] & missing[:-1], axis=0))
    if affected.size == 0:
        return result

    state = RollingSkewState(window, int(affected.size))
    repaired = np.empty((len(data), affected.size), dtype=float)
    for row, value in enumerate(values[:, affected]):
        repaired[row] = state.update(value)
    output = result.to_numpy(dtype=float, copy=True)
    output[:, affected] = repaired
    return pd.DataFrame(output, index=data.index, columns=data.columns)
