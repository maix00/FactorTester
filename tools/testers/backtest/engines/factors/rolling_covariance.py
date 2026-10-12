"""Incremental rolling covariance and correlation state."""

from __future__ import annotations

import numpy as np


class RollingCovarianceState:
    """Pairwise finite rolling covariance/correlation with O(products) updates."""

    def __init__(self, window: int, width: int, *, correlation: bool) -> None:
        self.window = window
        self.width = width
        self.correlation = correlation
        self._ring_x = np.full((window, width), np.nan, dtype=float)
        self._ring_y = np.full((window, width), np.nan, dtype=float)
        self._cursor = 0
        self._length = 0
        self._updates = 0
        self._count = np.zeros(width, dtype=np.int64)
        self._origin_x = np.zeros(width, dtype=float)
        self._origin_y = np.zeros(width, dtype=float)
        self._mean_x = np.zeros(width, dtype=float)
        self._mean_y = np.zeros(width, dtype=float)
        self._m2_x = np.zeros(width, dtype=float)
        self._m2_y = np.zeros(width, dtype=float)
        self._co_moment = np.zeros(width, dtype=float)
        self._roundoff_x = np.zeros(width, dtype=float)
        self._roundoff_y = np.zeros(width, dtype=float)

    def update(self, left: np.ndarray, right: np.ndarray) -> np.ndarray:
        left = np.asarray(left, dtype=float)
        right = np.asarray(right, dtype=float)
        if left.shape != (self.width,) or right.shape != (self.width,):
            raise ValueError("streaming rolling input width changed unexpectedly")

        self._roundoff_x.fill(0.0)
        self._roundoff_y.fill(0.0)
        if self._length == self.window:
            self._remove(self._ring_x[self._cursor], self._ring_y[self._cursor])
        self._ring_x[self._cursor] = left
        self._ring_y[self._cursor] = right
        self._add(left, right)
        self._cursor = (self._cursor + 1) % self.window
        self._length = min(self.window, self._length + 1)
        self._updates += 1
        epsilon = 32.0 * np.finfo(float).eps
        needs_rebase = (
            ((self._m2_x > 0.0) & (self._m2_x <= epsilon * self._roundoff_x))
            | ((self._m2_y > 0.0) & (self._m2_y <= epsilon * self._roundoff_y))
        )
        if np.any(needs_rebase) or self._updates % 2048 == 0:
            self._rebase()

        if self._length < self.window:
            return np.full(self.width, np.nan, dtype=float)
        ready = self._count == self.window
        result = np.full(self.width, np.nan, dtype=float)
        if self.correlation:
            denominator = np.sqrt(np.maximum(self._m2_x, 0.0) * np.maximum(self._m2_y, 0.0))
            valid = ready & (denominator > 0.0)
            result[valid] = self._co_moment[valid] / denominator[valid]
        elif self.window > 1:
            result[ready] = self._co_moment[ready] / (self.window - 1)
        return result

    def _remove(self, left: np.ndarray, right: np.ndarray) -> None:
        valid = np.isfinite(left) & np.isfinite(right) & (self._count > 0)
        shifted_x = left - self._origin_x
        shifted_y = right - self._origin_y
        remaining = self._count - 1
        singleton = valid & (remaining == 0)
        for state in (self._mean_x, self._mean_y, self._m2_x, self._m2_y, self._co_moment):
            state[singleton] = 0.0
        self._count[singleton] = 0

        multiple = valid & (remaining > 0)
        if not multiple.any():
            return
        old_x = self._mean_x[multiple].copy()
        old_y = self._mean_y[multiple].copy()
        next_x = old_x + (old_x - shifted_x[multiple]) / remaining[multiple]
        next_y = old_y + (old_y - shifted_y[multiple]) / remaining[multiple]
        removed_x = (shifted_x[multiple] - old_x) * (shifted_x[multiple] - next_x)
        removed_y = (shifted_y[multiple] - old_y) * (shifted_y[multiple] - next_y)
        self._m2_x[multiple] -= removed_x
        self._m2_y[multiple] -= removed_y
        self._roundoff_x[multiple] += np.abs(removed_x)
        self._roundoff_y[multiple] += np.abs(removed_y)
        self._co_moment[multiple] -= (
            (shifted_x[multiple] - old_x) * (shifted_y[multiple] - next_y)
        )
        self._mean_x[multiple] = next_x
        self._mean_y[multiple] = next_y
        self._count[multiple] = remaining[multiple]

    def _add(self, left: np.ndarray, right: np.ndarray) -> None:
        valid = np.isfinite(left) & np.isfinite(right)
        if not valid.any():
            return
        empty = valid & (self._count == 0)
        self._origin_x[empty] = left[empty]
        self._origin_y[empty] = right[empty]
        shifted_x = left - self._origin_x
        shifted_y = right - self._origin_y
        count = self._count[valid] + 1
        delta_x = shifted_x[valid] - self._mean_x[valid]
        delta_y = shifted_y[valid] - self._mean_y[valid]
        next_x = self._mean_x[valid] + delta_x / count
        next_y = self._mean_y[valid] + delta_y / count
        added_x = delta_x * (shifted_x[valid] - next_x)
        added_y = delta_y * (shifted_y[valid] - next_y)
        self._m2_x[valid] += added_x
        self._m2_y[valid] += added_y
        self._roundoff_x[valid] += np.abs(added_x)
        self._roundoff_y[valid] += np.abs(added_y)
        self._co_moment[valid] += delta_x * (shifted_y[valid] - next_y)
        self._mean_x[valid] = next_x
        self._mean_y[valid] = next_y
        self._count[valid] = count

    def _rebase(self) -> None:
        finite = np.isfinite(self._ring_x) & np.isfinite(self._ring_y)
        count = finite.sum(axis=0)
        first = np.argmax(finite, axis=0)
        columns = np.arange(self.width)
        anchor_x = np.where(count > 0, self._ring_x[first, columns], 0.0)
        anchor_y = np.where(count > 0, self._ring_y[first, columns], 0.0)
        delta_x = np.where(finite, self._ring_x - anchor_x, 0.0)
        delta_y = np.where(finite, self._ring_y - anchor_y, 0.0)
        mean_x = delta_x.sum(axis=0) / np.maximum(count, 1)
        mean_y = delta_y.sum(axis=0) / np.maximum(count, 1)
        centered_x = np.where(finite, delta_x - mean_x, 0.0)
        centered_y = np.where(finite, delta_y - mean_y, 0.0)
        self._count = count
        self._origin_x = anchor_x
        self._origin_y = anchor_y
        self._mean_x = mean_x
        self._mean_y = mean_y
        self._m2_x = np.sum(centered_x * centered_x, axis=0)
        self._m2_y = np.sum(centered_y * centered_y, axis=0)
        self._co_moment = np.sum(centered_x * centered_y, axis=0)
