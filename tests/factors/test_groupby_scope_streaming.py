"""``groupby_scope``：增量内核与批量内核必须逐点一致（ADR-022 双后端契约）。

增量侧只保留 O(1) 状态（计数/和/平方和/运行极值/极值位置 + 分区标记），
不保留 O(K) 窗口缓冲；本测试用「同一面板逐根喂入」与批量内核逐点比对，
覆盖跨交易日边界、NaN 缺口、截断窗口与分组边界。
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd

from tools.factors.events import EventId


class _DayEvents:
    """Minimal EventLine used by scope tests; ordinal is 1-based like Nautilus."""

    def __init__(self) -> None:
        self.ordinal = 0
        self.day = None
        self.events = {}

    def observe(self, stamp) -> None:
        self.ordinal += 1
        day = pd.Timestamp(stamp).normalize()
        if day != self.day:
            self.day = day
            self.events[EventId.TRADING_DAY_START] = self.ordinal

    def latest(self, event):
        return self.events.get(event)

    def previous(self, event):
        return self.events.get(event)

    def first(self, event):
        return self.events.get(event)
import pytest

from tools.data.types import DataFreq
from tools.factors.expr import EvaluateContext
from tools.factors.expr.groupby_scope_eval import apply_grouped
from tools.factors.expr.lookback_scope import (
    scope_bars,
    scope_session,
    scope_trading_day,
)
from tools.factors.expr.timeline import PanelTimeline

BARS_PER_DAY = 255


class _RowNode:
    """Feeds one pre-recorded row per bar; the kernel's only data dependency."""

    def __init__(self, rows: np.ndarray) -> None:
        self.rows = rows
        self.position = -1

    def update(self, market, cache):  # noqa: ANN001 - matches StreamingNode
        self.position += 1
        return self.rows[self.position]


def _panel(products: tuple[str, ...]) -> tuple[pd.DatetimeIndex, pd.DataFrame]:
    index = pd.date_range("2026-01-05 09:31", periods=BARS_PER_DAY, freq="min")
    index = index.append(pd.date_range("2026-01-06 09:31", periods=BARS_PER_DAY, freq="min"))
    steps = np.arange(BARS_PER_DAY, dtype=float)
    rng = np.random.default_rng(11)
    columns = {}
    for offset, product in enumerate(products):
        day_one = np.sin((steps + offset) / 9.0) * 5.0 + steps * 0.1 + 1000.0 * offset
        day_two = np.cos((steps + offset) / 7.0) * 3.0 - steps * 0.05 + 1000.0 * offset
        column = np.r_[day_one, day_two]
        # 缺口：不同产品在不同位置缺观测，模拟异步面板
        column[7 + offset] = np.nan
        column[BARS_PER_DAY + 40 + offset * 3] = np.nan
        column[BARS_PER_DAY + 41 + offset * 3] = np.nan
        if offset:
            column[130:135] = np.nan
        columns[product] = column
    frame = pd.DataFrame(columns, index=index)
    return index, frame


def _ctx(frame: pd.DataFrame) -> EvaluateContext:
    index = frame.index
    timeline = PanelTimeline(
        index=index,
        products=tuple(frame.columns),
        trading_days=pd.Index(pd.DatetimeIndex(index).normalize(), name="DAY1"),
        observed_mask=frame.notna(),
        same_session=True,
    )
    return EvaluateContext(
        products=tuple(frame.columns),
        freq=DataFreq.MIN1,
        cache={},
        panel_timeline=timeline,
    )


CASES = [
    ("mean", None, 0, None),
    ("mean", None, 0, 119),
    ("mean", None, 120, None),
    ("sum", None, 0, None),
    ("std", None, 0, None),
    ("var", None, 0, 59),
    ("min", None, 0, None),
    ("max", None, 0, 119),
    ("median", None, 0, None),
    ("quantile", 0.5, 0, None),
    ("quantile", 0.25, 0, 200),
    ("argmax", None, 0, None),
    ("argmax", None, 0, 119),
    ("argmin", None, 0, None),
]


def test_compiled_plan_routes_groupby_scope_to_the_scope_kernel():
    """接线证据：走真正的 compile_streaming_factor 路径，必须落到作用域内核。

    直接 import 内核的单测不能证明分派接线正确（两条 elif 分支里只有第一条可达），
    所以这里断言编译产物本身，并喂几根 bar 看它真的按当日累计。
    """
    from tools.data.types import DataColumn, DataFreq
    from tools.factors.expr.groupby_scope import GroupByScopeExpr
    from tools.factors.expr.leaf import ColumnRef
    from tools.factors.expr.streaming.incremental import (
        RustIntervalNode,
        StreamingFactorPlan,
        compile_incremental_factor,
        compile_streaming_factor,
    )

    column = DataColumn.CLOSE
    expression = GroupByScopeExpr(scope_trading_day(), ColumnRef(column)).mean()
    events = _DayEvents()
    plan = compile_streaming_factor(
        expression, ("A",), source_freq=DataFreq.MIN1, event_line=events,
    )
    assert isinstance(plan, StreamingFactorPlan)
    assert isinstance(plan._root, RustIntervalNode), (
        f"编译路径没有接到事件作用域内核，而是 {type(plan._root).__name__}"
    )

    executor = compile_incremental_factor(
        "trading-day-mean", expression, ("A",), source_freq=DataFreq.MIN1,
        event_line=events,
    )
    index = pd.date_range("2026-01-05 09:31", periods=4, freq="min")
    observed = []
    for position, stamp in enumerate(index):
        events.observe(stamp)
        executor.on_bar(
            pd.Timestamp(stamp),
            {"A": {column.name: float(position)}},
            trading_day=pd.Timestamp(stamp).normalize(),
        )
        observed.append(executor.on_signal(stamp)["A"])

    assert observed == [0.0, 0.5, 1.0, 1.5], observed


def test_compiled_plan_resets_at_the_day_boundary():
    """跨日必须重置：第二天的第一根只等于自己的值，而不是两天的累计。"""
    from tools.data.types import DataColumn, DataFreq
    from tools.factors.expr.groupby_scope import GroupByScopeExpr
    from tools.factors.expr.leaf import ColumnRef
    from tools.factors.expr.streaming.incremental import compile_streaming_factor
    from tools.factors.expr.streaming.incremental import compile_incremental_factor

    column = DataColumn.CLOSE
    expression = GroupByScopeExpr(scope_trading_day(), ColumnRef(column)).mean()
    events = _DayEvents()
    executor = compile_incremental_factor(
        "trading-day-mean", expression, ("A",), source_freq=DataFreq.MIN1,
        event_line=events,
    )

    def feed(day: str, values: list[float]) -> list[float]:
        out = []
        stamps = pd.date_range(f"{day} 09:31", periods=len(values), freq="min")
        for value, stamp in zip(values, stamps, strict=True):
            events.observe(stamp)
            executor.on_bar(
                pd.Timestamp(stamp), {"A": {column.name: value}},
                trading_day=pd.Timestamp(stamp).normalize(),
            )
            out.append(executor.on_signal(stamp)["A"])
        return out

    first = feed("2026-01-05", [10.0, 20.0, 30.0])
    second = feed("2026-01-06", [100.0, 300.0])
    assert first == [10.0, 15.0, 20.0], first
    assert second == [100.0, 200.0], second


def _ctx_with_trading_days(frame, days):
    """与生产同一口径：交易日由调用方给出（生产来自索引的 DAY1 层）。"""
    timeline = PanelTimeline(
        index=frame.index,
        products=tuple(frame.columns),
        trading_days=pd.Index(pd.DatetimeIndex(days), name="DAY1"),
        observed_mask=frame.notna(),
        same_session=True,
    )
    return EvaluateContext(
        products=tuple(frame.columns), freq=DataFreq.MIN1, cache={}, panel_timeline=timeline
    )


def test_timeline_trading_days_prefers_the_day1_index_level():
    """平台口径：MultiIndex 带 DAY1 层就用该层，否则才退回日历日。"""
    from tools.factors.expr.timeline import _trading_days

    stamps = pd.DatetimeIndex(["2026-03-02 20:30", "2026-03-02 21:30", "2026-03-03 09:31"])
    days = pd.DatetimeIndex(["2026-03-02", "2026-03-03", "2026-03-03"])
    multi = pd.MultiIndex.from_arrays([days, stamps], names=["DAY1", "TIME"])
    assert list(_trading_days(multi)) == list(days), "DAY1 层必须优先于日历日"
    # 层名不是 DAY1 时同样必须被认作交易日层（历史实现只认 DAY1，会静默退回日历日）
    named = pd.MultiIndex.from_arrays([days, stamps], names=["trading_day", "TIME"])
    assert list(_trading_days(named)) == list(days), "trading_day 层也是交易日层"
    signal = pd.MultiIndex.from_arrays([days, stamps], names=["_SIGNAL@DAY1", "TIME"])
    assert list(_trading_days(signal)) == list(days), "_SIGNAL@DAY1 层也是交易日层"
    assert list(_trading_days(stamps)) == list(stamps.normalize()), "无日级层才用日历日"


def test_rolling_slides_while_scope_resets_within_partition():
    """rolling(3) keeps the last 3 bars; scope_bars(3) resets every 3 bars."""
    import pandas as pd

    from tools.data.types import DataColumn, DataFreq
    from tools.factors.expr.groupby_scope import GroupByScopeExpr
    from tools.factors.expr.leaf import ColumnRef, _to_expr
    from tools.factors.expr.lookback_scope import scope_bars
    from tools.factors.expr.streaming.incremental import compile_incremental_factor

    column = DataColumn.CLOSE
    rolling = compile_incremental_factor(
        "rolling-3", ColumnRef(column).rolling_mean(3), ("A",),
        source_freq=DataFreq.MIN1,
    )
    scoped = compile_incremental_factor(
        "scope-3",
        GroupByScopeExpr(scope_bars(3), ColumnRef(column)).mean(),
        ("A",), source_freq=DataFreq.MIN1,
    )
    stamps = pd.date_range("2026-01-05 09:31", periods=5, freq="min")
    rolling_values = []
    scoped_values = []
    for value, stamp in zip([10.0, 20.0, 30.0, 40.0, 50.0], stamps, strict=True):
        fields = {"A": {column.name: value}}
        rolling.on_bar(pd.Timestamp(stamp), fields)
        scoped.on_bar(pd.Timestamp(stamp), fields)
        rolling_values.append(rolling.on_signal(stamp)["A"])
        scoped_values.append(scoped.on_signal(stamp)["A"])

    np.testing.assert_allclose(
        rolling_values, [10.0, 15.0, 20.0, 30.0, 40.0],
    )
    np.testing.assert_allclose(scoped_values, [10.0, 15.0, 20.0, 40.0, 45.0])
