"""Bounded sufficient-statistic state for incremental rolling OLS metrics."""

from __future__ import annotations

import numpy as np

from .rolling_regression import ROLLING_LINEAR_METRICS

_REBASE_INTERVAL = 4096


class RollingLinearState:
    """Update one rolling OLS metric in O(products) work per new bar."""

    def __init__(self, window: int, width: int, metric: str) -> None:
        if metric not in ROLLING_LINEAR_METRICS:
            raise ValueError(f"Unknown rolling linear metric: {metric}")
        if window < 1:
            raise ValueError("window must be at least 1")
        if width < 1:
            raise ValueError("width must be at least 1")

        self.window = window
        self.width = width
        self.metric = metric
        self.minimum = max(3, window // 2)
        self._ring = np.full((window, width), np.nan, dtype=float)
        self._cursor = 0
        self._length = 0
        self._steps = 0
        self._anchor = np.zeros(width, dtype=float)
        self._count = np.zeros(width, dtype=np.int64)
        self._sum_x = np.zeros(width, dtype=float)
        self._sum_x2 = np.zeros(width, dtype=float)
        self._sum_y = np.zeros(width, dtype=float)
        self._sum_y2 = np.zeros(width, dtype=float)
        self._sum_xy = np.zeros(width, dtype=float)

    def update(self, values: np.ndarray) -> np.ndarray:
        row = np.asarray(values, dtype=float)
        if row.shape != (self.width,):
            raise ValueError(
                f"rolling regression width changed: expected {self.width}, got {row.shape}"
            )

        finite = np.isfinite(row)

        if self._length == self.window:
            oldest = self._ring[self._cursor]
            oldest_finite = np.isfinite(oldest)
            oldest_y = np.where(
                oldest_finite,
                oldest - self._anchor,
                0.0,
            )
            survivors = self._count - oldest_finite
            previous_sum_x = self._sum_x.copy()
            survivor_sum_y = self._sum_y - oldest_y

            # Every surviving point moves one x-position left when the window advances.
            self._sum_x = previous_sum_x - survivors
            self._sum_x2 += -2.0 * previous_sum_x + survivors
            self._sum_xy -= survivor_sum_y
            self._sum_y = survivor_sum_y
            self._sum_y2 -= oldest_y * oldest_y
            self._count = survivors
            x_new = self.window - 1
        else:
            x_new = self._length

        # Recenter around the latest finite observation. Translating y does not
        # change any OLS metric, and doing this in sufficient-statistic space
        # avoids cancellation when a long-running series drifts far from its
        # initial level without touching every value in the ring buffer.
        new_anchor = np.where(finite, row, self._anchor)
        anchor_delta = new_anchor - self._anchor
        previous_sum_y = self._sum_y
        self._sum_y = previous_sum_y - anchor_delta * self._count
        self._sum_y2 = (
            self._sum_y2
            - 2.0 * anchor_delta * previous_sum_y
            + anchor_delta * anchor_delta * self._count
        )
        self._sum_xy -= anchor_delta * self._sum_x
        self._anchor = new_anchor

        centered = np.where(finite, row - self._anchor, np.nan)
        safe_y = np.where(finite, centered, 0.0)
        self._count += finite
        self._sum_x += finite * x_new
        self._sum_x2 += finite * (x_new * x_new)
        self._sum_y += safe_y
        self._sum_y2 += safe_y * safe_y
        self._sum_xy += safe_y * (finite * x_new)

        self._ring[self._cursor] = row
        self._cursor = (self._cursor + 1) % self.window
        self._length = min(self.window, self._length + 1)
        self._steps += 1
        if self._steps % _REBASE_INTERVAL == 0:
            self._rebase()
        return self._result()

    def _rebase(self) -> None:
        if self._length == self.window:
            values = np.concatenate(
                (self._ring[self._cursor :], self._ring[: self._cursor]),
                axis=0,
            )
        else:
            values = self._ring[: self._length]

        finite = np.isfinite(values)
        anchors = np.zeros(self.width, dtype=float)
        positions_in_window = np.arange(self._length, dtype=np.intp)[:, None]
        latest_valid = np.max(
            np.where(finite, positions_in_window, -1),
            axis=0,
        )
        has_valid = latest_valid >= 0
        anchors[has_valid] = values[
            latest_valid[has_valid],
            np.flatnonzero(has_valid),
        ]
        self._anchor = anchors
        centered = np.where(finite, values - anchors, np.nan)
        safe_y = np.where(finite, centered, 0.0)
        positions = np.arange(self._length, dtype=float)[:, None]
        self._count = finite.sum(axis=0, dtype=np.int64)
        self._sum_x = np.sum(finite * positions, axis=0)
        self._sum_x2 = np.sum(finite * positions * positions, axis=0)
        self._sum_y = np.sum(safe_y, axis=0)
        self._sum_y2 = np.sum(safe_y * safe_y, axis=0)
        self._sum_xy = np.sum(safe_y * positions, axis=0)

    def _result(self) -> np.ndarray:
        result = np.full(self.width, np.nan, dtype=float)
        ready = self._count >= self.minimum
        if not ready.any():
            return result

        count = np.maximum(self._count, 1).astype(float)
        centered_xx = self._sum_x2 - self._sum_x * self._sum_x / count
        centered_yy = self._sum_y2 - self._sum_y * self._sum_y / count
        centered_xy = self._sum_xy - self._sum_x * self._sum_y / count
        eligible = ready & (centered_xx > 0.0)
        if not eligible.any():
            return result

        slope = np.divide(
            centered_xy,
            centered_xx,
            out=np.full(self.width, np.nan, dtype=float),
            where=centered_xx > 0.0,
        )
        if self.metric == "rolling_linreg_slope":
            result[eligible] = slope[eligible]
            return result

        sum_squares = np.maximum(0.0, centered_yy - slope * centered_xy)
        if self.metric == "rolling_linreg_r2":
            valid = eligible & (centered_yy > 0.0)
            result[valid] = 1.0 - sum_squares[valid] / centered_yy[valid]
            return result

        residual_variance = np.divide(
            sum_squares,
            count - 2.0,
            out=np.full(self.width, np.nan, dtype=float),
            where=count > 2.0,
        )
        if self.metric == "rolling_linreg_resid_std":
            result[eligible] = np.sqrt(residual_variance[eligible])
            return result

        standard_error = np.sqrt(residual_variance / centered_xx)
        valid = eligible & np.isfinite(standard_error) & (standard_error > 0.0)
        result[valid] = slope[valid] / standard_error[valid]
        return result
