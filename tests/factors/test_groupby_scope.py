"""``groupby_scope`` aggregates inside a lookback partition (当日／会话／每 K 根).

Unlike ``rolling(K)``, which slides a fixed-length window and therefore reaches
across the trading-day boundary, these kernels use only the current partition up
to and including the current bar.  At 1-minute frequency with 255 bars per day,
``rolling('1d')`` is "the last 255 bars", not "today".
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from tools.data.types import DataFreq
from tools.factors.expr import EvaluateContext
from tools.factors.expr.core import FactorExpr
from tools.factors.expr.groupby_scope import GroupByScopeExpr
from tools.factors.expr.leaf import ConstExpr
from tools.factors.expr.lookback_scope import scope_bars, scope_trading_day
from tools.factors.expr.timeline import PanelTimeline

BARS_PER_DAY = 255


class _FrameExpr(FactorExpr):
    """A ready-made frame, so the kernel can be tested without a data source."""

    def __init__(self, frame: pd.DataFrame) -> None:
        self.frame = frame

    def _evaluate(self, ctx: EvaluateContext) -> pd.DataFrame:
        return self.frame

    def _structural_key(self) -> tuple:
        return ("frame", id(self))

    def _to_latex(self, subst=None) -> str:
        return "X"

    def _get_alias(self) -> str:
        return "X"


def _two_days(values: np.ndarray) -> tuple[pd.DatetimeIndex, pd.DataFrame]:
    """Two trading days of 1-minute bars, 255 bars each (T 合约节奏)."""
    index = pd.date_range(
        "2026-01-05 09:31", periods=BARS_PER_DAY, freq="min",
    ).append(pd.date_range("2026-01-06 09:31", periods=BARS_PER_DAY, freq="min"))
    return index, pd.DataFrame({"A": values}, index=index)


def _ctx(index: pd.Index) -> EvaluateContext:
    timeline = PanelTimeline(
        index=index,
        products=("A",),
        trading_days=pd.Index(pd.DatetimeIndex(index).normalize(), name="DAY1"),
        observed_mask=pd.DataFrame(True, index=index, columns=("A",)),
        same_session=True,
    )
    return EvaluateContext(
        products=("A",), freq=DataFreq.MIN1, cache={}, panel_timeline=timeline,
    )


def _daily_values() -> np.ndarray:
    day_one = np.arange(BARS_PER_DAY, dtype=float)
    day_two = np.arange(BARS_PER_DAY, dtype=float) + 1000.0
    return np.r_[day_one, day_two]


def test_morning_mean_uses_only_the_current_trading_day():
    """当日午前均值 = 当日前 120 根；rolling('1d') 会混入前一交易日。"""
    index, frame = _two_days(_daily_values())
    ctx = _ctx(index)
    data = _FrameExpr(frame)

    # 观察时点为第二日第 201 根（14:21）
    target = BARS_PER_DAY + 200
    grouped = GroupByScopeExpr(scope_trading_day(), data).truncate(0, 119).mean()
    got = grouped.evaluate(ctx=ctx)["A"].iloc[target]
    expected = float(np.mean(np.arange(120, dtype=float) + 1000.0))
    assert got == expected, f"当日午前均值应为 {expected}，实际 {got}"

    # 固定 255 根尾窗在同一时点会混入前一交易日：手算该窗口前 120 根均值作对照
    values = _daily_values()
    window = values[target - BARS_PER_DAY + 1: target + 1]
    crossed = float(np.mean(window[:120]))
    assert crossed != got, "rolling 式尾窗与 groupby_scope 在跨日边界上必须不同"
    # 该窗口里确实有跨日观测，证明这不是等价实现
    assert int(np.sum(window[:120] < 1000.0)) == 54


def test_partitions_do_not_cross_group_boundaries():
    """scope_bars(5) 每 5 根一组、不重叠；第 7 根处与 rolling(5) 不同。"""
    values = np.arange(20, dtype=float)
    index, frame = _two_days(np.r_[values, np.full(BARS_PER_DAY * 2 - len(values), np.nan)])
    ctx = _ctx(index)
    data = _FrameExpr(frame)

    grouped = GroupByScopeExpr(scope_bars(5), data).mean().evaluate(ctx=ctx)["A"]
    sliding = data.rolling(5).mean().evaluate(ctx=ctx)["A"]

    # 第 7 根（0-based）= 第二组第 3 根：组内 [5,6,7] 均值 = 6
    assert grouped.iloc[7] == 6.0, f"组内累计应为 6，实际 {grouped.iloc[7]}"
    # 滑动窗口 [3,4,5,6,7] 均值 = 5
    assert sliding.iloc[7] == 5.0
    assert grouped.iloc[7] != sliding.iloc[7]


def test_aggregation_is_causal():
    """改动未来根不得改变历史输出。"""
    index, frame = _two_days(_daily_values())
    ctx = _ctx(index)
    target = BARS_PER_DAY + 200

    before = GroupByScopeExpr(scope_trading_day(), _FrameExpr(frame)).argmax().evaluate(ctx=ctx)
    mutated = frame.copy()
    mutated.iloc[-1, 0] = -1e9           # 改动当日最后一根（使其不再是最优）
    after = GroupByScopeExpr(scope_trading_day(), _FrameExpr(mutated)).argmax().evaluate(ctx=ctx)

    np.testing.assert_allclose(before["A"].iloc[: BARS_PER_DAY + 1],
                               after["A"].iloc[: BARS_PER_DAY + 1], equal_nan=True)
    assert after["A"].iloc[-1] != before["A"].iloc[-1] or before["A"].iloc[-1] != before["A"].iloc[target], \
        "未来根变化应改变其后的取值"


def test_argmax_normalisation_matches_rolling_convention():
    """0 = 最新、1 = 组内最早，与 rolling().argmax() 的方向一致。"""
    index, frame = _two_days(_daily_values())
    ctx = _ctx(index)
    data = _FrameExpr(frame)

    series = GroupByScopeExpr(scope_trading_day(), data).argmax().evaluate(ctx=ctx)["A"]
    # 单调递增：最大值始终是当前根 → 归一化位置恒为 0
    assert series.iloc[BARS_PER_DAY - 1] == 0.0
    assert series.iloc[-1] == 0.0
    # 单调递减时最大值是组内最早根 → 1
    falling, fall_frame = _two_days(-_daily_values())
    fall = GroupByScopeExpr(scope_trading_day(), _FrameExpr(fall_frame)).argmax().evaluate(
        ctx=_ctx(falling),
    )["A"]
    assert fall.iloc[BARS_PER_DAY - 1] == 1.0


def test_quantile_and_truncate_bounds():
    index, frame = _two_days(_daily_values())
    ctx = _ctx(index)
    data = _FrameExpr(frame)

    quantile = GroupByScopeExpr(scope_trading_day(), data).quantile(
        ConstExpr(0.5),
    ).evaluate(ctx=ctx)["A"]
    # 当日中位数：第 k 根的组内中位数位于 [1000, 1000+k] 的中位
    assert quantile.iloc[BARS_PER_DAY] == 1000.0
    assert quantile.iloc[BARS_PER_DAY + 2] == 1001.0


def test_arg_extreme_vectorised_and_per_bar_paths_agree(monkeypatch):
    """向量化路径与逐根路径必须逐点相等（并列取最早、截断后 span 继续增长）。"""
    from tools.factors.expr import groupby_scope_eval as gse

    index, _ = _two_days(np.zeros(BARS_PER_DAY * 2))
    values = np.resize(
        np.array([1.0, 5.0, 5.0, 2.0, 5.0, 0.0, 3.0, 3.0, 4.0, 4.0, 9.0, 9.0]), len(index)
    ).astype(float)
    values[0] = np.nan
    values[BARS_PER_DAY] = np.nan
    values[BARS_PER_DAY + 7] = np.nan
    values[-1] = np.nan
    index, frame = _two_days(values)
    ctx = _ctx(index)

    cases = [
        (op, scope, start, end)
        for op in ("argmax", "argmin")
        for scope in (scope_trading_day(), scope_bars(5))
        for start, end in ((0, None), (0, 119), (3, 40), (0, 0))
    ]
    for op, scope, start, end in cases:
        monkeypatch.setattr(gse, "_ARG_EXTREME_VECTOR_FLOOR", 1)
        vectorised = gse.apply_grouped(
            op, scope, frame, ctx=ctx, trunc_start=start, trunc_end=end
        )["A"].to_numpy(dtype=float)
        monkeypatch.setattr(gse, "_ARG_EXTREME_VECTOR_FLOOR", 10 ** 9)
        per_bar = gse.apply_grouped(
            op, scope, frame, ctx=ctx, trunc_start=start, trunc_end=end
        )["A"].to_numpy(dtype=float)
        label = f"{op}/trunc({start},{end})"
        assert np.array_equal(np.isnan(vectorised), np.isnan(per_bar)), label
        np.testing.assert_allclose(
            vectorised[~np.isnan(vectorised)], per_bar[~np.isnan(per_bar)],
            rtol=1e-12, atol=1e-12, err_msg=label,
        )
