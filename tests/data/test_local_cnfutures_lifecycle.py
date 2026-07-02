"""_last_valid_timestamp must work for both plain DatetimeIndex market data
and _SIGNAL@-prefixed MultiIndex market data -- indexing a MultiIndex with
[-1] returns a tuple of level values, not a scalar Timestamp, and feeding
that into pd.Timestamp(...) raises "Cannot convert input ... of type
<class 'tuple'>". This is the last-resort lifecycle-inference fallback
TermStructureExpandModule's force-close/rollover notice registration calls
when a contract has no lifecycle dates of its own and isn't found in the
OpenCTP/AKShare catalogs -- so a crash here surfaces deep inside "登记交割
强平通知", far from this file."""

from __future__ import annotations

import pandas as pd

from sources.LocalCNFutures.lifecycle import _last_valid_timestamp, infer_contract_end_from_coverage


def test_last_valid_timestamp_on_plain_datetime_index():
    idx = pd.DatetimeIndex(["2026-01-28", "2026-01-29", "2026-01-30"])
    series = pd.Series([1.0, 2.0, 3.0], index=idx)
    assert _last_valid_timestamp(series) == pd.Timestamp("2026-01-30")


def test_last_valid_timestamp_ignores_trailing_nan():
    idx = pd.DatetimeIndex(["2026-01-28", "2026-01-29", "2026-01-30"])
    series = pd.Series([1.0, 2.0, float("nan")], index=idx)
    assert _last_valid_timestamp(series) == pd.Timestamp("2026-01-29")


def test_last_valid_timestamp_on_signal_multiindex():
    """The regression case: a MultiIndex with a trading-day level and a
    _SIGNAL@-prefixed event-time level, like custom/exact engine mode market
    data can carry. [-1] on such an index is a tuple; must resolve to just
    the signal time level instead."""
    idx = pd.MultiIndex.from_tuples(
        [
            (pd.Timestamp("2026-01-29"), pd.Timestamp("2026-01-29 15:00", tz="Asia/Shanghai")),
            (pd.Timestamp("2026-01-30"), pd.Timestamp("2026-01-30 15:00", tz="Asia/Shanghai")),
        ],
        names=["trading_day", "_SIGNAL@MIN1"],
    )
    series = pd.Series([1.0, 2.0], index=idx)
    result = _last_valid_timestamp(series)
    assert result == pd.Timestamp("2026-01-30 15:00", tz="Asia/Shanghai")


def test_infer_contract_end_from_coverage_handles_multiindex_market_data():
    idx = pd.MultiIndex.from_tuples(
        [
            (pd.Timestamp("2026-01-29"), pd.Timestamp("2026-01-29 15:00", tz="Asia/Shanghai")),
            (pd.Timestamp("2026-01-30"), pd.Timestamp("2026-01-30 15:00", tz="Asia/Shanghai")),
            (pd.Timestamp("2026-01-31"), pd.Timestamp("2026-01-31 15:00", tz="Asia/Shanghai")),
        ],
        names=["trading_day", "_SIGNAL@MIN1"],
    )
    raw_prices = pd.DataFrame({
        "P2601.DCE": [10.0, 10.5, float("nan")],
        "P2602.DCE": [11.0, 11.5, 12.0],
    }, index=idx)
    row = {"contract": "P2601", "uid": "P2601.DCE"}
    peer_row = {"contract": "P2602", "uid": "P2602.DCE"}

    result = infer_contract_end_from_coverage(row, [row, peer_row], raw_prices)

    assert result["status"] == "ended"
    assert result["timestamp"] == pd.Timestamp("2026-01-30 15:00", tz="Asia/Shanghai")
