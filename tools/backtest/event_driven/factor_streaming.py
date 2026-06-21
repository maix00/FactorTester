"""Compile existing FactorExpr graphs into incremental event executors."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Protocol

import numpy as np
import pandas as pd

from tools.factors.expr import ColumnRef, CompositeExpr, ConstExpr, FactorExpr, RollingOp

from .factor_events import IncrementalFactorExecutor
from .runtime import MarketSlice


class UnsupportedStreamingFactor(ValueError):
    pass


class StreamingNode(Protocol):
    def update(self, market: MarketSlice, cache: dict[int, np.ndarray]) -> np.ndarray: ...


@dataclass(slots=True)
class ConstantNode:
    value: float
    width: int

    def update(self, market: MarketSlice, cache: dict[int, np.ndarray]) -> np.ndarray:
        return np.full(self.width, self.value, dtype=float)


@dataclass(slots=True)
class ColumnNode:
    column_name: str
    products: tuple[str, ...]

    def update(self, market: MarketSlice, cache: dict[int, np.ndarray]) -> np.ndarray:
        try:
            return np.asarray([
                market.prices[product].fields[self.column_name]
                for product in self.products
            ], dtype=float)
        except KeyError as exc:
            raise KeyError(f"market slice is missing factor column {self.column_name!r}") from exc


@dataclass(slots=True)
class CompositeNode:
    op: str
    children: tuple[StreamingNode, ...]

    def update(self, market: MarketSlice, cache: dict[int, np.ndarray]) -> np.ndarray:
        key = id(self)
        if key in cache:
            return cache[key]
        values = [child.update(market, cache) for child in self.children]
        with np.errstate(all="ignore"):
            result = _apply_composite(self.op, values)
        cache[key] = np.asarray(result, dtype=float)
        return cache[key]


class RollingMeanNode:
    def __init__(self, child: StreamingNode, window: int, width: int) -> None:
        self.child = child
        self.window = window
        self.min_periods = max(1, window // 2)
        self._history: deque[np.ndarray] = deque(maxlen=window)
        self._width = width

    def update(self, market: MarketSlice, cache: dict[int, np.ndarray]) -> np.ndarray:
        key = id(self)
        if key in cache:
            return cache[key]
        self._history.append(self.child.update(market, cache).copy())
        history = np.asarray(self._history, dtype=float)
        valid_count = np.sum(np.isfinite(history), axis=0)
        result = np.divide(
            np.nansum(history, axis=0),
            valid_count,
            out=np.full(self._width, np.nan, dtype=float),
            where=valid_count >= self.min_periods,
        )
        cache[key] = result
        return result


class StreamingFactorPlan:
    def __init__(
        self,
        expression: FactorExpr,
        products: tuple[str, ...],
        root: StreamingNode,
    ) -> None:
        self.expression = expression
        self.products = products
        self._root = root

    def update(self, timestamp: pd.Timestamp, market: MarketSlice) -> dict[str, float]:
        if set(market.prices) != set(self.products):
            raise ValueError("streaming factor products do not match the market slice")
        values = self._root.update(market, {})
        return dict(zip(self.products, values, strict=True))


def compile_streaming_factor(
    expression: FactorExpr,
    products: tuple[str, ...],
) -> StreamingFactorPlan:
    if not products or len(set(products)) != len(products):
        raise ValueError("streaming products must be non-empty and unique")
    memo: dict[int, StreamingNode] = {}

    def compile_node(expr: FactorExpr) -> StreamingNode:
        key = id(expr)
        if key in memo:
            return memo[key]
        if isinstance(expr, ConstExpr):
            if not np.isscalar(expr.value):
                raise UnsupportedStreamingFactor("streaming constants must be scalar")
            node: StreamingNode = ConstantNode(float(expr.value), len(products))
        elif isinstance(expr, ColumnRef):
            node = ColumnNode(expr.column.name, products)
        elif isinstance(expr, CompositeExpr):
            if expr.op not in _COMPOSITE_OPS:
                raise UnsupportedStreamingFactor(f"unsupported composite op: {expr.op}")
            node = CompositeNode(expr.op, tuple(compile_node(item) for item in expr.operands))
        elif isinstance(expr, RollingOp):
            if expr.op != "rolling_mean" or expr._n_data != 1:
                raise UnsupportedStreamingFactor(f"unsupported rolling op: {expr.op}")
            if expr._trunc_start is not None or expr._trunc_end is not None:
                raise UnsupportedStreamingFactor("truncated rolling windows are not supported")
            if not isinstance(expr.window, ConstExpr) or not isinstance(expr.window.value, int):
                raise UnsupportedStreamingFactor("streaming windows must resolve to fixed bars")
            if expr.window.value <= 0:
                raise UnsupportedStreamingFactor("streaming window must be positive")
            node = RollingMeanNode(
                compile_node(expr.operand), expr.window.value, len(products)
            )
        else:
            raise UnsupportedStreamingFactor(
                f"unsupported FactorExpr node: {type(expr).__name__}"
            )
        memo[key] = node
        return node

    return StreamingFactorPlan(expression, products, compile_node(expression))


def compile_incremental_factor(
    factor_alias: str,
    expression: FactorExpr,
    products: tuple[str, ...],
) -> IncrementalFactorExecutor:
    """Compile one author-facing FactorExpr into a runtime FactorActor."""

    plan = compile_streaming_factor(expression, products)
    return IncrementalFactorExecutor(factor_alias, plan.update)


_COMPOSITE_OPS = {
    "add", "sub", "mul", "div", "neg", "abs", "sign", "sqrt", "log",
    "pow", "bimax", "bimin", "max", "min",
}


def _apply_composite(op: str, values: list[np.ndarray]) -> np.ndarray:
    if op == "add":
        return values[0] + values[1]
    if op == "sub":
        return values[0] - values[1]
    if op == "mul":
        return values[0] * values[1]
    if op == "div":
        return values[0] / values[1]
    if op == "neg":
        return -values[0]
    if op == "abs":
        return np.abs(values[0])
    if op == "sign":
        return np.sign(values[0])
    if op == "sqrt":
        return np.sqrt(values[0])
    if op == "log":
        return np.log(values[0])
    if op == "pow":
        return values[0] ** values[1]
    if op in {"bimax", "max"}:
        return np.maximum.reduce(values)
    if op in {"bimin", "min"}:
        return np.minimum.reduce(values)
    raise UnsupportedStreamingFactor(f"unsupported composite op: {op}")
