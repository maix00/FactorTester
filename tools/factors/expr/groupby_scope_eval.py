"""Batch kernels for scope-partitioned aggregation (groupby_scope).

Unlike ``rolling``, which slides a **fixed-length** window over the series, these
kernels partition the series by a lookback scope (trading day / session / every
K bars) and aggregate **within a partition**, using only the observations of the
current partition up to and including the current bar.  This is what makes
"当日午前均值" or "当日 argmax" expressible: ``rolling('1d')`` resolves to a fixed
bar count, so a mid-afternoon bar would otherwise reach into the previous
trading day.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from tools.data.types import finest_index

from .bar_search_eval import _observed_mask
from .lookback_scope import BarCountScope, LookbackScope, SessionScope, TradingDayScope

# 少于该长度时逐根循环更快（numpy 每次调用的固定开销超过扫描本身）
_ARG_EXTREME_VECTOR_FLOOR = 32

GROUPED_AGGREGATIONS = frozenset({
    "mean", "std", "var", "min", "max", "sum", "median", "quantile",
    "argmax", "argmin",
})

_MIN_PERIODS = {
    "mean": 1, "sum": 1, "min": 1, "max": 1,
    "std": 2, "var": 2, "median": 1, "quantile": 1,
}


def partition_keys(
    index: pd.Index,
    observed_rows: np.ndarray,
    scope: LookbackScope,
    ctx: Any,
) -> np.ndarray:
    """Return one partition key per observed row, in observed order.

    ``scope_bars(K)`` groups every K **observed** bars together (non-overlapping,
    unlike a sliding window); ``scope_trading_day()`` and ``scope_session(gap)``
    reuse the same partition logic the bar-search kernels already rely on.
    """
    if isinstance(scope, BarCountScope):
        count = int(scope.resolved_count(ctx=ctx))
        if count < 1:
            raise ValueError("scope_bars(K) requires K >= 1")
        return np.arange(len(observed_rows), dtype=np.int64) // count
    if isinstance(scope, TradingDayScope):
        if ctx.panel_timeline is None:
            raise ValueError("trading_day scope requires panel_timeline")
        days = np.asarray(ctx.panel_timeline.trading_days)[observed_rows]
        return pd.factorize(days, sort=False)[0]
    if isinstance(scope, SessionScope):
        event_index = finest_index(index) if isinstance(index, pd.MultiIndex) else index
        timestamps = pd.DatetimeIndex(event_index[observed_rows])
        if len(timestamps) == 0:
            return np.empty(0, dtype=np.int64)
        starts = np.r_[
            True,
            np.asarray(timestamps[1:] - timestamps[:-1]) >= pd.Timedelta(scope.gap),
        ]
        return np.cumsum(starts, dtype=np.int64) - 1
    raise TypeError(f"unsupported groupby_scope scope: {scope!r}")


def _group_bounds(keys: np.ndarray) -> list[tuple[int, int]]:
    """Contiguous [start, stop) runs of equal partition keys."""
    if len(keys) == 0:
        return []
    boundaries = np.flatnonzero(keys[1:] != keys[:-1]) + 1
    edges = np.r_[0, boundaries, len(keys)]
    return [(int(edges[i]), int(edges[i + 1])) for i in range(len(edges) - 1)]


def _prefix_aggregate(
    values: np.ndarray, op: str, quantile: float | None,
    start: int, end: int,
) -> np.ndarray:
    """Aggregate the partition's [start, end] members for every prefix position.

    ``start``/``end`` are positions **inside the partition** (``end=None`` means
    "up to the current bar").  Results before ``start`` are NaN.
    """
    length = len(values)
    output = np.full(length, np.nan, dtype=float)
    if length == 0:
        return output
    window = values[start:length] if end is None else values[start:end + 1]
    if len(window) == 0:
        return output
    series = pd.Series(window, dtype=float)
    minimum = min(_MIN_PERIODS.get(op, 1), max(1, len(series)))
    if op == "quantile":
        if quantile is None:
            raise ValueError("groupby_scope.quantile requires q")
        expanded = series.expanding(min_periods=minimum).quantile(quantile)
    elif op == "median":
        expanded = series.expanding(min_periods=minimum).median()
    else:
        expanded = getattr(series.expanding(min_periods=minimum), op)()
    # positions after the fixed end keep the completed window's value
    if end is not None and end + 1 < length:
        tail = np.full(length - (end + 1), expanded.iloc[-1], dtype=float)
        expanded = pd.concat([expanded, pd.Series(tail, index=range(end + 1, length))])
    output[start:] = expanded.to_numpy(dtype=float)[: length - start]
    return output


def _prefix_arg_extreme_loop(
    values: np.ndarray, op: str, start: int, end: int,
) -> np.ndarray:
    """逐根实现：小分区下比 numpy 调用开销更低，同时作为向量化版的等价参照。"""
    length = len(values)
    output = np.full(length, np.nan, dtype=float)
    best_index = -1
    stop = length - 1 if end is None else min(end, length - 1)
    for position in range(start, length):
        limit = position if end is None else min(position, stop)
        if position == start:
            best_index = start
        elif limit > best_index:
            candidates = values[best_index + 1: limit + 1]
            if len(candidates) and not np.all(np.isnan(candidates)):
                offset = (np.nanargmax(candidates) if op == "argmax"
                          else np.nanargmin(candidates))
                challenger = best_index + 1 + int(offset)
                best_value, challenger_value = values[best_index], values[challenger]
                if np.isnan(best_value):
                    best_index = challenger
                elif not np.isnan(challenger_value):
                    # 只有严格更优才推进，保证与 rolling 的「最早出现的极值」一致
                    if op == "argmax" and challenger_value > best_value:
                        best_index = challenger
                    elif op == "argmin" and challenger_value < best_value:
                        best_index = challenger
        if np.isnan(values[position]):
            continue
        span = position - start
        age = position - best_index
        output[position] = 0.0 if span == 0 else age / span
    return output


def _prefix_arg_extreme(
    values: np.ndarray, op: str, start: int, end: int,
) -> np.ndarray:
    """Normalised position of the running extreme, 0 = newest, 1 = oldest.

    Mirrors ``rolling.py::_rolling_argmaxmin``'s convention so the two operators
    mean the same thing at the day's last bar.

    Vectorised form of the per-bar recurrence: the running extreme and the
    **first** position attaining it are both prefix scans, so the whole
    partition is one pass of numpy instead of one Python step per bar.  Ties
    keep the earliest occurrence (strict improvement only), and positions after
    a truncated end keep advancing their span while the extreme stays frozen —
    both match the per-bar implementation, which is kept for small partitions
    where numpy's per-call overhead would dominate.
    """
    length = len(values)
    if length == 0 or start >= length:
        return np.full(length, np.nan, dtype=float)
    stop = length - 1 if end is None else min(end, length - 1)
    if stop - start + 1 < _ARG_EXTREME_VECTOR_FLOOR:
        return _prefix_arg_extreme_loop(values, op, start, end)

    is_max = op == "argmax"
    window = values[start:stop + 1]
    filled = np.where(np.isnan(window), -np.inf if is_max else np.inf, window)
    running = np.maximum.accumulate(filled) if is_max else np.minimum.accumulate(filled)
    previous = np.r_[-np.inf if is_max else np.inf, running[:-1]]
    positions = np.arange(start, stop + 1)
    # 严格优于「此前的极值」才记录 → 并列取最早出现（与逐根实现一致）
    improved = np.isfinite(filled) & (filled > previous if is_max else filled < previous)
    # 回退值是 start（不是 -1）：逐根实现即使在 start 处是 NaN 也把 best 置为 start，
    # 而截断到 start 时 limit > best 不再成立、best 便不再推进，两者必须一致。
    first_at = np.where(improved, positions, start)
    best = np.maximum.accumulate(first_at)

    tail = np.arange(start, length)
    best_at = best[np.minimum(tail, stop) - start]
    span = tail - start
    with np.errstate(invalid="ignore", divide="ignore"):
        result = np.where(span == 0, 0.0, (tail - best_at) / np.maximum(span, 1))
    result = np.where(np.isnan(values[start:]), np.nan, result)
    output = np.full(length, np.nan, dtype=float)
    output[start:] = result
    return output


def apply_grouped(
    op: str,
    scope: LookbackScope,
    data: pd.DataFrame,
    *,
    ctx: Any,
    quantile: float | None = None,
    trunc_start: int | None = None,
    trunc_end: int | None = None,
) -> pd.DataFrame:
    """Partition ``data`` by ``scope`` and aggregate inside each partition."""
    if op not in GROUPED_AGGREGATIONS:
        raise ValueError(f"Unknown groupby_scope aggregation: {op}")
    values = data.to_numpy(dtype=float)
    observed = _observed_mask(data, ctx)
    output = np.full(values.shape, np.nan, dtype=float)
    for column in range(values.shape[1]):
        rows = np.flatnonzero(observed[:, column])
        if len(rows) == 0:
            continue
        column_values = values[rows, column]
        keys = partition_keys(data.index, rows, scope, ctx)
        for start_ordinal, stop_ordinal in _group_bounds(keys):
            group = column_values[start_ordinal:stop_ordinal]
            start = 0 if trunc_start is None else max(0, int(trunc_start))
            end = None if trunc_end is None else max(0, int(trunc_end))
            if end is not None and end >= len(group):
                end = None
            if op in ("argmax", "argmin"):
                result = _prefix_arg_extreme(group, op, start, end)
            else:
                result = _prefix_aggregate(group, op, quantile, start, end)
            output[rows[start_ordinal:stop_ordinal], column] = result
    return pd.DataFrame(output, index=data.index, columns=data.columns)