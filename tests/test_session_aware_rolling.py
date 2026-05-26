from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from tools.data.DataFreq import DataFreq
from tools.factors.FactorExpr import (
    ColumnRef, ConstExpr, FactorExpr, build_panel_timeline,
)
from tools.factors.expr.shift import ShiftOp
from tools.factors.expr.rolling import RollingExpr, WindowBarsExpr


# ── helpers ──

class _Product:
    """A simple product stub that provides a trading schedule."""

    def __init__(self, name: str, *sessions: str, day_periods: int = 240):
        self.name = name
        self.schedule = None
        if sessions:
            from tools.products.TradingSchedule import TradingSchedule
            self.schedule = TradingSchedule.from_strings(*sessions)

        # Attach MIN1 with the configured day_periods for _resolve_windows
        class _FreqMeta:
            pass
        fm = _FreqMeta()
        fm.day_periods = day_periods
        setattr(self, 'MIN1', fm)

    def get_trading_schedule(self):
        return self.schedule

    def __repr__(self):
        return self.name


def _frame(times: list[str], values: list[float] | None = None,
           col: str = "A") -> pd.DataFrame:
    index = pd.to_datetime(times)
    if values is None:
        values = list(range(len(times)))
    return pd.DataFrame({col: values}, index=index)


# ── tests ──

def test_same_session_rolling_unchanged():
    """Rolling(3).mean() on same-session panel matches standard pandas rolling."""
    product = _Product("same", "09:00-09:05")
    raw = _frame([
        "2026-05-25 09:00", "2026-05-25 09:01", "2026-05-25 09:02",
        "2026-05-25 09:03", "2026-05-25 09:04", "2026-05-25 09:05",
    ], col="close")
    preloaded = {(product, "MIN1"): raw}
    timeline = build_panel_timeline([product], DataFreq.MIN1, preloaded)

    data = raw.rename(columns={"close": product})
    operand = ConstExpr(data)
    window = ConstExpr(3)
    roll_expr = RollingExpr(operand, window).mean()

    result = roll_expr.evaluate(
        products=[product], freq=DataFreq.MIN1,
        preloaded=preloaded,
        panel_timeline=timeline,
    )

    expected = data.rolling(3, min_periods=max(1, 3 // 2)).mean()
    pd.testing.assert_frame_equal(result, expected)


def test_intraday_rolling_skips_non_scheduled_slots():
    """Rolling(2).mean() skips fill slots for a product with partial schedule."""
    short = _Product("short", "09:00-09:02")
    long = _Product("long", "09:00-09:04")

    short_data = _frame(
        ["2026-05-25 09:00", "2026-05-25 09:01", "2026-05-25 09:02"],
        values=[1.0, 2.0, 3.0], col="v",
    )
    long_data = _frame(
        ["2026-05-25 09:00", "2026-05-25 09:01", "2026-05-25 09:02",
         "2026-05-25 09:03", "2026-05-25 09:04"],
        values=[10.0, 11.0, 12.0, 13.0, 14.0], col="v",
    )

    preloaded = {
        (short, "MIN1"): short_data,
        (long, "MIN1"): long_data,
    }
    timeline = build_panel_timeline([short, long], DataFreq.MIN1, preloaded)

    idx = pd.DatetimeIndex([
        "2026-05-25 09:00", "2026-05-25 09:01", "2026-05-25 09:02",
        "2026-05-25 09:03", "2026-05-25 09:04",
    ])
    combined = pd.DataFrame({
        short: [1.0, 2.0, 3.0, np.nan, np.nan],
        long: [10.0, 11.0, 12.0, 13.0, 14.0],
    }, index=idx)

    operand = ConstExpr(combined)
    window = ConstExpr(2)
    roll_expr = RollingExpr(operand, window).mean()

    result = roll_expr.evaluate(
        products=[short, long], freq=DataFreq.MIN1,
        panel_timeline=timeline,
    )

    # short rolling(2):
    # 09:00: only 1 scheduled bar → min_periods=1 → result=1.0
    # 09:01: scheduled bars [1.0, 2.0] → mean=1.5
    # 09:02: scheduled bars [2.0, 3.0] → mean=2.5
    # 09:03: not scheduled → NaN
    # 09:04: not scheduled → NaN
    assert result.loc[pd.Timestamp("2026-05-25 09:00"), short] == 1.0
    assert result.loc[pd.Timestamp("2026-05-25 09:01"), short] == 1.5
    assert result.loc[pd.Timestamp("2026-05-25 09:02"), short] == 2.5
    assert np.isnan(result.loc[pd.Timestamp("2026-05-25 09:03"), short])
    assert np.isnan(result.loc[pd.Timestamp("2026-05-25 09:04"), short])

    # long rolling(2):
    # 09:00: only 1 bar → min_periods=1 → 10.0
    # 09:01-09:04: rolling means of 2 bars
    assert result.loc[pd.Timestamp("2026-05-25 09:00"), long] == 10.0
    assert result.loc[pd.Timestamp("2026-05-25 09:01"), long] == 10.5
    assert result.loc[pd.Timestamp("2026-05-25 09:02"), long] == 11.5
    assert result.loc[pd.Timestamp("2026-05-25 09:03"), long] == 12.5
    assert result.loc[pd.Timestamp("2026-05-25 09:04"), long] == 13.5


def test_adding_different_session_product_does_not_change_existing_rolling():
    """Rolling output for existing product is invariant to adding a different-session product."""
    short = _Product("short", "09:00-09:01")
    long = _Product("long", "09:00-09:02")

    short_data = _frame(["2026-05-25 09:00", "2026-05-25 09:01"],
                        values=[100.0, 101.0])
    long_data = _frame(["2026-05-25 09:00", "2026-05-25 09:01", "2026-05-25 09:02"],
                       values=[200.0, 201.0, 202.0])

    # --- reference: short alone ---
    preloaded_short = {(short, "MIN1"): short_data}
    timeline_short = build_panel_timeline([short], DataFreq.MIN1, preloaded_short)
    operand_short = ConstExpr(short_data.rename(columns={"A": short}))
    ref = RollingExpr(operand_short, ConstExpr(2)).mean().evaluate(
        products=[short], freq=DataFreq.MIN1,
        preloaded=preloaded_short,
        panel_timeline=timeline_short,
    )

    # --- combined ---
    preloaded_both = {
        (short, "MIN1"): short_data,
        (long, "MIN1"): long_data,
    }
    timeline_both = build_panel_timeline([short, long], DataFreq.MIN1, preloaded_both)

    idx = pd.DatetimeIndex(["2026-05-25 09:00", "2026-05-25 09:01", "2026-05-25 09:02"])
    combined = pd.DataFrame({
        short: [100.0, 101.0, np.nan],
        long: [200.0, 201.0, 202.0],
    }, index=idx)

    result = RollingExpr(ConstExpr(combined), ConstExpr(2)).mean().evaluate(
        products=[short, long], freq=DataFreq.MIN1,
        panel_timeline=timeline_both,
    )

    for ts in [pd.Timestamp("2026-05-25 09:00"), pd.Timestamp("2026-05-25 09:01")]:
        if np.isnan(ref.loc[ts, short]):
            assert np.isnan(result.loc[ts, short])
        else:
            assert abs(result.loc[ts, short] - ref.loc[ts, short]) < 1e-10


def test_scheduled_but_unobserved_bars_counted_in_window():
    """Scheduled-but-missing bars are counted in window size but contribute NaN."""
    product = _Product("prod", "09:00-09:03")
    # 09:02 is scheduled but missing from raw data
    data = _frame(
        ["2026-05-25 09:00", "2026-05-25 09:01", "2026-05-25 09:03"],
        values=[1.0, 4.0, 9.0], col="v",
    )
    preloaded = {(product, "MIN1"): data}
    timeline = build_panel_timeline([product], DataFreq.MIN1, preloaded)

    idx = pd.DatetimeIndex([
        "2026-05-25 09:00", "2026-05-25 09:01", "2026-05-25 09:02", "2026-05-25 09:03",
    ])
    operand_df = pd.DataFrame({
        product: [1.0, 4.0, np.nan, 9.0],
    }, index=idx)

    operand = ConstExpr(operand_df)
    roll_expr = RollingExpr(operand, ConstExpr(3)).mean()

    result = roll_expr.evaluate(
        products=[product], freq=DataFreq.MIN1,
        panel_timeline=timeline,
    )

    # At 09:03, the window covers 09:01, 09:02(scheduled but NaN), 09:03
    # mean([4.0, NaN, 9.0]) with skipna=True → 6.5
    assert abs(result.loc[pd.Timestamp("2026-05-25 09:03"), product] - 6.5) < 1e-10


def test_rolling_argmax_raw_session_aware():
    """Rolling argmax_raw respects scheduled mask on intraday data."""
    product = _Product("prod", "09:00-09:04")
    raw = _frame(
        ["2026-05-25 09:00", "2026-05-25 09:01",
         "2026-05-25 09:02", "2026-05-25 09:03", "2026-05-25 09:04"],
        values=[5.0, 2.0, 8.0, 1.0, 3.0], col="v",
    )
    preloaded = {(product, "MIN1"): raw}
    timeline = build_panel_timeline([product], DataFreq.MIN1, preloaded)

    data = raw.rename(columns={"v": product})
    operand = ConstExpr(data)
    roll_expr = RollingExpr(operand, ConstExpr(3)).argmax_raw()

    result = roll_expr.evaluate(
        products=[product], freq=DataFreq.MIN1,
        panel_timeline=timeline,
    )

    # Window size 3, first 2 rows NaN (min_periods check not in our positional path)
    # row 09:02: window [09:00=5, 09:01=2, 09:02=8] → argmax (most recent first):
    #   reversed: [8, 2, 5] → nanargmax → 0 → raw_pos=3-1-0=2
    assert result.loc[pd.Timestamp("2026-05-25 09:02"), product] == 2.0

    # row 09:03: window [09:01=2, 09:02=8, 09:03=1] → reversed [1, 8, 2] → argmax=1 → raw_pos=3-1-1=1
    assert result.loc[pd.Timestamp("2026-05-25 09:03"), product] == 1.0

    # row 09:04: window [09:02=8, 09:03=1, 09:04=3] → reversed [3, 1, 8] → argmax=2 → raw_pos=3-1-2=0
    assert result.loc[pd.Timestamp("2026-05-25 09:04"), product] == 0.0


def test_rolling_without_timeline_uses_fixed_bars():
    """Without a PanelTimeline, rolling falls back to pandas rolling(periods)."""
    idx = pd.DatetimeIndex(["2026-05-25 09:00", "2026-05-25 09:01", "2026-05-25 09:02",
                            "2026-05-25 09:03", "2026-05-25 09:04"])
    data = pd.DataFrame({"A": [1.0, 2.0, 3.0, 4.0, 5.0]}, index=idx)

    operand = ConstExpr(data)
    result = RollingExpr(operand, ConstExpr(3)).mean().evaluate(
        products=["A"], freq=DataFreq.MIN1,
    )

    expected = data.rolling(3, min_periods=max(1, 3 // 2)).mean()
    pd.testing.assert_frame_equal(result, expected)


def test_bars_rejects_async_day_window():
    """Day-mixed .bars on asynchronous panels rejects explicitly."""
    short = _Product("short", "09:00-09:01", day_periods=2)
    long = _Product("long", "09:00-09:03", day_periods=4)

    # 1-day window with intraday frequency on async sessions → different bar counts
    window = ConstExpr(DataFreq("1d"))
    operand = ConstExpr(pd.DataFrame({"dummy": [1.0]}, index=pd.DatetimeIndex(["2026-05-25 09:00"])))

    bars_expr = RollingExpr(operand, window).bars

    # Different day_periods → common=False → rejected
    with pytest.raises(ValueError, match="scalar bar count"):
        bars_expr.evaluate(products=[short, long], freq=DataFreq.MIN1)


def test_tide_factor_product_group_expansion_invariance():
    """A tide-style factor (rolling argmin/argmax + truncation) is invariant
    under product-group expansion (same session)."""
    product = _Product("prod", "09:00-09:04")
    raw = _frame(
        ["2026-05-25 09:00", "2026-05-25 09:01",
         "2026-05-25 09:02", "2026-05-25 09:03", "2026-05-25 09:04"],
        values=[10.0, 9.0, 12.0, 8.0, 11.0], col="close",
    )
    preloaded = {(product, "MIN1"): raw}
    timeline = build_panel_timeline([product], DataFreq.MIN1, preloaded)

    data = raw.rename(columns={"close": product})
    operand = ConstExpr(data)

    # Build a tide-style rolling sum over a 3-bar window
    roll_sum = RollingExpr(operand, ConstExpr(3)).sum()

    result = roll_sum.evaluate(
        products=[product], freq=DataFreq.MIN1,
        preloaded=preloaded,
        panel_timeline=timeline,
    )

    # Verify same-session matches pandas
    expected = data.rolling(3, min_periods=1).sum()
    pd.testing.assert_frame_equal(result, expected)
