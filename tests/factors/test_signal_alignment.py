from __future__ import annotations

import pandas as pd

from tools.factors.FactorExpr import signal_align


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
