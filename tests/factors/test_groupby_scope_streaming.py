"""``groupby_scope``：增量内核与批量内核必须逐点一致（ADR-022 双后端契约）。

增量侧只保留 O(1) 状态（计数/和/平方和/运行极值/极值位置 + 分区标记），
不保留 O(K) 窗口缓冲；本测试用「同一面板逐根喂入」与批量内核逐点比对，
覆盖跨交易日边界、NaN 缺口、截断窗口与分组边界。
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
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
from tools.testers.backtest.engines.factors.incremental import GroupScopeNode

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


@pytest.mark.parametrize("op,quantile,trunc_start,trunc_end", CASES)
@pytest.mark.parametrize("scope_kind", ["trading_day", "bars", "session"])
def test_streaming_matches_batch_pointwise(op, quantile, trunc_start, trunc_end, scope_kind):
    products = ("A", "B")
    index, frame = _panel(products)
    ctx = _ctx(frame)
    if scope_kind == "trading_day":
        scope = scope_trading_day()
    elif scope_kind == "bars":
        scope = scope_bars(7)
    else:
        scope = scope_session(gap="30min")

    expected = apply_grouped(
        op, scope, frame, ctx=ctx, quantile=quantile,
        trunc_start=trunc_start, trunc_end=trunc_end,
    )

    rows = frame.to_numpy(dtype=float)
    node = GroupScopeNode(
        op, _RowNode(rows), scope, len(products),
        quantile=quantile, trunc_start=trunc_start, trunc_end=trunc_end,
        products=products,
    )

    got = np.full(rows.shape, np.nan, dtype=float)
    for position in range(len(index)):
        stamp = pd.Timestamp(index[position])
        market = SimpleNamespace(
            timestamp=stamp,
            trading_day=stamp.normalize(),
            prices={},
        )
        value = node.update(market, {})
        got[position] = value

    np.testing.assert_allclose(got, expected.to_numpy(dtype=float), rtol=1e-9, atol=1e-9, equal_nan=True,
                               err_msg=f"{op}/{scope_kind}/trunc({trunc_start},{trunc_end}) 两后端不一致")


def test_streaming_state_does_not_grow_with_the_partition():
    """状态大小与分区长度无关：跑满两天后各状态数组形状不变。"""
    products = ("A",)
    index, frame = _panel(products)
    node = GroupScopeNode(
        "mean", _RowNode(frame.to_numpy(dtype=float)), scope_trading_day(), 1,
        products=products,
    )
    for position in range(len(index)):
        stamp = pd.Timestamp(index[position])
        node.update(SimpleNamespace(timestamp=stamp, trading_day=stamp.normalize(), prices={}), {})
    for name in ("_count", "_sum", "_mean", "_m2", "_raw", "_min", "_max", "_best_raw"):
        assert getattr(node, name).shape == (1,), name
    # 均值/极值类不保留任何窗口内容
    assert not hasattr(node, "_window")
