from __future__ import annotations

import pandas as pd

from tools.factors.FactorExpr import signal_align


def test_signal_align_uses_last_bar_of_each_fixed_window():
    idx = pd.date_range("2026-01-01 09:01", periods=10, freq="min", name="1m")
    raw = pd.DataFrame({"A": range(10)}, index=idx)

    aligned = signal_align(raw, "5m", basepoint="last", end_session_skip=False)

    assert list(aligned["A"]) == [4, 9]
    assert list(aligned.index.get_level_values("_SIGNAL@MIN5")) == [idx[4], idx[9]]


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
