from __future__ import annotations

import pandas as pd
import numpy as np

from tools.data.types import DataFreq
from tools.factors.FactorExpr import EvaluateContext, FactorExpr, SignalAlign, signal_align
from tools.factors.expr.timeline import PanelTimeline


class _FrameExpr(FactorExpr):
    def __init__(self, value: pd.DataFrame):
        self.value = value

    def _evaluate(self, ctx):
        return self.value

    def _structural_key(self):
        return ("frame", id(self))


def test_signal_align_does_not_skip_session_gap_by_default():
    idx = pd.DatetimeIndex(
        list(pd.date_range("2026-01-01 09:01", periods=5, freq="min"))
        + list(pd.date_range("2026-01-01 21:01", periods=5, freq="min")),
        name="1m",
    )
    raw = pd.DataFrame({"A": range(10)}, index=idx)

    implicit = signal_align(raw, "5m", basepoint="last")
    explicit = signal_align(raw, "5m", basepoint="last", end_session_skip=False)

    pd.testing.assert_frame_equal(implicit, explicit)


def test_signal_align_uses_last_bar_of_each_fixed_window():
    idx = pd.date_range("2026-01-01 09:01", periods=10, freq="min", name="1m")
    raw = pd.DataFrame({"A": range(10)}, index=idx)

    aligned = signal_align(raw, "5m", basepoint="last", end_session_skip=False)

    assert list(aligned["A"]) == [4, 9]
    assert list(aligned.index.get_level_values("_SIGNAL@MIN5")) == [idx[4], idx[9]]


def test_nested_signal_align_carries_only_formed_values_onto_finer_timeline():
    idx = pd.date_range("2026-01-01 09:01", periods=4, freq="min", name="1m")
    source = pd.DataFrame({"A": [1.0, 2.0, 3.0, 4.0]}, index=idx)
    fine = pd.DataFrame({"A": [10.0, 20.0, 30.0, 40.0]}, index=idx)
    expr = SignalAlign(_FrameExpr(source), "2m") + _FrameExpr(fine)

    result = expr.evaluate(
        ctx=EvaluateContext(products=["A"], freq=DataFreq.MIN1, cache={}),
    )

    assert result.index.equals(idx)
    np.testing.assert_allclose(
        result["A"].to_numpy(),
        [np.nan, 22.0, 32.0, 44.0],
        equal_nan=True,
    )


def test_outer_finer_signal_align_carries_nested_signal_on_panel_timeline():
    idx = pd.date_range("2026-01-01 09:01", periods=4, freq="min", name="1m")
    source = pd.DataFrame({"A": [1.0, 2.0, 3.0, 4.0]}, index=idx)
    timeline = PanelTimeline(
        index=idx,
        products=("A",),
        trading_days=pd.Index(idx.normalize(), name="DAY1"),
        observed_mask=pd.DataFrame(True, index=idx, columns=["A"]),
        same_session=True,
    )
    expr = SignalAlign(SignalAlign(_FrameExpr(source), "2m"), "1m")

    result = expr.evaluate(
        ctx=EvaluateContext(
            products=["A"],
            freq=DataFreq.MIN1,
            cache={},
            panel_timeline=timeline,
        ),
    )

    np.testing.assert_allclose(
        result["A"].to_numpy(),
        [np.nan, 2.0, 2.0, 4.0],
        equal_nan=True,
    )


def test_two_nested_signal_frequencies_use_the_finer_signal_timeline():
    idx = pd.date_range("2026-01-01 09:01", periods=6, freq="min", name="1m")
    left = pd.DataFrame({"A": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]}, index=idx)
    right = pd.DataFrame({"A": [10.0, 20.0, 30.0, 40.0, 50.0, 60.0]}, index=idx)
    expr = SignalAlign(_FrameExpr(left), "2m") + SignalAlign(
        _FrameExpr(right), "3m",
    )

    result = expr.evaluate(
        ctx=EvaluateContext(products=["A"], freq=DataFreq.MIN1, cache={}),
    )

    assert list(result.index.get_level_values("_SIGNAL@MIN2")) == [
        idx[1], idx[3], idx[5],
    ]
    np.testing.assert_allclose(
        result["A"].to_numpy(),
        [np.nan, 34.0, 66.0],
        equal_nan=True,
    )


def test_signal_align_resets_intraday_windows_across_session_gap():
    idx = pd.DatetimeIndex(
        list(pd.date_range("2026-01-01 09:01", periods=5, freq="min"))
        + list(pd.date_range("2026-01-01 21:01", periods=5, freq="min")),
        name="1m",
    )
    raw = pd.DataFrame({"A": range(10)}, index=idx)

    aligned = signal_align(raw, "5m", basepoint="last", end_session_skip=True)

    assert list(aligned["A"]) == [4, 9]
    assert list(aligned.index.get_level_values("_SIGNAL@MIN5")) == [idx[4], idx[9]]


def test_signal_align_daily_basepoint_selects_specific_time():
    day1 = pd.date_range("2026-01-01 09:00", periods=3, freq="h")
    day2 = pd.date_range("2026-01-02 09:00", periods=3, freq="h")
    times = pd.DatetimeIndex(list(day1) + list(day2), name="1h")
    days = pd.DatetimeIndex(times.normalize(), name="1d")
    idx = pd.MultiIndex.from_arrays([days, times], names=["1d", "1h"])
    raw = pd.DataFrame({"A": range(6)}, index=idx)

    aligned = signal_align(raw, "1d", daily_basepoint="10:00:00", end_session_skip=False)
    assert list(aligned["A"]) == [1, 4]


def test_signal_align_daily_basepoint_recovers_tuple_time_index():
    times = list(pd.date_range("2026-01-01 09:00", periods=3, freq="h"))
    times += list(pd.date_range("2026-01-02 09:00", periods=3, freq="h"))
    idx = pd.Index([(ts.normalize(), ts) for ts in times])
    raw = pd.DataFrame({"A": range(6)}, index=idx)

    aligned = signal_align(raw, "1d", daily_basepoint="10:00:00", end_session_skip=False)

    assert list(aligned["A"]) == [1, 4]
    assert aligned.index.names == ["_SIGNAL@DAY1", "HOUR1"]
    assert list(aligned.index.get_level_values("_SIGNAL@DAY1")) == [
        pd.Timestamp("2026-01-01"),
        pd.Timestamp("2026-01-02"),
    ]
    assert list(aligned.index.get_level_values("HOUR1")) == [
        pd.Timestamp("2026-01-01 10:00"),
        pd.Timestamp("2026-01-02 10:00"),
    ]


def test_signal_align_infers_business_named_multiindex_frequency():
    times = pd.DatetimeIndex([
        "2026-01-01 09:00",
        "2026-01-01 10:00",
        "2026-01-02 09:00",
        "2026-01-02 10:00",
    ])
    days = pd.DatetimeIndex(times.normalize())
    idx = pd.MultiIndex.from_arrays([days, times], names=["交易日", "数据源时间"])
    raw = pd.DataFrame({"A": range(4)}, index=idx)

    aligned = signal_align(raw, "1d", basepoint="last", end_session_skip=False)

    assert list(aligned["A"]) == [1, 3]
    assert list(aligned.index.get_level_values("_SIGNAL@DAY1")) == [
        pd.Timestamp("2026-01-01"),
        pd.Timestamp("2026-01-02"),
    ]


def test_signal_align_skips_zero_frequency_candidates_without_dividing_by_zero():
    times = pd.DatetimeIndex(["2026-01-01", "2026-01-02"], name="1d")
    zero_level = pd.DatetimeIndex(["2026-01-01", "2026-01-01"], name="0")
    idx = pd.MultiIndex.from_arrays([zero_level, times], names=["0", "1d"])
    raw = pd.DataFrame({"A": [10, 20]}, index=idx)

    aligned = signal_align(raw, "1d", basepoint="last", end_session_skip=False)

    assert list(aligned["A"]) == [10, 20]
