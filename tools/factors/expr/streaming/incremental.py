"""Compile existing FactorExpr graphs into incremental event executors."""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass, field
from operator import add
from typing import TYPE_CHECKING, Any, Protocol

import numpy as np
import pandas as pd

from tools.data.types import DataFreq
from tools.factors.expr import (
    BarDistanceOp,
    BarSinceOp,
    CategoryBoolRef,
    ColumnRef,
    CompositeExpr,
    ConstExpr,
    CrossSectionalOp,
    FactorExpr,
    RollingOp,
    ShiftOp,
    SignalAlign,
    TermStructureOp,
    WhereOp,
)
from tools.factors.expr.conditional import apply_where
from tools.factors.expr.groupby_scope import GroupByScopeOp
from tools.factors.expr.lookback_scope import BarCountScope
from tools.factors.expr.pointwise import POINTWISE_OPS, apply_pointwise
from tools.factors.expr.rolling_skew import RollingSkewState
from tools.factors.expr.term_structure_math import (
    evaluate_term_curve,
    normalize_term_curve,
)
from tools.factors.interval import IntervalSpec
from tools.factors.lookback import LookbackContract, infer_lookback_contract
from tools.products.AdjustableTermStructure import (
    TERM_RANK_COL,
)

from .bar_search import BarDistanceNode, BarSinceNode, compile_match_predicate
from .cross_sectional_kernels import ordinal_rank, rank_percent, zscore
from .cross_sectional_residual import ResidualizeNode
from .group_cross_sectional import GroupCrossSectionalNode
from .rolling_covariance import RollingCovarianceState
from .rolling_extrema import RollingArgExtremaState, RollingMinMaxState
from .rolling_moments import RollingMomentsState

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
        key = id(self)
        if key not in cache:
            cache[key] = np.full(self.width, self.value, dtype=float)
        return cache[key]


@dataclass(slots=True)
class ColumnNode:
    column_name: str
    products: tuple[Any, ...]

    def update(self, market: MarketSlice, cache: dict[int, np.ndarray]) -> np.ndarray:
        key = id(self)
        if key in cache:
            return cache[key]
        try:
            cache[key] = np.asarray([
                market.prices[product].fields[self.column_name]
                for product in self.products
            ], dtype=float)
            return cache[key]
        except KeyError as exc:
            raise KeyError(f"market slice is missing factor column {self.column_name!r}") from exc


@dataclass(slots=True)
class CategoryBoolNode:
    category: Any
    category_name: str
    products: tuple[Any, ...]

    def update(self, market: MarketSlice, cache: dict[int, np.ndarray]) -> np.ndarray:
        key = id(self)
        if key not in cache:
            cache[key] = np.asarray([
                self.category.is_in_category(self.category_name, product)
                for product in self.products
            ], dtype=bool)
        return cache[key]


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


class SignalHoldNode:
    """Publish a child value on its signal cadence and hold it between bars."""

    def __init__(
        self,
        child: StreamingNode,
        *,
        every_bars: int,
        width: int,
        reset_on_session_gap: bool,
        session_gap: pd.Timedelta,
    ) -> None:
        self.child = child
        self.every_bars = every_bars
        self._count = 0
        self._held = np.full(width, np.nan, dtype=float)
        self._last_timestamp: pd.Timestamp | None = None
        self._reset_on_session_gap = reset_on_session_gap
        self._session_gap = session_gap

    def update(self, market: MarketSlice, cache: dict[int, np.ndarray]) -> np.ndarray:
        key = id(self)
        if key in cache:
            return cache[key]
        timestamp = pd.Timestamp(market.timestamp)
        if (
            self._reset_on_session_gap
            and self._last_timestamp is not None
            and timestamp - self._last_timestamp >= self._session_gap
        ):
            self._count = 0
        value = np.asarray(self.child.update(market, cache), dtype=float)
        self._count += 1
        if self._count % self.every_bars == 0:
            self._held = value.copy()
        self._last_timestamp = timestamp
        cache[key] = self._held.copy()
        return cache[key]


class _BarWindowResolver:
    def __init__(self, window):
        self.window = max(1, int(window))
        self.ordinal = 0

    def __call__(self, _market):
        current = self.ordinal
        self.ordinal += 1
        return IntervalSpec(max(0, current - self.window + 1), current)


class _SessionWindowResolver:
    def __init__(self, calendar, lookback_sessions):
        self.calendar = calendar
        self.lookback_sessions = int(lookback_sessions)
        self.ordinal = 0

    def __call__(self, market):
        timestamp = getattr(market, "timestamp", None)
        if timestamp is None:
            return None
        _session, size = self.calendar.window_for_timestamp(
            int(pd.Timestamp(timestamp).value), self.lookback_sessions,
        )
        current = self.ordinal
        self.ordinal += 1
        return IntervalSpec(max(0, current - int(size) + 1), current)


class _WallWindowResolver:
    def __init__(self, duration_ns):
        self.duration_ns = int(duration_ns)
        self.ordinal = 0
        self._timestamps: deque[tuple[int, int]] = deque()

    def __call__(self, market):
        timestamp = getattr(market, "timestamp", None)
        if timestamp is None:
            return None
        current = self.ordinal
        self.ordinal += 1
        nanos = int(pd.Timestamp(timestamp).value)
        cutoff = nanos - self.duration_ns
        while self._timestamps and self._timestamps[0][1] < cutoff:
            self._timestamps.popleft()
        self._timestamps.append((current, nanos))
        return IntervalSpec(self._timestamps[0][0], current)


class _BarScopeResolver:
    def __init__(self, bar_count):
        self.bar_count = max(1, int(bar_count))
        self.ordinal = 0

    def __call__(self, _market):
        start = (self.ordinal // self.bar_count) * self.bar_count
        current = self.ordinal
        self.ordinal += 1
        return IntervalSpec(start, current)


class _EventResolver:
    def __init__(self, event_ref, event_line):
        self.event_ref = event_ref
        self.event_line = event_line
        self.ordinal = 0

    def __call__(self, _market):
        from tools.factors.events import resolve_event_ref
        occurrence = resolve_event_ref(self.event_ref, self.event_line, 0)
        current = self.ordinal
        self.ordinal += 1
        if occurrence is None:
            return None
        return IntervalSpec(max(0, int(occurrence) - 1), current)


class _RangeResolver:
    def __init__(self, scope, trunc_start, trunc_end, event_line, source_freq, products):
        from tools.factors.events import EventId, EventRef
        from tools.factors.expr.lookback_scope import (
            BarCountScope, SessionScope, TradingDayScope,
        )
        self.trunc_start = int(trunc_start)
        self.trunc_end = int(trunc_end)
        self.ordinal = 0
        self.event_line = event_line
        self.event_ref = None
        self.bar_count = None
        if isinstance(scope, TradingDayScope):
            self.event_ref = EventRef(EventId.TRADING_DAY_START)
        elif isinstance(scope, SessionScope):
            self.event_ref = EventRef(EventId.TRADING_SESSION_START)
        elif isinstance(scope, BarCountScope):
            self.bar_count = int(scope.resolved_count(
                source_freq=source_freq, products=products,
            ))
        else:
            raise UnsupportedStreamingFactor(f"unsupported range scope: {scope!r}")

    def __call__(self, _market):
        current = self.ordinal
        self.ordinal += 1
        if self.bar_count is not None:
            base = (current // self.bar_count) * self.bar_count
        else:
            from tools.factors.events import resolve_event_ref
            occurrence = resolve_event_ref(self.event_ref, self.event_line, 0)
            if occurrence is None:
                return None
            base = max(0, int(occurrence) - 1)
        return IntervalSpec(base + self.trunc_start, base + self.trunc_end)


class RustIntervalNode:
    """The only scope/window node: resolves [start, end] then updates one kernel."""

    _OPS = {
        "mean": "mean", "sum": "sum", "var": "var", "std": "std",
        "min": "min", "max": "max", "skew": "skew",
        "argmin": "argmin", "argmax": "argmax",
        "median": "quantile", "quantile": "quantile", "rank": "rank",
        "mad": "mad",
        "rolling_mean": "mean", "rolling_sum": "sum",
        "rolling_var": "var", "rolling_std": "std",
        "rolling_min": "min", "rolling_max": "max",
        "rolling_skew": "skew",
        "rolling_argmin": "argmin", "rolling_argmax": "argmax",
        "rolling_argmin_raw": "argmin", "rolling_argmax_raw": "argmax",
        "rolling_median": "quantile", "rolling_quantile": "quantile",
        "rolling_rank": "rank", "rolling_mad": "mad",
    }

    def __init__(self, op, child, width, resolver, quantile=None):
        from alpha import IntervalState
        rust_op = self._OPS.get(op)
        if rust_op is None:
            raise UnsupportedStreamingFactor(f"interval does not support {op}")
        self.op = op
        self.child = child
        self.resolver = resolver
        self._width = width
        self._rust_op = rust_op
        self._quantile = quantile
        self._states = [IntervalState(rust_op, quantile) for _ in range(width)]

    def configure(self, min_periods: int, propagate_nan: bool) -> None:
        from alpha import IntervalState
        self._states = [
            IntervalState(self._rust_op, self._quantile, max(1, int(min_periods)), bool(propagate_nan))
            for _ in range(self._width)
        ]

    def update(self, market, cache):
        key = id(self)
        if key in cache:
            return cache[key]
        interval = self.resolver(market)
        if interval is None:
            return np.full(self._width, np.nan, dtype=float)
        start, end = interval.start, interval.end
        values = np.asarray(self.child.update(market, cache), dtype=float)
        if values.shape != (self._width,):
            raise ValueError("interval input width changed")
        result = np.asarray(
            [state.update(start, end, float(value))
             for state, value in zip(self._states, values, strict=True)],
            dtype=float,
        )
        cache[key] = result
        return result


class RustIntervalPairNode:
    """cov/corr over an explicit interval resolved from any boundary."""

    def __init__(self, op, children, width, resolver):
        from alpha import IntervalPairState
        if op not in {"rolling_cov", "rolling_corr"}:
            raise UnsupportedStreamingFactor(f"interval pair does not support {op}")
        self.op = op
        self.children = tuple(children)
        self.resolver = resolver
        self._width = width
        self._states = [
            IntervalPairState(op == "rolling_corr") for _ in range(width)
        ]

    def update(self, market, cache):
        key = id(self)
        if key in cache:
            return cache[key]
        interval = self.resolver(market)
        if interval is None:
            return np.full(self._width, np.nan, dtype=float)
        start, end = interval.start, interval.end
        left = np.asarray(self.children[0].update(market, cache), dtype=float)
        right = np.asarray(self.children[1].update(market, cache), dtype=float)
        if left.shape != (self._width,) or right.shape != (self._width,):
            raise ValueError("interval pair input width changed")
        result = np.asarray(
            [state.update(start, end, float(x), float(y))
             for state, x, y in zip(self._states, left, right, strict=True)],
            dtype=float,
        )
        cache[key] = result
        return result


class RustEmaNode:
    """Adjusted EMA executed by Rust."""

    def __init__(self, child, span, width):
        from alpha import EmaState
        self.child = child
        self.span = int(span)
        self._width = width
        self._states = [EmaState(self.span, 1, True) for _ in range(width)]

    def configure(self, min_periods: int, propagate_nan: bool) -> None:
        from alpha import EmaState
        self._states = [
            EmaState(self.span, max(1, int(min_periods)), bool(propagate_nan))
            for _ in range(self._width)
        ]

    def update(self, market, cache):
        key = id(self)
        if key in cache:
            return cache[key]
        values = np.asarray(self.child.update(market, cache), dtype=float)
        if values.shape != (self._width,):
            raise ValueError("ema input width changed")
        result = np.asarray(
            [state.update(float(value))
             for state, value in zip(self._states, values, strict=True)],
            dtype=float,
        )
        cache[key] = result
        return result


class ShiftNode:
    def __init__(self, child: StreamingNode, periods: int, width: int) -> None:
        self.child = child
        self.periods = periods
        self._history: deque[np.ndarray] = deque(maxlen=periods + 1)
        self._width = width

    def update(self, market: MarketSlice, cache: dict[int, np.ndarray]) -> np.ndarray:
        key = id(self)
        if key in cache:
            return cache[key]
        value = self.child.update(market, cache).copy()
        self._history.append(value)
        if len(self._history) <= self.periods:
            result = np.full(self._width, np.nan, dtype=float)
        else:
            result = self._history[0].copy()
        cache[key] = result
        return result


@dataclass(slots=True)
class CrossSectionalNode:
    op: str
    children: tuple[StreamingNode, ...]
    tie_break_keys: tuple[str, ...]
    _tie_break_order: np.ndarray = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._tie_break_order = np.argsort(
            np.asarray(self.tie_break_keys, dtype=str),
            kind="mergesort",
        )

    def update(self, market: MarketSlice, cache: dict[int, np.ndarray]) -> np.ndarray:
        key = id(self)
        if key in cache:
            return cache[key]
        if self.op in {"cs_ordinal_rank_asc", "cs_ordinal_rank_desc", "cs_rank_masked"}:
            if len(self.children) != 2:
                raise UnsupportedStreamingFactor(f"{self.op} requires value and eligibility mask")
            values = self.children[0].update(market, cache)
            mask = self.children[1].update(market, cache)
            mask_array = np.asarray(mask, dtype=float)
            eligible = ~np.isnan(mask_array) & mask_array.astype(bool)
            if self.op == "cs_rank_masked":
                result = rank_percent(values, eligible)
            else:
                result = ordinal_rank(
                    values,
                    eligible,
                    self._tie_break_order,
                    ascending=self.op == "cs_ordinal_rank_asc",
                )
            cache[key] = result
            return result
        if len(self.children) != 1:
            raise UnsupportedStreamingFactor(
                f"{self.op} produces an IC time series, not product-level live signal values"
            )
        values = self.children[0].update(market, cache)
        if self.op == "cs_rank":
            result = rank_percent(values)
        elif self.op == "cs_zscore":
            result = zscore(values)
        else:
            raise UnsupportedStreamingFactor(f"unsupported cross-sectional op: {self.op}")
        cache[key] = result
        return result


@dataclass(slots=True)
class TermStructureNode:
    op: str
    products: tuple[Any, ...]
    near_rank: int
    far_rank: int
    depth: int
    column_name: str

    def update(self, market: MarketSlice, cache: dict[int, np.ndarray]) -> np.ndarray:
        key = id(self)
        if key not in cache:
            cache[key] = np.asarray([
                self._value_for_curve(product, market.term_curves.get(product))
                for product in self.products
            ], dtype=float)
        return cache[key]

    def _value_for_curve(self, product: Any, curve: pd.DataFrame | None) -> float:
        if curve is None:
            raise KeyError(f"TERM_STRUCTURE snapshot is missing curve for product {product!r}")
        if self.column_name not in curve.columns:
            raise KeyError(f"TERM_STRUCTURE curve for product {product!r} is missing column {self.column_name!r}")
        if TERM_RANK_COL not in curve.columns:
            raise KeyError(f"TERM_STRUCTURE curve for product {product!r} is missing column {TERM_RANK_COL!r}")
        try:
            return evaluate_term_curve(
                self.op,
                curve,
                near_rank=self.near_rank,
                far_rank=self.far_rank,
                depth=self.depth,
                column=self.column_name,
            )
        except KeyError as exc:
            raise KeyError(f"TERM_STRUCTURE curve for product {product!r} is missing required field: {exc}") from exc


@dataclass(slots=True)
class WhereNode:
    cond: StreamingNode
    true_value: StreamingNode
    false_value: StreamingNode

    def update(self, market: MarketSlice, cache: dict[int, np.ndarray]) -> np.ndarray:
        key = id(self)
        if key in cache:
            return cache[key]
        cond = self.cond.update(market, cache)
        true_value = self.true_value.update(market, cache)
        false_value = self.false_value.update(market, cache)
        cache[key] = np.asarray(apply_where(cond, true_value, false_value), dtype=float)
        return cache[key]


from bisect import insort  # placed next to its only consumer


def _resolve_truncation(expr: FactorExpr | None) -> int | None:
    """Resolve a groupby_scope truncation bound; streaming needs fixed bars."""
    if expr is None:
        return None
    if isinstance(expr, ConstExpr):
        value = expr.value
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise UnsupportedStreamingFactor("groupby_scope truncation must be numeric")
        return max(0, int(value))
    raise UnsupportedStreamingFactor("groupby_scope truncation must resolve to fixed bars")


def _with_timestamp(market: MarketSlice, timestamp: pd.Timestamp) -> MarketSlice:
    """Attach the bar timestamp when the slice does not carry one.

    The run-scoped executor already hands over an internal slice that carries
    ``timestamp``/``trading_day``; the precomputed adapter builds a bare
    ``MarketSlice``.  Scope-partitioned kernels need the time to find partition
    boundaries, so fill it in here rather than teaching every node about time.
    """
    if getattr(market, "timestamp", None) is not None:
        return market
    import dataclasses

    try:
        # 只补时间戳，绝不覆盖调用方给出的交易日（它来自权威来源）
        return dataclasses.replace(market, timestamp=pd.Timestamp(timestamp))
    except TypeError:
        return market


class StreamingFactorPlan:
    def __init__(
        self,
        expression: FactorExpr,
        products: tuple[Any, ...],
        root: StreamingNode,
        lookback_contract: LookbackContract | None = None,
        node_keys: tuple[tuple, ...] = (),
    ) -> None:
        self.expression = expression
        self.products = products
        self._root = root
        self.lookback_contract = lookback_contract
        self.node_keys = node_keys

    def update(self, timestamp: pd.Timestamp, market: MarketSlice) -> dict[str, float]:
        if set(market.prices) != set(self.products):
            raise ValueError("streaming factor products do not match the market slice")
        values = self._root.update(_with_timestamp(market, timestamp), {})
        return dict(zip(self.products, values, strict=True))


class MultiStreamingPlan:
    """One incremental plan DAG shared by several factor outputs."""

    def __init__(self, aliases, products, roots, plans):
        self.aliases = tuple(aliases)
        self.products = products
        self._roots = tuple(roots)
        self.plans = tuple(plans)

    def update(self, timestamp, market):
        cache: dict[int, np.ndarray] = {}
        values = {}
        market = _with_timestamp(market, timestamp)
        for alias, root in zip(self.aliases, self._roots, strict=True):
            array = root.update(market, cache)
            values[alias] = dict(zip(self.products, array, strict=True))
        return values


@dataclass(frozen=True, slots=True)
class _StreamingBarPrice:
    fields: Mapping[str, float]


class NormalizedBarFields(dict[str, float]):
    """Internal marker for the native snapshot's string/numeric field map."""

    __slots__ = ()


@dataclass(frozen=True, slots=True)
class _StreamingMarketSlice:
    timestamp: pd.Timestamp
    trading_day: pd.Timestamp | None
    prices: Mapping[Any, _StreamingBarPrice]
    term_curves: Mapping[Any, pd.DataFrame]
    observed: tuple[bool, ...]


class SingleFactorIncrementalExecutor:
    """Compatibility facade: one alias over the shared multi-factor executor."""

    def __init__(self, factor_alias: str, multi: MultiStreamingIncrementalExecutor) -> None:
        self.factor_alias = factor_alias
        self._multi = multi
        self._plan = multi._plan

    def on_bar(self, *args, **kwargs) -> None:
        self._multi.on_bar(*args, **kwargs)

    def on_signal(self, timestamp: pd.Timestamp) -> dict[Any, float]:
        return dict(self._multi.on_signal(timestamp)[self.factor_alias])


class MultiStreamingIncrementalExecutor:
    """Run-scoped executor with one shared DAG for several factors."""

    def __init__(self, plan: MultiStreamingPlan) -> None:
        self._plan = plan
        self._latest: dict[str, dict[Any, float]] = {}

    def on_bar(
        self,
        timestamp: pd.Timestamp,
        fields_by_product: Mapping[Any, Any],
        term_curves_by_product: Mapping[Any, Any] | None = None,
        trading_day: pd.Timestamp | None = None,
    ) -> None:
        term_curves_by_product = term_curves_by_product or {}
        observed_products = set(fields_by_product) | set(term_curves_by_product)
        missing = [product for product in self._plan.products if product not in observed_products]
        if missing:
            raise ValueError(f"market slice is missing streaming products: {missing!r}")
        market = _StreamingMarketSlice(
            pd.Timestamp(timestamp),
            pd.Timestamp(trading_day).normalize() if trading_day is not None else None,
            {
                product: _StreamingBarPrice(_normalize_bar_fields(fields_by_product.get(product, {})))
                for product in self._plan.products
            },
            {
                product: _normalize_term_curve(curve)
                for product, curve in term_curves_by_product.items()
                if product in self._plan.products
            },
            tuple(product in observed_products for product in self._plan.products),
        )
        self._latest = {
            alias: {product: float(value) for product, value in values.items()}
            for alias, values in self._plan.update(pd.Timestamp(timestamp), market).items()
        }

    def on_signal(self, timestamp: pd.Timestamp) -> dict[str, dict[Any, float]]:
        return {alias: dict(values) for alias, values in self._latest.items()}


def compile_streaming_factor(
    expression: FactorExpr,
    products: tuple[Any, ...],
    *,
    source_freq: DataFreq | str | None = None,
    session_calendar: Any = None,
    event_line: Any = None,
    memo: dict[tuple, StreamingNode] | None = None,
) -> StreamingFactorPlan:
    if not products or len(set(products)) != len(products):
        raise ValueError("streaming products must be non-empty and unique")
    if memo is None:
        memo = {}

    def compile_node(expr: FactorExpr) -> StreamingNode:
        key = expr._structural_key()
        if key in memo:
            return memo[key]
        if isinstance(expr, ConstExpr):
            if not np.isscalar(expr.value):
                raise UnsupportedStreamingFactor("streaming constants must be scalar")
            node: StreamingNode = ConstantNode(float(expr.value), len(products))
        elif isinstance(expr, ColumnRef):
            node = ColumnNode(expr.column.name, products)
        elif isinstance(expr, CategoryBoolRef):
            node = CategoryBoolNode(expr.category, expr.category_name, products)
        elif isinstance(expr, SignalAlign):
            if source_freq is None:
                raise UnsupportedStreamingFactor(
                    "streaming SignalAlign requires an explicit source frequency"
                )
            source = DataFreq(source_freq)
            target = DataFreq(expr.signal_freq)
            if source.value <= pd.Timedelta(0) or target.value <= pd.Timedelta(0):
                raise UnsupportedStreamingFactor(
                    "streaming SignalAlign frequencies must be positive"
                )
            if target.is_day_multiple():
                raise UnsupportedStreamingFactor(
                    "streaming daily SignalAlign requires a session-calendar close event"
                )
            ratio = target.value.total_seconds() / source.value.total_seconds()
            if ratio < 1 or not float(ratio).is_integer():
                raise UnsupportedStreamingFactor(
                    "streaming SignalAlign must be an integer multiple of source frequency"
                )
            if not isinstance(expr.basepoint, str) or expr.basepoint.lower() not in {"first", "last"}:
                raise UnsupportedStreamingFactor(
                    "streaming SignalAlign requires first/last basepoint"
                )
            node = SignalHoldNode(
                compile_node(expr.operands[0]),
                every_bars=int(ratio),
                width=len(products),
                reset_on_session_gap=bool(expr.end_session_skip),
                session_gap=pd.Timedelta(expr.end_session_gap),
            )
        elif isinstance(expr, BarSinceOp):
            scope = expr.scope
            if isinstance(scope, BarCountScope):
                scope = scope.resolve_for_streaming(source_freq, products)
            node = BarSinceNode(
                compile_node(expr.condition),
                scope=scope,
                select=expr.select,
                default=_streaming_bar_search_default(expr.operands[1], "bar_since default"),
                width=len(products),
                include_current=expr.include_current,
            )
        elif isinstance(expr, BarDistanceOp):
            scope = expr.scope
            if isinstance(scope, BarCountScope):
                scope = scope.resolve_for_streaming(source_freq, products)
            node = BarDistanceNode(
                compile_node(expr.value),
                compile_match_predicate(expr.condition, compile_node),
                scope=scope,
                select=expr.select,
                default=_streaming_bar_search_default(expr.operands[2], "bar_distance default"),
                width=len(products),
            )
        elif isinstance(expr, CompositeExpr):
            if expr.op not in _COMPOSITE_OPS:
                raise UnsupportedStreamingFactor(f"unsupported composite op: {expr.op}")
            node = CompositeNode(expr.op, tuple(compile_node(item) for item in expr.operands))
        elif isinstance(expr, RollingOp):
            if expr._trunc_start is not None or expr._trunc_end is not None:
                raise UnsupportedStreamingFactor("truncated rolling windows are not supported")
            if not isinstance(expr.window, ConstExpr):
                raise UnsupportedStreamingFactor("streaming windows must resolve to fixed bars")
            lookback_sessions = None
            event_ref = _event_ref_from_window(expr.window.value)
            wall_duration_ns = _wall_duration_ns(expr.window.value)
            if event_ref is not None:
                window = 1
            elif wall_duration_ns is not None:
                window = 1
            elif session_calendar is not None:
                try:
                    duration = pd.Timedelta(expr.window.value)
                except (TypeError, ValueError):
                    duration = None
                if duration is not None and duration >= pd.Timedelta("1D"):
                    ratio = duration / pd.Timedelta("1D")
                    if not np.isclose(ratio, round(ratio)):
                        raise UnsupportedStreamingFactor(
                            "session window must be an integer trading-day count"
                        )
                    lookback_sessions = int(round(ratio))
                    if expr.op not in {
                        "rolling_mean", "rolling_sum", "rolling_var",
                        "rolling_std", "rolling_min", "rolling_max",
                        "rolling_skew", "rolling_argmin", "rolling_argmax",
            "rolling_argmin_raw", "rolling_argmax_raw",
                        "rolling_median", "rolling_quantile", "rolling_rank", "rolling_mad",
                        "rolling_cov", "rolling_corr",
                    }:
                        raise UnsupportedStreamingFactor(
                            "session window has no verified Rust implementation"
                        )
                    window = 1
                else:
                    window = _resolve_window_bars(expr.window.value, source_freq)
            else:
                window = _resolve_window_bars(expr.window.value, source_freq)
            children = tuple(
                compile_node(item)
                for item in expr.operands[expr._data_start:expr._data_start + expr._n_data]
            )
            if event_ref is not None:
                resolver = _EventResolver(event_ref, event_line)
                if expr.op in {"rolling_cov", "rolling_corr"} and len(children) == 2:
                    node = RustIntervalPairNode(
                        expr.op, children, len(products), resolver,
                    )
                elif len(children) == 1:
                    node = RustIntervalNode(
                        expr.op, children[0], len(products), resolver,
                        quantile=getattr(expr, "quantile", None),
                    )
                else:
                    raise UnsupportedStreamingFactor(
                        "event window expects one operand or cov/corr pair"
                    )
            elif wall_duration_ns is not None:
                if expr.op in {"rolling_cov", "rolling_corr"} and len(children) == 2:
                    node = RustIntervalPairNode(
                        expr.op, children, len(products),
                        _WallWindowResolver(wall_duration_ns),
                    )
                elif len(children) == 1:
                    node = RustIntervalNode(
                        expr.op, children[0], len(products),
                        _WallWindowResolver(wall_duration_ns),
                        quantile=getattr(expr, "quantile", None),
                    )
                else:
                    raise UnsupportedStreamingFactor(
                        "wall window expects one operand or cov/corr pair"
                    )
            elif (
                session_calendar is not None
                and lookback_sessions is not None
                and expr.op in {"rolling_cov", "rolling_corr"}
                and len(children) == 2
            ):
                node = RustIntervalPairNode(
                    expr.op, children, len(products),
                    _SessionWindowResolver(session_calendar, lookback_sessions),
                )
            elif (
                session_calendar is not None
                and lookback_sessions is not None
                and expr.op in {
                    "rolling_mean", "rolling_sum", "rolling_var",
                    "rolling_std", "rolling_min", "rolling_max",
                    "rolling_skew", "rolling_argmin", "rolling_argmax",
            "rolling_argmin_raw", "rolling_argmax_raw",
                    "rolling_median", "rolling_quantile", "rolling_rank", "rolling_mad",
                }
            ):
                node = RustIntervalNode(
                    expr.op, children[0], len(products),
                    _SessionWindowResolver(session_calendar, lookback_sessions),
                    quantile=getattr(expr, "quantile", None),
                )
            elif (
                wall_duration_ns is None
                and lookback_sessions is None
                and len(children) == 1
                and expr.op in RustIntervalNode._OPS
            ):
                node = RustIntervalNode(
                    expr.op, children[0], len(products),
                    _BarWindowResolver(window),
                    quantile=getattr(expr, "quantile", None),
                )
            elif expr.op == "rolling_ema":
                if len(children) != 1:
                    raise UnsupportedStreamingFactor("rolling_ema expects one streaming operand")
                node = RustEmaNode(children[0], window, len(products))
            elif (
                wall_duration_ns is None
                and lookback_sessions is None
                and expr.op in {"rolling_cov", "rolling_corr"}
                and len(children) == 2
            ):
                node = RustIntervalPairNode(
                    expr.op, children, len(products),
                    _BarWindowResolver(window),
                )
            else:
                raise UnsupportedStreamingFactor(
                    f"rolling op has no interval-kernel implementation: {expr.op}"
                )
        elif isinstance(expr, GroupByScopeOp):
            op_name = expr.op
            operands = expr.operands
            data_operands = tuple(
                compile_node(item)
                for item in operands[expr._data_start:expr._data_start + expr._n_data]
            )
            # 数据操作数恒为一个；quantile 的 q 与截断上下界都在尾部
            if not data_operands:
                raise UnsupportedStreamingFactor("groupby_scope expects one data operand")
            quantile = None
            if op_name == "quantile":
                quantile = expr.quantile_value()
                if isinstance(quantile, ConstExpr):
                    quantile = quantile.value
                if isinstance(quantile, bool) or not isinstance(quantile, (int, float)):
                    raise UnsupportedStreamingFactor("streaming quantile must be a constant")
                quantile = float(quantile)
            rust_partition = False
            trunc_start = _resolve_truncation(expr.trunc_start)
            trunc_end = _resolve_truncation(expr.trunc_end)
            has_trunc = trunc_start is not None or trunc_end is not None
            if has_trunc:
                resolver = _RangeResolver(
                    expr.scope,
                    trunc_start if isinstance(trunc_start, int) else 0,
                    trunc_end if isinstance(trunc_end, int) else 0,
                    event_line, source_freq, products,
                )
                node = RustIntervalNode(
                    op_name, data_operands[0], len(products), resolver,
                    quantile=quantile,
                )
                rust_partition = True
            else:
                from tools.factors.expr.lookback_scope import (
                    BarCountScope, SessionScope, TradingDayScope,
                )
                if isinstance(expr.scope, BarCountScope):
                    resolver = _BarScopeResolver(expr.scope.resolved_count(
                        source_freq=source_freq, products=products,
                    ))
                elif event_line is not None:
                    from tools.factors.events import EventId, EventRef
                    if isinstance(expr.scope, TradingDayScope):
                        ref = EventRef(EventId.TRADING_DAY_START)
                    elif isinstance(expr.scope, SessionScope):
                        ref = EventRef(EventId.TRADING_SESSION_START)
                    else:
                        ref = None
                    resolver = _EventResolver(ref, event_line) if ref else None
                else:
                    resolver = None
                if resolver is None:
                    raise UnsupportedStreamingFactor(
                        "scope aggregation needs an event line or fixed bar count"
                    )
                node = RustIntervalNode(
                    op_name, data_operands[0], len(products), resolver,
                    quantile=quantile,
                )
                rust_partition = True
            if not rust_partition:
                raise UnsupportedStreamingFactor(
                    "scope aggregation requires the unified Rust kernel"
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
            if expr.op == "cs_residualize":
                children = tuple(compile_node(item) for item in expr.operands)
                node = ResidualizeNode(children, expr.exposure_count or 0)
                memo[key] = node
                return node
            if expr.op not in {"cs_rank", "cs_rank_masked", "cs_zscore", "cs_ordinal_rank_asc", "cs_ordinal_rank_desc", "cs_group_rank", "cs_group_zscore", "cs_group_demean"}:
                raise UnsupportedStreamingFactor(
                    f"unsupported cross-sectional op: {expr.op}"
                )
            if expr.op in {"cs_group_rank", "cs_group_zscore", "cs_group_demean"}:
                node = GroupCrossSectionalNode(
                    expr.op, (compile_node(expr.operand), compile_node(expr.right)), expr.category, products,
                )
            elif expr.op in {"cs_rank_masked", "cs_ordinal_rank_asc", "cs_ordinal_rank_desc"}:
                children = (compile_node(expr.operand), compile_node(expr.right))
                node = CrossSectionalNode(
                    expr.op, children, tuple(str(getattr(product, "name", product)) for product in products),
                )
            else:
                children = (compile_node(expr.operand),)
                node = CrossSectionalNode(
                    expr.op, children, tuple(str(getattr(product, "name", product)) for product in products),
                )
        elif isinstance(expr, TermStructureOp):
            near_rank, far_rank, depth, column_name = _term_structure_params(expr)
            node = TermStructureNode(
                expr.op,
                products,
                near_rank,
                far_rank,
                depth,
                column_name,
            )
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
        if isinstance(node, (RustIntervalNode, RustEmaNode)):
            from tools.factors.expr.window_semantics import NanPolicy
            if isinstance(expr, GroupByScopeOp):
                min_periods = expr.min_periods if expr.min_periods is not None else 1
            else:
                min_periods = getattr(expr, "min_periods", None)
                if min_periods is None:
                    from tools.factors.expr.window_semantics import default_min_periods
                    window_value = locals().get("window", 1)
                    min_periods = default_min_periods(
                        getattr(expr, "op", ""),
                        window_value if isinstance(window_value, int) else 1,
                    )
            if isinstance(min_periods, ConstExpr):
                min_periods = min_periods.value
            elif hasattr(min_periods, "param"):
                min_periods = min_periods.param.default_value
            policy = getattr(expr, "nan_policy", NanPolicy.PROPAGATE)
            node.configure(int(min_periods), policy is NanPolicy.PROPAGATE)
        memo[key] = node
        return node

    root = compile_node(expression)
    lookback_contract = infer_lookback_contract(
        expression,
        resolve_window=lambda window_expr: _resolve_streaming_expr_window(
            window_expr,
            source_freq,
        ),
        zero=0,
        add=add,
    )
    return StreamingFactorPlan(
        expression, products, root, lookback_contract, tuple(memo.keys()),
    )


def compile_incremental_factor(
    factor_alias: str,
    expression: FactorExpr,
    products: tuple[Any, ...],
    *,
    source_freq: DataFreq | str | None = None,
    session_calendar: Any = None,
    event_line: Any = None,
) -> SingleFactorIncrementalExecutor:
    """Compile one author-facing FactorExpr into a run-scoped executor."""

    multi = compile_incremental_factors(
        {factor_alias: expression}, products, source_freq=source_freq,
        session_calendar=session_calendar, event_line=event_line,
    )
    return SingleFactorIncrementalExecutor(factor_alias, multi)


def compile_incremental_factors(
    expressions: dict[str, FactorExpr],
    products: tuple[Any, ...],
    *,
    source_freq: DataFreq | str | None = None,
    session_calendar: Any = None,
    event_line: Any = None,
):
    """Compile several factors into one shared incremental DAG."""
    if not expressions:
        raise ValueError("incremental factor set must be non-empty")
    from tools.factors.expr.streaming.rust_incremental import (
        UnsupportedByRustPlan, compile_rust_incremental,
    )
    try:
        return compile_rust_incremental(expressions, products, source_freq=source_freq)
    except (UnsupportedByRustPlan, AttributeError, KeyError, TypeError, ValueError):
        pass
    memo: dict[tuple, StreamingNode] = {}
    plans = []
    aliases = []
    roots = []
    for alias, expression in expressions.items():
        plan = compile_streaming_factor(
            expression, products, source_freq=source_freq,
            session_calendar=session_calendar, event_line=event_line,
            memo=memo,
        )
        aliases.append(alias)
        plans.append(plan)
        roots.append(plan._root)
    multi = MultiStreamingPlan(aliases, products, roots, plans)
    return MultiStreamingIncrementalExecutor(multi)


def _normalize_bar_fields(fields: Any) -> dict[str, float]:
    if isinstance(fields, NormalizedBarFields):
        return fields
    if isinstance(fields, Mapping):
        # FactorStepAdapter and the native market snapshot already provide a
        # string-keyed numeric mapping.  It is consumed read-only by
        # ColumnNode, so avoid rebuilding the same dictionary on every bar.
        if all(
            isinstance(name, str)
            and isinstance(value, (int, float, np.integer, np.floating))
            for name, value in fields.items()
        ):
            return fields  # type: ignore[return-value]
        return {str(name): float(value) for name, value in fields.items()}
    value = float(fields)
    return {
        "OPEN": value,
        "HIGH": value,
        "LOW": value,
        "CLOSE": value,
    }


def _streaming_scalar(expr: FactorExpr, label: str) -> float:
    if not isinstance(expr, ConstExpr) or not np.isscalar(expr.value):
        raise UnsupportedStreamingFactor(f"streaming {label} must resolve to a scalar constant")
    return float(expr.value)


def _streaming_bar_search_default(expr: FactorExpr, label: str) -> float | None:
    if type(expr).__name__ == "ScopeLengthDefault":
        return None
    return _streaming_scalar(expr, label)


def _normalize_term_curve(curve: Any) -> pd.DataFrame:
    return normalize_term_curve(curve)


def _term_structure_params(expr: TermStructureOp) -> tuple[int, int, int, str]:
    if expr.op in TermStructureOp._PAIR_OPS:
        if len(expr.operands) != 3:
            raise UnsupportedStreamingFactor(f"{expr.op} expects near_rank, far_rank, and column operands")
        near_rank = _term_structure_int_operand(expr.operands[0], "near_rank")
        far_rank = _term_structure_int_operand(expr.operands[1], "far_rank")
        column = _term_structure_column_operand(expr.operands[2])
        return near_rank, far_rank, 0, column
    if expr.op in TermStructureOp._DEPTH_OPS:
        if len(expr.operands) != 2:
            raise UnsupportedStreamingFactor(f"{expr.op} expects depth and column operands")
        depth = _term_structure_int_operand(expr.operands[0], "depth")
        column = _term_structure_column_operand(expr.operands[1])
        return 0, 1, depth, column
    if expr.op in TermStructureOp._RANK_OPS:
        if len(expr.operands) != 2:
            raise UnsupportedStreamingFactor(f"{expr.op} expects rank and column operands")
        rank = _term_structure_int_operand(expr.operands[0], "rank")
        column = _term_structure_column_operand(expr.operands[1])
        return rank, 0, 0, column
    raise UnsupportedStreamingFactor(f"unsupported term structure op: {expr.op}")


def _term_structure_int_operand(expr: FactorExpr, name: str) -> int:
    if not isinstance(expr, ConstExpr) or not np.isscalar(expr.value):
        raise UnsupportedStreamingFactor(f"term structure {name} must be a scalar constant")
    value = int(expr.value)
    if value < 0:
        raise UnsupportedStreamingFactor(f"term structure {name} must be non-negative")
    return value


def _term_structure_column_operand(expr: FactorExpr) -> str:
    if isinstance(expr, (ColumnRef, ConstExpr)):
        return TermStructureOp._column_name(expr)
    raise UnsupportedStreamingFactor("term structure column operand must be a ColumnRef or DataColumn constant")


def resolve_trading_day_window(
    value: object,
    *,
    calendar_window: Any,
    current_session: int,
) -> int:
    """Resolve a session lookback (e.g. ``250d``) to its minute-bar count.

    The count is variable: it is the sum of authoritative session bar counts
    over the requested trading-day lookback.  It must be recomputed at every
    session boundary, never approximated as a fixed multiple of calendar days.
    """
    if isinstance(value, str):
        duration = pd.Timedelta(value)
    elif isinstance(value, pd.Timedelta):
        duration = value
    else:
        raise UnsupportedStreamingFactor("trading-day windows must be durations")
    if duration < pd.Timedelta("1D"):
        raise UnsupportedStreamingFactor("trading-day window must span at least one day")
    ratio = duration / pd.Timedelta("1D")
    if not np.isfinite(ratio) or not np.isclose(ratio, round(ratio)):
        raise UnsupportedStreamingFactor("trading-day window must be an integer day count")
    return calendar_window.window_size(current_session, int(round(ratio)))


def _event_ref_from_window(value: object):
    """Parse explicit ``event:<id>`` window syntax into an EventRef."""
    if not isinstance(value, str) or not value.startswith("event:"):
        return None
    from tools.factors.events import EventId, EventRef, Occurrence

    parts = value.split(":")
    if len(parts) == 3 and parts[1] in {item.value for item in Occurrence}:
        return EventRef(EventId(parts[2]), Occurrence(parts[1]))
    return EventRef(EventId(parts[1]))


def _wall_duration_ns(value: object) -> int | None:
    """Return nanoseconds for the explicit ``wall:`` window syntax."""
    if not isinstance(value, str) or not value.startswith("wall:"):
        return None
    duration = pd.Timedelta(value[5:])
    if duration <= pd.Timedelta(0):
        raise UnsupportedStreamingFactor("wall window must be positive")
    return int(duration.value)


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
        bars = round(ratio)
    else:
        raise UnsupportedStreamingFactor("streaming windows must resolve to fixed bars")
    if bars <= 0:
        raise UnsupportedStreamingFactor("streaming window must be positive")
    return bars


def _resolve_streaming_expr_window(
    window_expr: Any,
    source_freq: DataFreq | str | None,
) -> int | None:
    if not isinstance(window_expr, ConstExpr):
        raise UnsupportedStreamingFactor("streaming windows must resolve to fixed bars")
    return _resolve_window_bars(window_expr.value, source_freq)


_COMPOSITE_OPS = POINTWISE_OPS


def _apply_composite(op: str, values: list[np.ndarray]) -> np.ndarray:
    try:
        return np.asarray(apply_pointwise(op, values))
    except ValueError as exc:
        raise UnsupportedStreamingFactor(f"unsupported composite op: {op}") from exc
