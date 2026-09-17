"""Scope-partitioned aggregation as a stateful streaming kernel (ADR-022).

Reference implementation for the shared streaming infrastructure is
``ExpandingEwmNode`` (width-vectorised cumulative state, constant memory) —
this node follows the same shape rather than the ``RollingWindowNode`` generic
path, which keeps a ``deque`` of whole per-child arrays and therefore costs
O(K * width) per bar:

* state is O(1) per product (counters, sum, sum of squares, running extremes,
  running arg-extreme, partition key) — the cost does **not** grow with the
  partition length, so a 250-day scope costs the same as a 5-bar one;
* work per bar is O(width);
* a partition boundary resets the state in O(1).

Unsupported combinations raise ``UnsupportedStreamingFactor`` (ADR-022 forbids
silent degradation) instead of falling back to a growing history.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from tools.factors.expr.groupby_scope_eval import GROUPED_AGGREGATIONS
from tools.factors.expr.lookback_scope import BarCountScope, SessionScope, TradingDayScope

def _unsupported(message: str) -> Exception:
    """Resolve the streaming error lazily: ``incremental`` imports this module."""

    from .incremental import UnsupportedStreamingFactor

    return UnsupportedStreamingFactor(message)


# Aggregations that can drop a leading slice by subtracting the dropped prefix.
_SUBTRACTABLE = frozenset({"sum", "mean", "std", "var"})
_INSTANT = frozenset({"mean", "std", "var", "min", "max", "sum", "argmax", "argmin"})


class GroupScopeNode:
    """Cumulative aggregation inside a scope partition, constant state per product."""

    def __init__(
        self,
        op: str,
        scope: Any,
        child: Any,
        width: int,
        *,
        quantile: float | None = None,
        trunc_start: int = 0,
        trunc_end: int | None = None,
    ) -> None:
        if op not in GROUPED_AGGREGATIONS:
            raise _unsupported(f"unsupported groupby_scope op: {op}")
        self.op = op
        self.scope = scope
        self.child = child
        self._width = int(width)
        self.quantile = None if quantile is None else float(quantile)
        self.trunc_start = max(0, int(trunc_start))
        self.trunc_end = None if trunc_end is None else int(trunc_end)
        if self.op in ("median", "quantile"):
            raise _unsupported(
                "groupby_scope median/quantile needs an order-statistic structure; "
                "not available in the streaming kernel"
            )
        if self.trunc_start > 0 and self.op not in _SUBTRACTABLE:
            raise _unsupported(
                f"groupby_scope truncate with a leading offset is only streamable for "
                f"{sorted(_SUBTRACTABLE)}, not {self.op}"
            )
        width = int(width)
        self._partition: object | None = None
        self._position = np.zeros(width, dtype=np.int64)   # ordinal inside partition
        self._count = np.zeros(width, dtype=np.int64)      # counted observations
        self._drop_count = np.zeros(width, dtype=np.int64)  # observations dropped from the head
        self._sum = np.zeros(width, dtype=float)
        self._sum_sq = np.zeros(width, dtype=float)
        self._drop_sum = np.zeros(width, dtype=float)
        self._drop_sum_sq = np.zeros(width, dtype=float)
        self._minimum = np.full(width, np.nan, dtype=float)
        self._maximum = np.full(width, np.nan, dtype=float)
        self._arg_value = np.full(width, np.nan, dtype=float)
        self._arg_position = np.full(width, -1, dtype=np.int64)
        self._last_timestamp: pd.Timestamp | None = None
        self._last = np.full(width, np.nan, dtype=float)

    # ---------------------------------------------------------------- scopes
    def _partition_key(self, market: Any) -> object:
        scope = self.scope
        if isinstance(scope, BarCountScope):
            return "bars"
        timestamp = getattr(market, "timestamp", None)
        if isinstance(scope, TradingDayScope):
            day = getattr(market, "trading_day", None)
            if day is not None:
                return pd.Timestamp(day)
            if timestamp is None:
                raise _unsupported(
                    "trading_day scope needs a market timestamp in the streaming kernel"
                )
            return pd.Timestamp(timestamp).normalize()
        if isinstance(scope, SessionScope):
            if timestamp is None:
                raise _unsupported(
                    "session scope needs a market timestamp in the streaming kernel"
                )
            timestamp = pd.Timestamp(timestamp)
            gap = pd.Timedelta(getattr(scope, "gap", "3h"))
            if self._last_timestamp is None or timestamp - self._last_timestamp >= gap:
                return (getattr(market, "trading_day", None), timestamp)
            return self._partition
        raise _unsupported(f"unsupported groupby_scope scope: {scope!r}")

    def _reset(self) -> None:
        self._position[:] = 0
        self._count[:] = 0
        self._drop_count[:] = 0
        self._sum[:] = 0.0
        self._sum_sq[:] = 0.0
        self._drop_sum[:] = 0.0
        self._drop_sum_sq[:] = 0.0
        self._minimum[:] = np.nan
        self._maximum[:] = np.nan
        self._arg_value[:] = np.nan
        self._arg_position[:] = -1

    def _bars_count(self) -> int:
        """K of ``scope_bars(K)``; the batch kernel passes a ctx, streaming has none."""

        scope = self.scope
        for attribute in ("count", "bars", "k"):
            value = getattr(scope, attribute, None)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return int(value)
        resolver = getattr(scope, "resolved_count", None)
        if resolver is not None:
            try:
                return int(resolver())
            except TypeError:
                return int(resolver(None))
        raise _unsupported("cannot resolve scope_bars(K) in the streaming kernel")

    # ------------------------------------------------------------------ step
    def update(self, market: Any, cache: dict[int, np.ndarray]) -> np.ndarray:
        key = id(self)
        if key in cache:
            return cache[key]
        raw = np.asarray(self.child.update(market, cache), dtype=float)
        if raw.shape != (self._width,):
            raise ValueError("streaming groupby_scope input width changed unexpectedly")

        partition = self._partition_key(market)
        if isinstance(self.scope, BarCountScope):
            count = self._bars_count()
            if count < 1:
                raise _unsupported("scope_bars(K) requires K >= 1")
            boundary = (self._position[0] > 0) and (int(self._position[0]) % count == 0)
            if boundary:
                self._reset()
            partition = self._partition
        elif partition != self._partition:
            self._reset()
        self._partition = partition
        timestamp = getattr(market, "timestamp", None)
        if timestamp is not None:
            self._last_timestamp = pd.Timestamp(timestamp)

        finite = np.isfinite(raw)
        frozen = ~finite & ~np.isnan(self._last)
        # a frozen truncate window stops accepting observations once it is full
        if self.trunc_end is not None:
            full = self._position >= self.trunc_end
            accepting = finite & ~full
        else:
            accepting = finite

        if self.trunc_start > 0:
            dropping = accepting & (self._position < self.trunc_start)
            kept = accepting & ~dropping
            self._drop_sum[dropping] += raw[dropping]
            self._drop_sum_sq[dropping] += raw[dropping] ** 2
            self._drop_count[dropping] += 1
        else:
            kept = accepting
        self._sum[kept] += raw[kept]
        self._sum_sq[kept] += raw[kept] ** 2
        self._count[kept] += 1

        positions = np.where(np.isnan(self._minimum), raw, np.minimum(self._minimum, raw))
        np.copyto(self._minimum, positions, where=kept)
        positions = np.where(np.isnan(self._maximum), raw, np.maximum(self._maximum, raw))
        np.copyto(self._maximum, positions, where=kept)

        if self.op in ("argmax", "argmin"):
            challenger = np.where(
                self.op == "argmax",
                np.nan_to_num(raw, nan=-np.inf) > np.nan_to_num(self._arg_value, nan=-np.inf),
                np.nan_to_num(raw, nan=np.inf) < np.nan_to_num(self._arg_value, nan=np.inf),
            )
            take = kept & (challenger | (self._arg_position < 0))
            self._arg_position[take] = self._position[take]
            self._arg_value[take] = raw[take]

        result = self._value()
        self._position[finite] += 1
        self._last[finite] = raw[finite]
        cache[key] = result
        return result

    def _value(self) -> np.ndarray:
        op = self.op
        count = self._count - self._drop_count
        total = self._sum - self._drop_sum
        total_sq = self._sum_sq - self._drop_sum_sq
        with np.errstate(invalid="ignore", divide="ignore"):
            if op == "sum":
                return np.where(count > 0, total, np.nan)
            if op == "mean":
                return np.where(count > 0, total / np.maximum(count, 1), np.nan)
            if op in ("std", "var"):
                variance = np.where(
                    count > 1,
                    (total_sq - total * total / np.maximum(count, 1)) / np.maximum(count - 1, 1),
                    np.nan,
                )
                variance = np.clip(variance, 0.0, None)
                return np.sqrt(variance) if op == "std" else variance
            if op == "min":
                return np.where(count > 0, self._minimum, np.nan)
            if op == "max":
                return np.where(count > 0, self._maximum, np.nan)
            if op in ("argmax", "argmin"):
                span = np.maximum(self._position - 1, 1)
                normalized = np.where(
                    self._arg_position < 0,
                    np.nan,
                    (self._position - 1 - self._arg_position) / span,
                )
                return normalized
        raise _unsupported(f"unsupported groupby_scope op: {op}")
