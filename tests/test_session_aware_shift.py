from __future__ import annotations

import numpy as np
import pandas as pd

from tools.data.DataFreq import DataFreq
from tools.factors.FactorExpr import (
    ColumnRef, ConstExpr, FactorExpr, ShiftOp, build_panel_timeline,
)
from tools.products.TradingSchedule import TradingSchedule


# ── helpers ──

class _Product:
    """A simple product stub that provides a trading schedule."""

    def __init__(self, name: str, *sessions: str):
        self.name = name
        self.schedule = TradingSchedule.from_strings(*sessions)

    def get_trading_schedule(self):
        return self.schedule

    def __repr__(self):
        return self.name


def _frame(times: list[str], values: list[float] | None = None) -> pd.DataFrame:
    index = pd.to_datetime(times)
    if values is None:
        values = list(range(len(times)))
    return pd.DataFrame({"CLOSE": values}, index=index)


# ── tests ──

def test_same_session_shift_unchanged():
    """On same-session panels, temporal shift is equivalent to fixed-bars shift."""
    product = _Product("same", "09:00-09:05")
    data = _frame([
        "2026-05-25 09:00", "2026-05-25 09:01", "2026-05-25 09:02",
        "2026-05-25 09:03", "2026-05-25 09:04", "2026-05-25 09:05",
    ])
    preloaded = {(product, "MIN1"): data}
    timeline = build_panel_timeline([product], DataFreq.MIN1, preloaded)

    periods = ConstExpr(2)
    operand = ConstExpr(data)
    shift_op = ShiftOp("shift", periods, operand)

    result = shift_op.evaluate(
        products=[product], freq=DataFreq.MIN1,
        preloaded=preloaded,
        panel_timeline=timeline,
    )

    expected = data.shift(2)
    pd.testing.assert_frame_equal(result, expected)


def test_intraday_shift_respects_scheduled_mask():
    """An intraday shift skips slots where the product is not scheduled."""
    daytime = _Product("day", "09:00-09:02")
    longer = _Product("long", "09:00-09:04")

    day_data = _frame(["2026-05-25 09:00", "2026-05-25 09:01", "2026-05-25 09:02"])
    long_data = _frame([
        "2026-05-25 09:00", "2026-05-25 09:01", "2026-05-25 09:02",
        "2026-05-25 09:03", "2026-05-25 09:04",
    ])

    preloaded = {
        (daytime, "MIN1"): day_data,
        (longer, "MIN1"): long_data,
    }
    timeline = build_panel_timeline([daytime, longer], DataFreq.MIN1, preloaded)

    # Build a combined operand DataFrame that mimics what SignalAlign produces
    # after union alignment
    idx = pd.DatetimeIndex([
        "2026-05-25 09:00", "2026-05-25 09:01", "2026-05-25 09:02",
        "2026-05-25 09:03", "2026-05-25 09:04",
    ])
    combined = pd.DataFrame({
        daytime: [0.0, 1.0, 2.0, np.nan, np.nan],
        longer: [10.0, 11.0, 12.0, 13.0, 14.0],
    }, index=idx)

    # Evaluate shift(1) via a ConstExpr operand
    operand = ConstExpr(combined)
    periods = ConstExpr(1)
    shift_op = ShiftOp("shift", periods, operand)

    result = shift_op.evaluate(
        products=[daytime, longer], freq=DataFreq.MIN1,
        panel_timeline=timeline,
    )

    # daytime: shift(1) on cols [0,1,2] within scheduled mask
    #         09:00 → no earlier → NaN
    #         09:01 → 09:00 value = 0.0
    #         09:02 → 09:01 value = 1.0
    #         09:03, 09:04 → not scheduled → not shifted (stays NaN)
    assert np.isnan(result.loc[pd.Timestamp("2026-05-25 09:00"), daytime])
    assert result.loc[pd.Timestamp("2026-05-25 09:01"), daytime] == 0.0
    assert result.loc[pd.Timestamp("2026-05-25 09:02"), daytime] == 1.0

    # longer: shift(1) across all 5 bars
    assert np.isnan(result.loc[pd.Timestamp("2026-05-25 09:00"), longer])
    assert result.loc[pd.Timestamp("2026-05-25 09:01"), longer] == 10.0
    assert result.loc[pd.Timestamp("2026-05-25 09:02"), longer] == 11.0
    assert result.loc[pd.Timestamp("2026-05-25 09:03"), longer] == 12.0
    assert result.loc[pd.Timestamp("2026-05-25 09:04"), longer] == 13.0


def test_longer_session_product_does_not_alter_existing_intraday_shift():
    """Adding a longer-session product does not change intraday shift for existing products."""
    short = _Product("short", "09:00-09:01")
    long = _Product("long", "09:00-09:02")

    short_data = _frame(["2026-05-25 09:00", "2026-05-25 09:01"],
                        values=[100.0, 101.0])
    long_data = _frame(["2026-05-25 09:00", "2026-05-25 09:01", "2026-05-25 09:02"],
                       values=[200.0, 201.0, 202.0])

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

    operand = ConstExpr(combined)
    periods = ConstExpr(1)
    shift_op = ShiftOp("shift", periods, operand)

    result = shift_op.evaluate(
        products=[short, long], freq=DataFreq.MIN1,
        panel_timeline=timeline_both,
    )

    # short: shift(1) should match the result without long in panel
    # Compute reference: short alone
    preloaded_short = {(short, "MIN1"): short_data}
    timeline_short = build_panel_timeline([short], DataFreq.MIN1, preloaded_short)
    operand_short = ConstExpr(short_data.rename(columns={"CLOSE": short}))
    ref = ShiftOp("shift", periods, operand_short).evaluate(
        products=[short], freq=DataFreq.MIN1,
        panel_timeline=timeline_short,
    )

    for ts in [pd.Timestamp("2026-05-25 09:00"), pd.Timestamp("2026-05-25 09:01")]:
        if np.isnan(ref.loc[ts, short]):
            assert np.isnan(result.loc[ts, short])
        else:
            assert result.loc[ts, short] == ref.loc[ts, short]

    # At 09:02 short is not scheduled — should be NaN
    assert np.isnan(result.loc[pd.Timestamp("2026-05-25 09:02"), short])


def test_scheduled_but_missing_source_bar_produces_nan():
    """A scheduled-but-unobserved source bar produces NaN, not an older value."""
    product = _Product("prod", "09:00-09:02")
    # 09:01 is scheduled but missing from raw data
    data = _frame(["2026-05-25 09:00", "2026-05-25 09:02"],
                  values=[100.0, 102.0])
    preloaded = {(product, "MIN1"): data}
    timeline = build_panel_timeline([product], DataFreq.MIN1, preloaded)

    idx = pd.DatetimeIndex(["2026-05-25 09:00", "2026-05-25 09:01", "2026-05-25 09:02"])
    operand_df = pd.DataFrame({
        product: [100.0, np.nan, 102.0],
    }, index=idx)

    operand = ConstExpr(operand_df)
    periods = ConstExpr(1)
    shift_op = ShiftOp("shift", periods, operand)

    result = shift_op.evaluate(
        products=[product], freq=DataFreq.MIN1,
        panel_timeline=timeline,
    )

    # 09:02 shift(1) → target is 09:01 which is scheduled but not observed → NaN
    assert np.isnan(result.loc[pd.Timestamp("2026-05-25 09:02"), product])


def test_pure_intraday_shift_without_timeline_uses_fixed_bars():
    """Without a PanelTimeline, shift falls back to integer bar shift."""
    idx = pd.DatetimeIndex(["2026-05-25 09:00", "2026-05-25 09:01", "2026-05-25 09:02"])
    data = pd.DataFrame({"A": [1.0, 2.0, 3.0]}, index=idx)

    operand = ConstExpr(data)
    periods = ConstExpr(1)
    shift_op = ShiftOp("shift", periods, operand)

    # Products is needed for _resolve_windows when operand has column names
    result = shift_op.evaluate(products=["A"], freq=DataFreq.MIN1)

    expected = data.shift(1)
    pd.testing.assert_frame_equal(result, expected)


def test_return_alignment_shift_semantics_preserved():
    """Return-alignment .shift(-1) preserves semantics on same-session panels."""
    product = _Product("prod", "09:00-09:03")
    prices = _frame([
        "2026-05-25 09:00", "2026-05-25 09:01",
        "2026-05-25 09:02", "2026-05-25 09:03",
    ], values=[100.0, 102.0, 101.0, 105.0])
    preloaded = {(product, "MIN1"): prices}
    timeline = build_panel_timeline([product], DataFreq.MIN1, preloaded)

    re = prices / prices.shift(1) - 1.0  # raw returns
    re_aligned = re.shift(-1)  # align to signal bar

    # Equivalent via DSL
    operand = ConstExpr(re)
    periods = ConstExpr(-1)
    shift_op = ShiftOp("shift", periods, operand)

    result = shift_op.evaluate(
        products=[product], freq=DataFreq.MIN1,
        panel_timeline=timeline,
    )

    pd.testing.assert_frame_equal(result, re_aligned)
