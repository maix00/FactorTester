"""Compile existing FactorExpr graphs into incremental event executors."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from operator import add
from typing import TYPE_CHECKING, Any, Mapping, Protocol

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
from tools.factors.expr.lookback_scope import BarCountScope
from tools.factors.expr.pointwise import POINTWISE_OPS, apply_pointwise
from tools.factors.expr.term_structure_math import (
    evaluate_term_curve,
    normalize_term_curve,
)
from tools.factors.lookback import LookbackContract, infer_lookback_contract
from tools.products.AdjustableTermStructure import (
    TERM_RANK_COL,
)

from .bar_search import BarDistanceNode, BarSinceNode, compile_match_predicate
from .cross_sectional_kernels import ordinal_rank, rank_percent, zscore
from .cross_sectional_residual import ResidualizeNode
from .group_cross_sectional import GroupCrossSectionalNode
from .rolling_statistics import ROLLING_STATISTICS, RollingStatisticsNode
from tools.factors.expr.groupby_scope import GroupByScopeOp

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
        self._width = width
        self._fast = len(children) == 1 and op in {
            # The sum/mean state is a clear win for all window sizes.  A
            # Python monotonic deque for min/max is slower than NumPy's
            # vectorized scan for the small windows common in live factors, so
            # those retain the generic kernel until a width-aware deque is
            # available.
            "rolling_mean", "rolling_sum",
        }
        if self._fast:
            self._ring = np.full((window, width), np.nan, dtype=float)
            self._ring_cursor = 0
            self._ring_length = 0
            self._sum = np.zeros(width, dtype=float)
            self._count = np.zeros(width, dtype=np.int64)
            self._histories: list[deque[np.ndarray]] = []
        else:
            self._histories = [deque(maxlen=window) for _ in children]

    def update(self, market: MarketSlice, cache: dict[int, np.ndarray]) -> np.ndarray:
        key = id(self)
        if key in cache:
            return cache[key]
        if self._fast:
            value = self.children[0].update(market, cache)
            result = self._update_fast(np.asarray(value, dtype=float))
            cache[key] = result
            return result
        for history, child in zip(self._histories, self.children, strict=True):
            history.append(child.update(market, cache).copy())
        result = self._aggregate()
        cache[key] = result
        return result

    def _update_fast(self, value: np.ndarray) -> np.ndarray:
        if value.shape != (self._width,):
            raise ValueError("streaming rolling input width changed unexpectedly")
        finite = np.isfinite(value)
        if self._ring_length == self.window:
            old = self._ring[self._ring_cursor]
            old_finite = np.isfinite(old)
            self._sum[old_finite] -= old[old_finite]
            self._count[old_finite] -= 1
        # Keep the original values in the ring; ``isfinite`` below gives the
        # same NaN/Inf-as-missing semantics as pandas without allocating a
        # cleaned copy on every bar.
        self._ring[self._ring_cursor] = value
        self._sum[finite] += value[finite]
        self._count[finite] += 1
        self._ring_cursor = (self._ring_cursor + 1) % self.window
        self._ring_length = min(self.window, self._ring_length + 1)

        result = np.full(self._width, np.nan, dtype=float)
        minimum = max(1, self.window // 2) if self.op == "rolling_mean" else 1
        ready = self._count >= minimum
        if self.op == "rolling_mean":
            result[ready] = self._sum[ready] / self._count[ready]
        elif self.op == "rolling_sum":
            result[ready] = self._sum[ready]
        return result

    def _aggregate(self) -> np.ndarray:
        histories = [np.asarray(history, dtype=float) for history in self._histories]
        if not histories or len(histories[0]) == 0:
            return np.full(self._width, np.nan, dtype=float)
        values = histories[0]
        finite = np.isfinite(values)
        count = finite.sum(axis=0)
        min_periods = 1 if self.op in {
            "rolling_min", "rolling_max", "rolling_sum",
            "rolling_argmax", "rolling_argmin",
            "rolling_argmax_raw", "rolling_argmin_raw",
        } else max(1, self.window // 2)
        result = np.full(self._width, np.nan, dtype=float)
        if self.op == "rolling_mean":
            ready = count >= min_periods
            result[ready] = np.nansum(values, axis=0)[ready] / count[ready]
            return result
        if self.op == "rolling_std":
            ready = (count >= min_periods) & (count > 1)
            mean = np.divide(
                np.nansum(values, axis=0), count,
                out=np.zeros(self._width, dtype=float), where=count > 0,
            )
            centered = np.where(finite, values - mean, 0.0)
            result[ready] = np.sqrt(np.sum(centered * centered, axis=0)[ready] / (count[ready] - 1))
            return result
        if self.op == "rolling_var":
            ready = (count >= min_periods) & (count > 1)
            mean = np.divide(
                np.nansum(values, axis=0), count,
                out=np.zeros(self._width, dtype=float), where=count > 0,
            )
            centered = np.where(finite, values - mean, 0.0)
            result[ready] = np.sum(centered * centered, axis=0)[ready] / (count[ready] - 1)
            return result
        if self.op == "rolling_min":
            safe = np.where(finite, values, np.inf)
            result[count > 0] = np.min(safe, axis=0)[count > 0]
            return result
        if self.op == "rolling_max":
            safe = np.where(finite, values, -np.inf)
            result[count > 0] = np.max(safe, axis=0)[count > 0]
            return result
        if self.op == "rolling_sum":
            ready = count >= min_periods
            result[ready] = np.nansum(values, axis=0)[ready]
            return result
        if self.op == "rolling_skew":
            mean = np.divide(
                np.nansum(values, axis=0), count,
                out=np.zeros(self._width, dtype=float), where=count > 0,
            )
            centered = np.where(finite, values - mean, 0.0)
            second = np.sum(centered * centered, axis=0) / np.maximum(count, 1)
            third = np.sum(centered * centered * centered, axis=0) / np.maximum(count, 1)
            valid = (count >= min_periods) & (count >= 3) & (second > 0.0)
            with np.errstate(divide="ignore", invalid="ignore"):
                skew = third / np.power(second, 1.5)
            result[valid] = np.sqrt(count[valid] * (count[valid] - 1)) / (count[valid] - 2) * skew[valid]
            return result
        if self.op in {"rolling_corr", "rolling_cov"}:
            if self.window <= 1 or len(values) < self.window:
                return np.full(self._width, np.nan, dtype=float)
            right = histories[1]
            pair_finite = np.isfinite(values) & np.isfinite(right)
            pair_count = pair_finite.sum(axis=0)
            # pandas' rolling corr/cov default min_periods=window: a single
            # missing value invalidates the current full window.
            ready = pair_count >= self.window
            if not ready.any():
                return result
            left_mean = np.mean(values, axis=0)
            right_mean = np.mean(right, axis=0)
            left_centered = values - left_mean
            right_centered = right - right_mean
            covariance = np.sum(left_centered * right_centered, axis=0) / (self.window - 1)
            if self.op == "rolling_cov":
                result[ready] = covariance[ready]
            else:
                left_std = np.sqrt(np.sum(left_centered * left_centered, axis=0) / (self.window - 1))
                right_std = np.sqrt(np.sum(right_centered * right_centered, axis=0) / (self.window - 1))
                valid = ready & (left_std > 0.0) & (right_std > 0.0)
                result[valid] = covariance[valid] / (left_std[valid] * right_std[valid])
            return result
        if self.op.startswith("rolling_arg"):
            if self.window > 1 and len(values) < self.window:
                return result
            is_max = "argmax" in self.op
            normalize = not self.op.endswith("_raw")
            for column in range(self._width):
                column_values = values[:, column]
                valid = np.flatnonzero(np.isfinite(column_values))
                if valid.size == 0:
                    # Match _rolling_argmaxmin: a full all-NaN window gets a
                    # neutral position (the pre-window rows remain NaN).
                    result[column] = 0.0
                    continue
                if valid.size < min_periods:
                    continue
                extreme = np.nanmax(column_values) if is_max else np.nanmin(column_values)
                # Batch sliding_window_view reverses each window, so ties use
                # the most recent occurrence rather than the oldest one.
                position = np.flatnonzero(np.isfinite(column_values) & (column_values == extreme))[-1]
                result[column] = position / max(1, self.window - 1) if normalize else position
            return result
        raise UnsupportedStreamingFactor(f"unsupported rolling op: {self.op}")


class ExpandingEwmNode:
    def __init__(self, child: StreamingNode, span: int, width: int) -> None:
        self.child = child
        self.span = span
        self._width = width
        self._minimum = max(1, span // 2)
        # pandas' default rolling EMA is adjust=True, ignore_na=False.  Keep
        # the adjusted numerator/denominator recurrence instead of rebuilding
        # an ever-growing DataFrame on every bar (the old implementation was
        # O(T²) in the number of bars).
        self._decay = 1.0 - (2.0 / (span + 1.0))
        self._numerator = np.zeros(width, dtype=float)
        self._denominator = np.zeros(width, dtype=float)
        self._observations = np.zeros(width, dtype=np.int64)
        self._last_result = np.full(width, np.nan, dtype=float)

    def update(self, market: MarketSlice, cache: dict[int, np.ndarray]) -> np.ndarray:
        key = id(self)
        if key in cache:
            return cache[key]
        value = np.asarray(self.child.update(market, cache), dtype=float)
        finite = np.isfinite(value)
        self._numerator *= self._decay
        self._denominator *= self._decay
        self._numerator[finite] += value[finite]
        self._denominator[finite] += 1.0
        self._observations[finite] += 1
        result = np.full(self._width, np.nan, dtype=float)
        ready = (self._observations >= self._minimum) & (self._denominator > 0.0)
        result[ready] = self._numerator[ready] / self._denominator[ready]
        # A missing observation does not change the visible adjusted mean.
        # Keep the previous quotient exactly (rather than dividing two
        # repeatedly decayed floats and accumulating gap-length roundoff).
        unchanged = (~finite) & (self._observations >= self._minimum)
        result[unchanged] = self._last_result[unchanged]
        # Very long missing runs can underflow both adjusted state terms.  In
        # that case pandas keeps the last EWM value visible; retaining the
        # output separately also avoids turning a legitimate long gap into a
        # spurious NaN.  A later finite value naturally restarts the state.
        fallback = (self._observations >= self._minimum) & ~ready & ~unchanged
        result[fallback] = self._last_result[fallback]
        observed = np.isfinite(result)
        self._last_result[observed] = result[observed]
        cache[key] = result
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


class GroupScopeNode:
    """Streaming kernel for ``groupby_scope`` (scope-partitioned aggregation).

    State is **O(1) per product** for every decomposable aggregation (count,
    sum, sum-of-squares, running extreme, running arg-extreme) and the partition
    boundary is read off the market slice, so no O(K) window buffer is needed:
    memory does not grow with the partition length.  ``median``/``quantile`` are
    the only ops carrying a partition-sized order-statistic list, which is
    unavoidable for an order statistic.
    """

    def __init__(
        self,
        op: str,
        child: StreamingNode,
        scope: Any,
        width: int,
        *,
        quantile: float | None = None,
        trunc_start: int = 0,
        trunc_end: int | None = None,
        products: tuple[Any, ...] | None = None,
        source_freq: Any | None = None,
        vectorized: bool | None = None,
    ) -> None:
        from tools.factors.expr.groupby_scope_eval import _MIN_PERIODS
        from tools.factors.expr.lookback_scope import (
            BarCountScope,
            SessionScope,
            TradingDayScope,
        )

        self.op = op
        self.child = child
        self.scope = scope
        self.width = width
        self.quantile = quantile
        self.trunc_start = max(0, int(trunc_start or 0))
        self.trunc_end = None if trunc_end is None else max(0, int(trunc_end))
        self.products = tuple(products) if products is not None else tuple(range(width))
        self._min_periods = _MIN_PERIODS
        self._bar_scope = BarCountScope
        self._day_scope = TradingDayScope
        self._session_scope = SessionScope
        self._bar_count = 0
        if isinstance(scope, BarCountScope):
            # 与 rolling 同口径解析：整数根数直接可用，时长按源频率折算成固定根数
            try:
                self._bar_count = int(
                    scope.resolved_count(source_freq=source_freq, products=self.products)
                )
            except (TypeError, ValueError) as error:
                raise UnsupportedStreamingFactor(
                    f"streaming groupby_scope(scope_bars) needs a fixed bar count: {error}"
                ) from error
            if self._bar_count < 1:
                raise UnsupportedStreamingFactor("scope_bars(K) requires K >= 1")
        elif not isinstance(scope, (TradingDayScope, SessionScope)):
            raise UnsupportedStreamingFactor(
                f"unsupported groupby_scope scope for streaming: {scope!r}"
            )
        self._key: np.ndarray = np.empty(width, dtype=object)
        self._opened = np.zeros(width, dtype=bool)
        self._raw = np.zeros(width, dtype=np.int64)
        self._count = np.zeros(width, dtype=np.int64)
        self._sum = np.zeros(width, dtype=float)
        # Welford 在线均值/二阶矩：O(1) 状态且避免 sum-of-squares 的抵消误差
        self._mean = np.zeros(width, dtype=float)
        self._m2 = np.zeros(width, dtype=float)
        self._min = np.full(width, np.inf, dtype=float)
        self._max = np.full(width, -np.inf, dtype=float)
        self._best_raw = np.full(width, -1, dtype=np.int64)
        self._best_value = np.full(width, np.nan, dtype=float)
        self._frozen = np.zeros(width, dtype=bool)
        self._frozen_value = np.full(width, np.nan, dtype=float)
        self._sorted: list[list[float]] = [[] for _ in range(width)]
        self._track_sum = op == "sum"
        self._track_moments = op in ("mean", "var", "std")
        self._track_extremes = op in ("min", "max")
        self._track_order = op in ("median", "quantile")
        self._last_ts: list[Any] = [None] * width
        self._session_id = np.zeros(width, dtype=np.int64)
        self._bar_ordinal = np.zeros(width, dtype=np.int64)
        # 跨产品向量化路径在宽度大时明显更快（每 bar 恒定开销），
        # 逐产品路径在宽度小（真实研究的 T/TL 两个品种）时更快。
        # 阈值取自实测：2 产品 0.0146 vs 0.0214 ms/bar，20 产品 0.0400 vs 0.0214 ms/bar。
        self._VECTOR_MIN_WIDTH = 8
        self._vector = (width >= self._VECTOR_MIN_WIDTH) if vectorized is None else bool(vectorized)
        self._last_ts_ns = np.zeros(width, dtype=np.int64)

    # -- partition bookkeeping -------------------------------------------
    def _partition_of(
        self, index: int, timestamp: Any, trading_day: Any, observed: bool,
    ) -> Any:
        scope = self.scope
        if isinstance(scope, self._bar_scope):
            if not observed:
                return self._key[index] if self._opened[index] else None
            ordinal = int(self._bar_ordinal[index])
            self._bar_ordinal[index] = ordinal + 1
            return ordinal // self._bar_count
        if isinstance(scope, self._day_scope):
            if trading_day is None:
                raise UnsupportedStreamingFactor(
                    "groupby_scope(trading_day) needs the trading day on the market slice; "
                    "it is not derived from the calendar date"
                )
            return trading_day
        if not observed:
            return self._key[index] if self._opened[index] else None
        last = self._last_ts[index]
        if last is not None and timestamp - last >= pd.Timedelta(scope.gap):
            self._session_id[index] += 1
        self._last_ts[index] = timestamp
        return int(self._session_id[index])

    def _reset(self, index: int, partition: Any) -> None:
        self._key[index] = partition
        self._opened[index] = True
        self._raw[index] = 0
        self._count[index] = 0
        self._sum[index] = 0.0
        self._mean[index] = 0.0
        self._m2[index] = 0.0
        self._min[index] = np.inf
        self._max[index] = -np.inf
        self._best_raw[index] = -1
        self._best_value[index] = np.nan
        self._frozen[index] = False
        self._frozen_value[index] = np.nan
        self._sorted[index] = []

    # -- per-bar evaluation ----------------------------------------------
    def update(self, market: MarketSlice, cache: dict[int, np.ndarray]) -> np.ndarray:
        key = id(self)
        if key in cache:
            return cache[key]
        values = np.asarray(self.child.update(market, cache), dtype=float)
        timestamp = getattr(market, "timestamp", None)
        trading_day = getattr(market, "trading_day", None)
        if timestamp is not None:
            timestamp = pd.Timestamp(timestamp)
        if isinstance(self.scope, (self._day_scope, self._session_scope)):
            if timestamp is None:
                raise UnsupportedStreamingFactor(
                    "groupby_scope needs bar timestamps; the market slice carries none"
                )
            # 交易日必须由权威来源给出（面板索引的 DAY1 层／运行时的 trading_day），
            # 不能由时间戳日历日推出：夜盘 bar 归属的是下一个交易日。
            if trading_day is None and isinstance(self.scope, self._day_scope):
                raise UnsupportedStreamingFactor(
                    "groupby_scope(trading_day) needs the trading day on the market slice; "
                    "it is not derived from the calendar date"
                )
        elif trading_day is not None:
            trading_day = pd.Timestamp(trading_day)
        if self._vector:
            output = self._update_vector(values, timestamp, trading_day)
        else:
            output = np.full(self.width, np.nan, dtype=float)
            for index in range(self.width):
                observed = index < values.shape[0] and not np.isnan(values[index])
                partition = self._partition_of(index, timestamp, trading_day, observed)
                if partition is not None and (
                    not self._opened[index] or partition != self._key[index]
                ):
                    self._reset(index, partition)
                if observed:
                    output[index] = self._consume(index, float(values[index]))
        cache[key] = output
        return output

    def _consume(self, index: int, value: float) -> float:
        raw = int(self._raw[index])
        self._raw[index] = raw + 1
        if raw < self.trunc_start:
            return np.nan
        self._count[index] += 1
        # 只维护当前算子真正需要的状态，避免每根做无用的浮点运算
        if self._track_sum:
            self._sum[index] += value
        if self._track_moments:
            count = int(self._count[index])
            delta = value - self._mean[index]
            self._mean[index] += delta / count
            self._m2[index] += delta * (value - self._mean[index])
        if self._track_extremes:
            if value < self._min[index]:
                self._min[index] = value
            if value > self._max[index]:
                self._max[index] = value
        if self._track_order:
            insort(self._sorted[index], value)
        if self.op in ("argmax", "argmin"):
            if self.trunc_end is None or raw <= self.trunc_end:
                best = int(self._best_raw[index])
                better = (
                    value > self._best_value[index] if self.op == "argmax"
                    else value < self._best_value[index]
                )
                if best < 0 or np.isnan(self._best_value[index]) or better:
                    self._best_raw[index] = raw
                    self._best_value[index] = value
            span = raw - self.trunc_start
            if span <= 0:
                return 0.0
            best = int(self._best_raw[index])
            return np.nan if best < 0 else (raw - best) / span
        if (
            self.trunc_end is not None
            and raw > self.trunc_end
            and self._frozen[index]
        ):
            return float(self._frozen_value[index])
        result = self._value(index, raw)
        if self.trunc_end is not None and raw == self.trunc_end:
            self._frozen[index] = True
            self._frozen_value[index] = result
        return result

    # -- 跨产品向量化路径（与 _consume 同一语义，宽度大时每 bar 恒定开销）---
    def _partition_ids_vector(
        self, timestamp: Any, trading_day: Any, observed: np.ndarray,
    ) -> np.ndarray:
        scope = self.scope
        if isinstance(scope, self._bar_scope):
            ids = self._bar_ordinal // self._bar_count
            self._bar_ordinal += observed
            return ids
        if isinstance(scope, self._day_scope):
            if trading_day is None:
                raise UnsupportedStreamingFactor(
                    "groupby_scope(trading_day) needs a trading day on the market slice"
                )
            stamp = np.datetime64(pd.Timestamp(trading_day), "ns").astype("int64")
            return np.full(self.width, stamp, dtype=np.int64)
        stamp = np.datetime64(pd.Timestamp(timestamp), "ns").astype("int64")
        gap = int(pd.Timedelta(scope.gap).value)
        started = observed & (self._last_ts_ns > 0) & ((stamp - self._last_ts_ns) >= gap)
        self._session_id += started
        self._last_ts_ns = np.where(observed, stamp, self._last_ts_ns)
        return self._session_id

    def _update_vector(
        self, values: np.ndarray, timestamp: Any, trading_day: Any,
    ) -> np.ndarray:
        observed = np.isfinite(values)
        if values.shape[0] != self.width:
            extra = np.zeros(self.width - values.shape[0], dtype=bool)
            observed = np.r_[observed, extra]
        ids = self._partition_ids_vector(timestamp, trading_day, observed)
        reset = observed & (~self._opened | (ids != self._key))
        if reset.any():
            index = np.flatnonzero(reset)
            self._key[index] = ids[index]
            self._opened[index] = True
            self._raw[index] = 0
            self._count[index] = 0
            self._sum[index] = 0.0
            self._mean[index] = 0.0
            self._m2[index] = 0.0
            self._min[index] = np.inf
            self._max[index] = -np.inf
            self._best_raw[index] = -1
            self._best_value[index] = np.nan
            self._frozen[index] = False
            self._frozen_value[index] = np.nan
            for position in index:
                self._sorted[position] = []
        position = self._raw.copy()
        kept = observed & (position >= self.trunc_start)
        if self._track_sum:
            self._sum += np.where(kept, values, 0.0)
        if self._track_moments:
            new_count = self._count + kept
            delta = values - self._mean
            safe = np.where(new_count > 0, new_count, 1)
            self._mean = np.where(kept, self._mean + delta / safe, self._mean)
            self._m2 = np.where(kept, self._m2 + delta * (values - self._mean), self._m2)
        if self._track_extremes:
            self._min = np.where(kept, np.minimum(self._min, values), self._min)
            self._max = np.where(kept, np.maximum(self._max, values), self._max)
        if self._track_order:
            for index_position in np.flatnonzero(kept):
                insort(self._sorted[index_position], float(values[index_position]))
        if self.op in ("argmax", "argmin"):
            advancing = kept if self.trunc_end is None else kept & (position <= self.trunc_end)
            current = self._best_value
            if self.op == "argmax":
                better = values > np.where(np.isnan(current), -np.inf, current)
            else:
                better = values < np.where(np.isnan(current), np.inf, current)
            take = advancing & ((self._best_raw < 0) | np.isnan(current) | better)
            self._best_raw = np.where(take, position, self._best_raw)
            self._best_value = np.where(take, values, self._best_value)
        self._count += kept
        self._raw += observed
        result = self._values_vector(position)
        if self.trunc_end is not None and self.op not in ("argmax", "argmin"):
            freeze_now = kept & (position == self.trunc_end)
            if freeze_now.any():
                self._frozen |= freeze_now
                self._frozen_value = np.where(freeze_now, result, self._frozen_value)
            after = observed & (position > self.trunc_end) & self._frozen
            result = np.where(after, self._frozen_value, result)
        return np.where(observed, result, np.nan)

    def _values_vector(self, position: np.ndarray) -> np.ndarray:
        op = self.op
        count = self._count
        output = np.full(self.width, np.nan, dtype=float)
        if op in ("median", "quantile"):
            for index in range(self.width):
                output[index] = self._order_statistic(index)
            return output
        minimum = self._minimum()
        if op in ("sum", "mean"):
            mask = count >= max(minimum, 1)
            source = self._sum if op == "sum" else self._mean
            output[mask] = source[mask]
        elif op in ("var", "std"):
            mask = count >= max(minimum, 2)
            variance = np.maximum(self._m2 / np.maximum(count - 1, 1), 0.0)
            output[mask] = np.sqrt(variance[mask]) if op == "std" else variance[mask]
        elif op in ("min", "max"):
            mask = count >= max(minimum, 1)
            source = self._min if op == "min" else self._max
            output[mask] = source[mask]
        elif op in ("argmax", "argmin"):
            span = position - self.trunc_start
            valid = (self._best_raw >= 0) & (span >= 0)
            with np.errstate(invalid="ignore", divide="ignore"):
                age = (position - self._best_raw) / np.maximum(span, 1)
            positive = valid & (span > 0)
            output[positive] = age[positive]
            output[valid & (span == 0)] = 0.0
        return output


    def _minimum(self) -> int:
        floor = int(self._min_periods.get(self.op, 1))
        if self.trunc_end is None:
            return floor
        return min(floor, max(1, self.trunc_end - self.trunc_start + 1))

    def _value(self, index: int, raw: int) -> float:
        op = self.op
        count = int(self._count[index])
        if count < self._minimum():
            return np.nan
        if op == "sum":
            return float(self._sum[index])
        if op == "mean":
            return float(self._mean[index])
        if op in ("var", "std"):
            if count < 2:
                return np.nan
            variance = max(0.0, float(self._m2[index] / (count - 1)))
            return float(np.sqrt(variance)) if op == "std" else variance
        if op == "min":
            return float(self._min[index])
        if op == "max":
            return float(self._max[index])
        if op in ("median", "quantile"):
            return self._order_statistic(index)
        raise UnsupportedStreamingFactor(f"unsupported groupby_scope op: {op}")

    def _order_statistic(self, index: int) -> float:
        values = self._sorted[index]
        size = len(values)
        if size == 0 or size < self._minimum():
            return np.nan
        if self.op == "median":
            if size % 2:
                return float(values[size // 2])
            return 0.5 * (values[size // 2 - 1] + values[size // 2])
        q = 0.5 if self.quantile is None else float(self.quantile)
        position = q * (size - 1)
        lower = int(np.floor(position))
        upper = int(np.ceil(position))
        if lower == upper:
            return float(values[lower])
        return float(values[lower] + (values[upper] - values[lower]) * (position - lower))


class StreamingFactorPlan:
    def __init__(
        self,
        expression: FactorExpr,
        products: tuple[Any, ...],
        root: StreamingNode,
        lookback_contract: LookbackContract | None = None,
    ) -> None:
        self.expression = expression
        self.products = products
        self._root = root
        self.lookback_contract = lookback_contract

    def update(self, timestamp: pd.Timestamp, market: MarketSlice) -> dict[str, float]:
        if set(market.prices) != set(self.products):
            raise ValueError("streaming factor products do not match the market slice")
        values = self._root.update(_with_timestamp(market, timestamp), {})
        return dict(zip(self.products, values, strict=True))


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


class IncrementalFactorExecutor:
    """Run-scoped stateful executor produced from a FactorExpr graph."""

    def __init__(self, factor_alias: str, plan: StreamingFactorPlan) -> None:
        if not factor_alias:
            raise ValueError("incremental executor requires a factor alias")
        self.factor_alias = factor_alias
        self._plan = plan
        self._latest: dict[Any, float] = {}

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
        )
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
            window = _resolve_window_bars(expr.window.value, source_freq)
            children = tuple(
                compile_node(item)
                for item in expr.operands[expr._data_start:expr._data_start + expr._n_data]
            )
            if expr.op in ROLLING_STATISTICS:
                if len(children) != 1:
                    raise UnsupportedStreamingFactor(
                        f"{expr.op} expects one streaming operand"
                    )
                node = RollingStatisticsNode(
                    expr.op,
                    children[0],
                    window,
                    len(products),
                    quantile=expr.quantile,
                )
            elif expr.op == "rolling_ema":
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
        elif isinstance(expr, GroupByScopeOp):
            from tools.factors.expr.groupby_scope import GroupByScopeOp as _GroupByScopeOp

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
            node = GroupScopeNode(
                op_name,
                data_operands[0],
                expr.scope,
                len(products),
                quantile=quantile,
                trunc_start=_resolve_truncation(expr.trunc_start),
                trunc_end=_resolve_truncation(expr.trunc_end),
                products=products,
                source_freq=source_freq,
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
    return StreamingFactorPlan(expression, products, root, lookback_contract)


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
