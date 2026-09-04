"""Batch evaluation helpers for bar-search expressions."""

from __future__ import annotations

from collections import deque
from typing import Any, Literal

import numpy as np
import pandas as pd

from tools.data.types import finest_index

from .composite import CompositeExpr
from .conditional import WhereOp, apply_where
from .core import EvaluateContext, FactorExpr
from .leaf import ConstExpr
from .lookback_scope import BarCountScope, LookbackScope, SessionScope, TradingDayScope
from .match_refs import MatchValueRef
from .pointwise import POINTWISE_OPS, apply_pointwise, carry_formed_signal

Selection = Literal["nearest", "farthest"]


def scalar_default(expr: FactorExpr) -> float | None:
    if type(expr).__name__ == "ScopeLengthDefault":
        return None
    if not isinstance(expr, ConstExpr) or not np.isscalar(expr.value):
        raise TypeError("bar search default must resolve to a scalar constant")
    return float(expr.value)


def _observed_mask(frame: pd.DataFrame, ctx: EvaluateContext) -> np.ndarray:
    if ctx.panel_timeline is None:
        return np.ones(frame.shape, dtype=bool)
    return ctx.panel_timeline.observed_mask.reindex(
        index=frame.index, columns=frame.columns, fill_value=False,
    ).to_numpy(dtype=bool)


def _segment_keys(
    index: pd.Index,
    observed_rows: np.ndarray,
    scope: LookbackScope,
    ctx: EvaluateContext,
) -> np.ndarray:
    if isinstance(scope, BarCountScope):
        return np.zeros(len(observed_rows), dtype=np.int64)
    if isinstance(scope, TradingDayScope):
        if ctx.panel_timeline is None:
            raise ValueError("trading_day bar-search scope requires panel_timeline")
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
    raise TypeError(f"unsupported bar-search scope: {scope!r}")


def evaluate_bar_since(
    condition: pd.DataFrame,
    *,
    scope: LookbackScope,
    select: Selection,
    default: float | None,
    ctx: EvaluateContext,
    include_current: bool,
) -> pd.DataFrame:
    values = condition.fillna(False).to_numpy(dtype=bool)
    observed = _observed_mask(condition, ctx)
    output = np.full(values.shape, np.nan, dtype=float)
    for column in range(values.shape[1]):
        rows = np.flatnonzero(observed[:, column])
        segments = _segment_keys(condition.index, rows, scope, ctx)
        matches: deque[int] = deque()
        previous_segment = -1
        segment_ordinal = -1
        for ordinal, (row, segment_key) in enumerate(zip(rows, segments, strict=True)):
            if int(segment_key) != previous_segment:
                matches.clear()
                previous_segment = int(segment_key)
                segment_ordinal = 0
            else:
                segment_ordinal += 1
            if include_current and values[int(row), column]:
                matches.append(ordinal)
            minimum = (
                ordinal - scope.resolved_count(ctx=ctx)
                if isinstance(scope, BarCountScope)
                else 0
            )
            while matches and matches[0] < minimum:
                matches.popleft()
            if matches:
                matched = matches[-1] if select == "nearest" else matches[0]
                output[int(row), column] = ordinal - matched
            else:
                scope_age = (
                    min(scope.resolved_count(ctx=ctx), segment_ordinal)
                    if isinstance(scope, BarCountScope)
                    else segment_ordinal
                )
                output[int(row), column] = scope_age if default is None else default
            if not include_current and values[int(row), column]:
                matches.append(ordinal)
    return pd.DataFrame(output, index=condition.index, columns=condition.columns)


def _evaluate_match_predicate(
    expr: FactorExpr,
    *,
    ctx: EvaluateContext,
    current: np.ndarray,
    candidate: np.ndarray,
    template: pd.DataFrame,
    static_cache: dict[int, Any],
) -> Any:
    if isinstance(expr, MatchValueRef):
        return current if expr.role == "current" else candidate
    if isinstance(expr, ConstExpr):
        return expr.value
    if isinstance(expr, WhereOp):
        values = [
            _evaluate_match_predicate(
                operand, ctx=ctx, current=current, candidate=candidate,
                template=template, static_cache=static_cache,
            )
            for operand in expr.operands
        ]
        return apply_where(*values)
    if isinstance(expr, CompositeExpr):
        # CompositeExpr is the shared base for binary pointwise math and for
        # structured composite operators (SignalAlign etc.).  Only true
        # pointwise ops can be applied operand-by-operand against the current
        # bar candidate; a nested-frequency operand such as a FactorParam
        # reference compiles to a SignalAlign whose own evaluate() must run as
        # a whole expression.  Treating it as a pointwise call raises
        # "unsupported pointwise op" in the bar-search condition.
        if expr.op in POINTWISE_OPS:
            values = tuple(
                _evaluate_match_predicate(
                    operand, ctx=ctx, current=current, candidate=candidate,
                    template=template, static_cache=static_cache,
                )
                for operand in expr.operands
            )
            return apply_pointwise(expr.op, values)
        # Non-pointwise composite: fall through to whole-expression
        # evaluation below.
    key = id(expr)
    if key in static_cache:
        return static_cache[key]
    value = expr.evaluate(ctx=ctx)
    if isinstance(value, pd.DataFrame):
        if any(str(name).startswith("_SIGNAL@") for name in value.index.names):
            value = carry_formed_signal(value, template)
        else:
            value = value.reindex(index=template.index, columns=template.columns)
        result: Any = value.to_numpy()
    else:
        result = value
    static_cache[key] = result
    return result


def evaluate_bar_distance(
    values: pd.DataFrame,
    condition_expr: FactorExpr,
    *,
    scope: LookbackScope,
    select: Selection,
    default: float | None,
    ctx: EvaluateContext,
) -> pd.DataFrame:
    current = values.to_numpy(dtype=float)
    observed = _observed_mask(values, ctx)
    output = np.full(current.shape, np.nan, dtype=float)
    matched = np.zeros(current.shape, dtype=bool)
    static_cache: dict[int, Any] = {}
    row_maps: list[tuple[np.ndarray, np.ndarray]] = []
    max_lag = 0
    for column in range(values.shape[1]):
        rows = np.flatnonzero(observed[:, column])
        segments = _segment_keys(values.index, rows, scope, ctx)
        row_maps.append((rows, segments))
        segment_age = -1
        previous_segment = -1
        for row, segment in zip(rows, segments, strict=True):
            if int(segment) != previous_segment:
                segment_age = 0
                previous_segment = int(segment)
            else:
                segment_age += 1
            scope_age = (
                min(scope.resolved_count(ctx=ctx), segment_age)
                if isinstance(scope, BarCountScope)
                else segment_age
            )
            output[int(row), column] = scope_age if default is None else default
        if isinstance(scope, BarCountScope):
            max_lag = max(max_lag, scope.resolved_count(ctx=ctx))
        elif len(rows):
            _, counts = np.unique(segments, return_counts=True)
            max_lag = max(max_lag, int(counts.max()) - 1)
    for lag in range(1, max_lag + 1):
        candidate = np.full(current.shape, np.nan, dtype=float)
        for column, (rows, segments) in enumerate(row_maps):
            if len(rows) <= lag:
                continue
            target_ordinals = np.arange(lag, len(rows))
            source_ordinals = target_ordinals - lag
            same_segment = segments[target_ordinals] == segments[source_ordinals]
            target_rows = rows[target_ordinals[same_segment]]
            source_rows = rows[source_ordinals[same_segment]]
            candidate[target_rows, column] = current[source_rows, column]
        raw_condition = np.asarray(
            _evaluate_match_predicate(
                condition_expr, ctx=ctx, current=current, candidate=candidate,
                template=values, static_cache=static_cache,
            ),
        )
        condition = np.isfinite(raw_condition) & raw_condition.astype(bool)
        condition &= np.isfinite(current) & np.isfinite(candidate)
        if select == "nearest":
            take = condition & ~matched
            output[take] = lag
            matched |= condition
        else:
            output[condition] = lag
    return pd.DataFrame(output, index=values.index, columns=values.columns)
