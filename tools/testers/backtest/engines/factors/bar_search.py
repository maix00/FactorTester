"""Incremental execution nodes for bar-search expressions."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from typing import Any

import numpy as np
import pandas as pd

from tools.factors.expr import CompositeExpr, ConstExpr, WhereOp
from tools.factors.expr.conditional import apply_where
from tools.factors.expr.lookback_scope import (
    BarCountScope,
    LookbackScope,
    SessionScope,
    TradingDayScope,
)
from tools.factors.expr.match_refs import MatchValueRef
from tools.factors.expr.pointwise import apply_pointwise

Predicate = Callable[[np.ndarray, np.ndarray, Any, dict[int, np.ndarray]], np.ndarray]


def compile_match_predicate(expr: Any, compile_node: Callable[[Any], Any]) -> Predicate:
    if isinstance(expr, MatchValueRef):
        if expr.role == "current":
            return lambda current, candidate, market, cache: current
        return lambda current, candidate, market, cache: candidate
    if isinstance(expr, ConstExpr):
        value = expr.value
        return lambda current, candidate, market, cache: value
    if isinstance(expr, WhereOp):
        children = tuple(compile_match_predicate(item, compile_node) for item in expr.operands)
        return lambda current, candidate, market, cache: np.asarray(apply_where(*(
            child(current, candidate, market, cache) for child in children
        )))
    if isinstance(expr, CompositeExpr):
        children = tuple(compile_match_predicate(item, compile_node) for item in expr.operands)
        return lambda current, candidate, market, cache: np.asarray(apply_pointwise(
            expr.op,
            tuple(child(current, candidate, market, cache) for child in children),
        ))
    node = compile_node(expr)
    return lambda current, candidate, market, cache: node.update(market, cache)


class _ScopedState:
    def __init__(self, scope: LookbackScope) -> None:
        self.scope = scope
        self._last_timestamp: pd.Timestamp | None = None
        self._last_trading_day: pd.Timestamp | None = None

    def should_reset(self, market: Any) -> bool:
        timestamp = pd.Timestamp(market.timestamp)
        reset = False
        if isinstance(self.scope, SessionScope) and self._last_timestamp is not None:
            reset = timestamp - self._last_timestamp >= pd.Timedelta(self.scope.gap)
        elif isinstance(self.scope, TradingDayScope):
            trading_day = getattr(market, "trading_day", None)
            if trading_day is None:
                raise ValueError("streaming trading_day scope requires an explicit trading day")
            normalized = pd.Timestamp(trading_day).normalize()
            reset = self._last_trading_day is not None and normalized != self._last_trading_day
            self._last_trading_day = normalized
        self._last_timestamp = timestamp
        return reset


class BarSinceNode(_ScopedState):
    def __init__(self, child: Any, *, scope: LookbackScope, select: str, default: float | None, width: int, include_current: bool) -> None:
        super().__init__(scope)
        self.child = child
        self.select = select
        self.default = default
        self.width = width
        self.include_current = include_current
        self._ordinal = -1
        self._matches = [deque() for _ in range(width)]

    def update(self, market: Any, cache: dict[int, np.ndarray]) -> np.ndarray:
        key = id(self)
        if key in cache:
            return cache[key]
        if self.should_reset(market):
            self._ordinal = -1
            for matches in self._matches:
                matches.clear()
        self._ordinal += 1
        condition = np.asarray(self.child.update(market, cache), dtype=float)
        fallback = (
            min(self.scope.resolved_count(), self._ordinal)
            if self.default is None and isinstance(self.scope, BarCountScope)
            else self._ordinal if self.default is None else self.default
        )
        output = np.full(self.width, fallback, dtype=float)
        for column, matches in enumerate(self._matches):
            is_match = np.isfinite(condition[column]) and bool(condition[column])
            if self.include_current and is_match:
                matches.append(self._ordinal)
            if isinstance(self.scope, BarCountScope):
                minimum = self._ordinal - self.scope.resolved_count()
                while matches and matches[0] < minimum:
                    matches.popleft()
            if matches:
                matched = matches[-1] if self.select == "nearest" else matches[0]
                output[column] = self._ordinal - matched
            if not self.include_current and is_match:
                matches.append(self._ordinal)
        cache[key] = output
        return output


class BarDistanceNode(_ScopedState):
    def __init__(
        self,
        child: Any,
        predicate: Predicate,
        *,
        scope: LookbackScope,
        select: str,
        default: float | None,
        width: int,
    ) -> None:
        super().__init__(scope)
        self.child = child
        self.predicate = predicate
        self.select = select
        self.default = default
        self.width = width
        self._scope_age = -1
        maxlen = scope.resolved_count() if isinstance(scope, BarCountScope) else None
        self._history: deque[np.ndarray] = deque(maxlen=maxlen)

    def update(self, market: Any, cache: dict[int, np.ndarray]) -> np.ndarray:
        key = id(self)
        if key in cache:
            return cache[key]
        if self.should_reset(market):
            self._history.clear()
            self._scope_age = -1
        self._scope_age += 1
        current = np.asarray(self.child.update(market, cache), dtype=float)
        fallback = (
            min(self.scope.resolved_count(), self._scope_age)
            if self.default is None and isinstance(self.scope, BarCountScope)
            else self._scope_age if self.default is None else self.default
        )
        output = np.full(self.width, fallback, dtype=float)
        matched = np.zeros(self.width, dtype=bool)
        candidates = reversed(self._history) if self.select == "nearest" else iter(self._history)
        history_length = len(self._history)
        for position, candidate in enumerate(candidates):
            lag = position + 1 if self.select == "nearest" else history_length - position
            raw_condition = np.asarray(
                self.predicate(current, candidate, market, cache),
            )
            condition = np.isfinite(raw_condition) & raw_condition.astype(bool)
            condition &= np.isfinite(current) & np.isfinite(candidate)
            if self.select == "nearest":
                take = condition & ~matched
                output[take] = lag
                matched |= condition
            else:
                take = condition & ~matched
                output[take] = lag
                matched |= condition
        self._history.append(current.copy())
        cache[key] = output
        return output
