from __future__ import annotations

import pandas as pd
import pytest

from sources.LocalCNFutures.trading_sessions import infer_trading_sessions


def _session_frame(intervals, days=10):
    rows = []
    for day in pd.date_range("2026-01-05", periods=days, freq="B"):
        for start, end in intervals:
            start_ts = pd.Timestamp(f"{day.date()} {start}")
            end_ts = pd.Timestamp(f"{day.date()} {end}")
            if end_ts < start_ts:
                end_ts += pd.Timedelta(days=1)
            for timestamp in pd.date_range(start_ts + pd.Timedelta(minutes=1), end_ts, freq="1min"):
                rows.append({"trade_time": timestamp, "trading_day": day})
    return pd.DataFrame(rows)


@pytest.mark.parametrize(
    ("night_end", "expected"),
    [(None, None), ("23:00", "21:00-23:00"), ("01:00", "21:00-01:00"), ("02:30", "21:00-02:30")],
)
def test_infer_day_and_night_sessions(night_end, expected):
    intervals = [("09:00", "10:15"), ("10:30", "11:30"), ("13:30", "15:00")]
    if night_end:
        intervals.append(("21:00", night_end))

    result = infer_trading_sessions(_session_frame(intervals), product_name="TEST.DCE")

    assert result.observed_day_sessions == "09:00-10:15, 10:30-11:30, 13:30-15:00"
    assert result.observed_night_session == expected


def test_inference_ignores_minutes_missing_on_most_days():
    frame = _session_frame([("09:00", "10:15")])
    noise = pd.DataFrame([
        {"trade_time": pd.Timestamp("2026-01-05 21:01"), "trading_day": pd.Timestamp("2026-01-05")}
    ])

    result = infer_trading_sessions(pd.concat([frame, noise], ignore_index=True))

    assert result.observed_night_session is None
