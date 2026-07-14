"""Compile existing FactorExpr graphs into incremental event executors."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Mapping, Protocol

import numpy as np
import pandas as pd

from tools.data.types import DataFreq
from tools.factors.expr import (
    ColumnRef,
    CompositeExpr,
    ConstExpr,
    CrossSectionalOp,
    FactorExpr,
    RollingOp,
    ShiftOp,
    WhereOp,
)

if TYPE_CHECKING:
    # MarketSlice lived in the now-deleted engines/native/runtime.py
    # (issue-114 rewrite). Used here purely as a type annotation on
    # `update(self, market: MarketSlice, ...)`, never instantiated — keep
    # as a type-checking-only forward ref rather than reviving the old
    # runtime module.
    from ..native.runtime import MarketSlice  # type: ignore[attr-defined]


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
    products: tuple[Any, ...]

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


class RollingWindowNode:
    def __init__(
        self,
        op: str,
        children: tuple[StreamingNode, ...],
        window: int,
        width: int,
    ) -> None:
        self.op = op
        self.children = children
        self.window = window
        self._histories = [deque(maxlen=window) for _ in children]
        self._width = width

    def update(self, market: MarketSlice, cache: dict[int, np.ndarray]) -> np.ndarray:
        key = id(self)
        if key in cache:
            return cache[key]
        for history, child in zip(self._histories, self.children, strict=True):
            history.append(child.update(market, cache).copy())
        result = self._aggregate()
        cache[key] = result
        return result

    def _aggregate(self) -> np.ndarray:
        frames = [pd.DataFrame(np.asarray(history, dtype=float)) for history in self._histories]
        frame = frames[0]
        min_periods = 1 if self.op in {
            "rolling_min", "rolling_max", "rolling_sum",
            "rolling_argmax", "rolling_argmin",
            "rolling_argmax_raw", "rolling_argmin_raw",
        } else max(1, self.window // 2)
        if self.op == "rolling_mean":
            return frame.mean(axis=0, skipna=True).where(frame.count() >= min_periods).to_numpy()
        if self.op == "rolling_std":
            return frame.std(axis=0, skipna=True).where(frame.count() >= min_periods).to_numpy()
        if self.op == "rolling_var":
            return frame.var(axis=0, skipna=True).where(frame.count() >= min_periods).to_numpy()
        if self.op == "rolling_min":
            return frame.min(axis=0, skipna=True).to_numpy()
        if self.op == "rolling_max":
            return frame.max(axis=0, skipna=True).to_numpy()
        if self.op == "rolling_sum":
            return frame.sum(axis=0, skipna=True, min_count=min_periods).to_numpy()
        if self.op == "rolling_skew":
            return frame.skew(axis=0, skipna=True).where(frame.count() >= min_periods).to_numpy()
        if self.op in {"rolling_corr", "rolling_cov"}:
            if len(frame) < self.window:
                return np.full(self._width, np.nan, dtype=float)
            method = "corr" if self.op == "rolling_corr" else "cov"
            return np.asarray([
                getattr(frame[column], method)(frames[1][column])
                for column in frame.columns
            ], dtype=float)
        if self.op.startswith("rolling_arg"):
            is_max = "argmax" in self.op
            normalize = not self.op.endswith("_raw")
            output = np.full(self._width, np.nan, dtype=float)
            for column in range(self._width):
                values = frame[column].to_numpy(dtype=float)
                valid = np.flatnonzero(np.isfinite(values))
                if valid.size < min_periods:
                    continue
                position = valid[np.argmax(values[valid]) if is_max else np.argmin(values[valid])]
                output[column] = position / max(1, self.window - 1) if normalize else position
            return output
        raise UnsupportedStreamingFactor(f"unsupported rolling op: {self.op}")


class ExpandingEwmNode:
    def __init__(self, child: StreamingNode, span: int, width: int) -> None:
        self.child = child
        self.span = span
        self._history: list[np.ndarray] = []
        self._width = width

    def update(self, market: MarketSlice, cache: dict[int, np.ndarray]) -> np.ndarray:
        key = id(self)
        if key in cache:
            return cache[key]
        self._history.append(self.child.update(market, cache).copy())
        frame = pd.DataFrame(np.asarray(self._history, dtype=float))
        min_periods = max(1, self.span // 2)
        result = frame.ewm(span=self.span, min_periods=min_periods).mean().iloc[-1]
        cache[key] = result.to_numpy(dtype=float)
        if len(cache[key]) != self._width:
            raise ValueError("streaming ewm output width changed unexpectedly")
        return cache[key]


class ShiftNode:
    def __init__(self, child: StreamingNode, periods: int, width: int) -> None:
        self.child = child
        self.periods = periods
        self._history: deque[np.ndarray] = deque(maxlen=periods + 1)
        self._width = width

    def update(self, market: MarketSlice, cache: dict[int, np.ndarray]) -> np.ndarray:
        value = self.child.update(market, cache).copy()
        self._history.append(value)
        if len(self._history) <= self.periods:
            return np.full(self._width, np.nan, dtype=float)
        return self._history[0].copy()


@dataclass(slots=True)
class CrossSectionalNode:
    op: str
    children: tuple[StreamingNode, ...]

    def update(self, market: MarketSlice, cache: dict[int, np.ndarray]) -> np.ndarray:
        if len(self.children) != 1:
            raise UnsupportedStreamingFactor(
                f"{self.op} produces an IC time series, not product-level live signal values"
            )
        values = self.children[0].update(market, cache)
        series = pd.Series(values, dtype=float)
        if self.op == "cs_rank":
            return (series.rank(pct=True) - 0.5).to_numpy()
        if self.op == "cs_zscore":
            std = series.std()
            if std == 0:
                return np.where(series.isna(), np.nan, 0.0)
            return ((series - series.mean()) / std).to_numpy()
        raise UnsupportedStreamingFactor(f"unsupported cross-sectional op: {self.op}")


@dataclass(slots=True)
class WhereNode:
    cond: StreamingNode
    true_value: StreamingNode
    false_value: StreamingNode

    def update(self, market: MarketSlice, cache: dict[int, np.ndarray]) -> np.ndarray:
        cond = self.cond.update(market, cache).astype(bool)
        true_value = self.true_value.update(market, cache)
        false_value = self.false_value.update(market, cache)
        return np.where(cond, true_value, false_value)


class StreamingFactorPlan:
    def __init__(
        self,
        expression: FactorExpr,
        products: tuple[Any, ...],
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


@dataclass(frozen=True, slots=True)
class _StreamingBarPrice:
    fields: Mapping[str, float]


@dataclass(frozen=True, slots=True)
class _StreamingMarketSlice:
    prices: Mapping[Any, _StreamingBarPrice]


class IncrementalFactorExecutor:
    """Run-scoped stateful executor produced from a FactorExpr graph."""

    def __init__(self, factor_alias: str, plan: StreamingFactorPlan) -> None:
        if not factor_alias:
            raise ValueError("incremental executor requires a factor alias")
        self.factor_alias = factor_alias
        self._plan = plan
        self._latest: dict[Any, float] = {}

    def on_bar(self, timestamp: pd.Timestamp, fields_by_product: Mapping[Any, Any]) -> None:
        missing = [product for product in self._plan.products if product not in fields_by_product]
        if missing:
            raise ValueError(f"market slice is missing streaming products: {missing!r}")
        market = _StreamingMarketSlice({
            product: _StreamingBarPrice(_normalize_bar_fields(fields))
            for product, fields in fields_by_product.items()
            if product in self._plan.products
        })
        self._latest = {
            product: float(value)
            for product, value in self._plan.update(pd.Timestamp(timestamp), market).items()
        }

    def on_signal(self, timestamp: pd.Timestamp) -> dict[Any, float]:
        return dict(self._latest)


def compile_streaming_factor(
    expression: FactorExpr,
    products: tuple[Any, ...],
    *,
    source_freq: DataFreq | str | None = None,
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
            if expr._trunc_start is not None or expr._trunc_end is not None:
                raise UnsupportedStreamingFactor("truncated rolling windows are not supported")
            if not isinstance(expr.window, ConstExpr):
                raise UnsupportedStreamingFactor("streaming windows must resolve to fixed bars")
            window = _resolve_window_bars(expr.window.value, source_freq)
            children = tuple(
                compile_node(item)
                for item in expr.operands[expr._data_start:expr._data_start + expr._n_data]
            )
            if expr.op == "rolling_ema":
                if len(children) != 1:
                    raise UnsupportedStreamingFactor("rolling_ema expects one streaming operand")
                node = ExpandingEwmNode(children[0], window, len(products))
            else:
                node = RollingWindowNode(
                    expr.op,
                    children,
                    window,
                    len(products),
                )
        elif isinstance(expr, ShiftOp):
            if not isinstance(expr.periods, ConstExpr) or not isinstance(expr.periods.value, int):
                raise UnsupportedStreamingFactor("streaming shifts must resolve to fixed bars")
            if expr.periods.value < 0:
                raise UnsupportedStreamingFactor("streaming shifts cannot look into the future")
            node = ShiftNode(
                compile_node(expr.operand),
                expr.periods.value,
                len(products),
            )
        elif isinstance(expr, CrossSectionalOp):
            if expr.op in {"cs_corr", "cs_spearman"}:
                raise UnsupportedStreamingFactor(
                    f"{expr.op} produces an IC time series, not product-level live signal values"
                )
            if expr.op not in {"cs_rank", "cs_zscore"}:
                raise UnsupportedStreamingFactor(
                    f"unsupported cross-sectional op: {expr.op}"
                )
            node = CrossSectionalNode(expr.op, (compile_node(expr.operand),))
        elif isinstance(expr, WhereOp):
            if len(expr.operands) != 3:
                raise UnsupportedStreamingFactor("where expects condition, true, and false operands")
            node = WhereNode(
                compile_node(expr.operands[0]),
                compile_node(expr.operands[1]),
                compile_node(expr.operands[2]),
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
    products: tuple[Any, ...],
    *,
    source_freq: DataFreq | str | None = None,
) -> IncrementalFactorExecutor:
    """Compile one author-facing FactorExpr into a run-scoped executor."""

    plan = compile_streaming_factor(expression, products, source_freq=source_freq)
    return IncrementalFactorExecutor(factor_alias, plan)


def _normalize_bar_fields(fields: Any) -> dict[str, float]:
    if isinstance(fields, Mapping):
        return {str(name): float(value) for name, value in fields.items()}
    value = float(fields)
    return {
        "OPEN": value,
        "HIGH": value,
        "LOW": value,
        "CLOSE": value,
    }


def _resolve_window_bars(
    value: object,
    source_freq: DataFreq | str | None,
) -> int:
    if isinstance(value, (int, np.integer)):
        bars = int(value)
    elif isinstance(value, (pd.Timedelta, str)):
        if source_freq is None:
            raise UnsupportedStreamingFactor(
                "duration windows require an explicit source frequency"
            )
        duration = pd.Timedelta(value)
        frequency = DataFreq(source_freq).value
        if duration >= pd.Timedelta("1D") and frequency < pd.Timedelta("1D"):
            raise UnsupportedStreamingFactor(
                "session-spanning duration windows require a trading-calendar kernel"
            )
        ratio = duration / frequency
        if not np.isfinite(ratio) or not np.isclose(ratio, round(ratio)):
            raise UnsupportedStreamingFactor(
                f"window {duration} is not an integer multiple of {frequency}"
            )
        bars = int(round(ratio))
    else:
        raise UnsupportedStreamingFactor("streaming windows must resolve to fixed bars")
    if bars <= 0:
        raise UnsupportedStreamingFactor("streaming window must be positive")
    return bars


_COMPOSITE_OPS = {
    "add", "sub", "mul", "div", "neg", "abs", "sign", "sqrt", "log",
    "pow", "bimax", "bimin", "max", "min", "gt", "lt", "ge", "le",
    "eq", "ne", "and", "or", "not",
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
    if op == "gt":
        return values[0] > values[1]
    if op == "lt":
        return values[0] < values[1]
    if op == "ge":
        return values[0] >= values[1]
    if op == "le":
        return values[0] <= values[1]
    if op == "eq":
        return values[0] == values[1]
    if op == "ne":
        return values[0] != values[1]
    if op == "and":
        return values[0].astype(bool) & values[1].astype(bool)
    if op == "or":
        return values[0].astype(bool) | values[1].astype(bool)
    if op == "not":
        return ~values[0].astype(bool)
    if op in {"bimax", "max"}:
        return np.maximum.reduce(values)
    if op in {"bimin", "min"}:
        return np.minimum.reduce(values)
    raise UnsupportedStreamingFactor(f"unsupported composite op: {op}")
