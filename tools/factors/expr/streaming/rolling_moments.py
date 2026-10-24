"""Incremental rolling variance state."""

from __future__ import annotations

import numpy as np


class RollingMomentsState:
    """Per-product Welford state with O(products) updates and a fixed ring."""

    def __init__(self, window: int, width: int, *, standard_deviation: bool) -> None:
        self.window = window
        self.width = width
        self.standard_deviation = standard_deviation
        self.minimum = max(1, window // 2)
        self._ring = np.full((window, width), np.nan, dtype=float)
        self._cursor = 0
        self._length = 0
        self._updates = 0
        self._count = np.zeros(width, dtype=np.int64)
        self._origin = np.zeros(width, dtype=float)
        self._mean = np.zeros(width, dtype=float)
        self._m2 = np.zeros(width, dtype=float)
        self._roundoff_scale = np.zeros(width, dtype=float)

    def update(self, value: np.ndarray) -> np.ndarray:
        value = np.asarray(value, dtype=float)
        if value.shape != (self.width,):
            raise ValueError("streaming rolling input width changed unexpectedly")

        self._roundoff_scale.fill(0.0)
        if self._length == self.window:
            self._remove(self._ring[self._cursor])
        self._ring[self._cursor] = value
        self._add(value)
        self._cursor = (self._cursor + 1) % self.window
        self._length = min(self.window, self._length + 1)
        self._updates += 1

        tolerance = 32.0 * np.finfo(float).eps * self._roundoff_scale
        near_zero = (self._m2 > 0.0) & (self._m2 <= tolerance)
        if np.any(near_zero) or self._updates % 2048 == 0:
            self._rebase()

        ready = (self._count >= self.minimum) & (self._count > 1)
        result = np.full(self.width, np.nan, dtype=float)
        variance = np.maximum(self._m2, 0.0) / np.maximum(self._count - 1, 1)
        result[ready] = np.sqrt(variance[ready]) if self.standard_deviation else variance[ready]
        return result

    def _remove(self, value: np.ndarray) -> None:
        valid = np.isfinite(value) & (self._count > 0)
        shifted = value - self._origin
        remaining = self._count - 1
        singleton = valid & (remaining == 0)
        self._mean[singleton] = 0.0
        self._m2[singleton] = 0.0
        self._count[singleton] = 0

        multiple = valid & (remaining > 0)
        if not multiple.any():
            return
        old_mean = self._mean[multiple].copy()
        next_mean = old_mean + (old_mean - shifted[multiple]) / remaining[multiple]
        removed = (shifted[multiple] - old_mean) * (shifted[multiple] - next_mean)
        self._m2[multiple] -= removed
        self._roundoff_scale[multiple] += np.abs(removed)
        self._mean[multiple] = next_mean
        self._count[multiple] = remaining[multiple]

    def _add(self, value: np.ndarray) -> None:
        valid = np.isfinite(value)
        if not valid.any():
            return
        empty = valid & (self._count == 0)
        self._origin[empty] = value[empty]
        shifted = value - self._origin
        count = self._count[valid] + 1
        delta = shifted[valid] - self._mean[valid]
        next_mean = self._mean[valid] + delta / count
        added = delta * (shifted[valid] - next_mean)
        self._m2[valid] += added
        self._roundoff_scale[valid] += np.abs(added)
        self._mean[valid] = next_mean
        self._count[valid] = count

    def _rebase(self) -> None:
        finite = np.isfinite(self._ring)
        count = finite.sum(axis=0)
        first = np.argmax(finite, axis=0)
        anchor = self._ring[first, np.arange(self.width)]
        anchor = np.where(count > 0, anchor, 0.0)
        delta = np.where(finite, self._ring - anchor, 0.0)
        mean_delta = delta.sum(axis=0) / np.maximum(count, 1)
        centered = np.where(finite, delta - mean_delta, 0.0)
        self._count = count
        self._origin = anchor
        self._mean = mean_delta
        self._m2 = np.sum(centered * centered, axis=0)
