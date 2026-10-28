"""Incremental rolling extrema kernels."""

from __future__ import annotations

from collections import deque

import numpy as np


class RollingMinMaxState:
    """Use vectorized scans for short windows and monotonic queues for long ones."""

    def __init__(self, op: str, window: int, width: int) -> None:
        self.op = op
        self.window = window
        self.width = width
        self._is_min = op == "rolling_min"
        # Benchmarks show the deque wins consistently once the ring scan is
        # very large; retain NumPy's vectorized reduction for smaller windows.
        self._use_deques = window >= 4096 and window >= 32 * max(width, 1)
        self._index = -1
        self._queues = [deque[tuple[int, float]]() for _ in range(width)] if self._use_deques else []
        if not self._use_deques:
            sentinel = np.inf if self._is_min else -np.inf
            self._ring = np.full((window, width), sentinel, dtype=float)
            self._cursor = 0
            self._length = 0
            self._count = np.zeros(width, dtype=np.int64)

    def update(self, value: np.ndarray) -> np.ndarray:
        value = np.asarray(value, dtype=float)
        if value.shape != (self.width,):
            raise ValueError("streaming rolling input width changed unexpectedly")
        if self._use_deques:
            return self._update_deques(value)

        if self._length == self.window:
            outgoing = self._ring[self._cursor]
            # Sentinels represent missing values; finite input values alone
            # contribute to the counter, matching pandas rolling min/max.
            self._count -= np.isfinite(outgoing)
        finite = np.isfinite(value)
        sentinel = np.inf if self._is_min else -np.inf
        self._ring[self._cursor] = np.where(finite, value, sentinel)
        self._count += finite
        self._cursor = (self._cursor + 1) % self.window
        self._length = min(self.window, self._length + 1)

        result = np.full(self.width, np.nan, dtype=float)
        ready = self._count > 0
        if self._is_min:
            result[ready] = np.min(self._ring, axis=0)[ready]
        else:
            result[ready] = np.max(self._ring, axis=0)[ready]
        return result

    def _update_deques(self, value: np.ndarray) -> np.ndarray:
        self._index += 1
        oldest = self._index - self.window
        result = np.full(self.width, np.nan, dtype=float)
        for column, current in enumerate(value):
            queue = self._queues[column]
            while queue and queue[0][0] <= oldest:
                queue.popleft()
            if np.isfinite(current):
                if self._is_min:
                    while queue and queue[-1][1] >= current:
                        queue.pop()
                else:
                    while queue and queue[-1][1] <= current:
                        queue.pop()
                queue.append((self._index, float(current)))
            if queue:
                result[column] = queue[0][1]
        return result


class RollingArgExtremaState:
    """Per-product monotonic queues; each observation enters and exits once."""

    def __init__(self, op: str, window: int, width: int) -> None:
        self.op = op
        self.window = window
        self.width = width
        self._is_max = "argmax" in op
        self._normalize = not op.endswith("_raw")
        self._index = -1
        self._queues: list[deque[tuple[int, float]]] = [deque() for _ in range(width)]

    def update(self, value: np.ndarray) -> np.ndarray:
        value = np.asarray(value, dtype=float)
        if value.shape != (self.width,):
            raise ValueError("streaming rolling input width changed unexpectedly")
        self._index += 1
        for column, current in enumerate(value):
            queue = self._queues[column]
            oldest = self._index - self.window
            while queue and queue[0][0] <= oldest:
                queue.popleft()
            # The batch operator excludes NaN but intentionally preserves +/-Inf.
            if np.isnan(current):
                continue
            if self._is_max:
                while queue and queue[-1][1] <= current:
                    queue.pop()
            else:
                while queue and queue[-1][1] >= current:
                    queue.pop()
            queue.append((self._index, float(current)))

        if self.window == 1:
            return np.where(np.isnan(value), np.nan, 0.0)
        if self._index + 1 < self.window:
            return np.full(self.width, np.nan, dtype=float)

        result = np.zeros(self.width, dtype=float)
        for column, queue in enumerate(self._queues):
            if queue:
                age = self._index - queue[0][0]
                position = self.window - 1 - age
                result[column] = position / (self.window - 1) if self._normalize else position
        return result
