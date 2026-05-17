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
