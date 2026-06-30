"""Shared MultiIndex-aware row/timestamp lookups for engine tables.

Real market data carries a (trading_day, ..., trade_time) MultiIndex --
trading_day exists because a night-session bar's calendar date differs from
its trading day, and `tools.data.types.time_index.DataIndex` already knows
how to find the actual signal/timestamp level regardless of how many other
levels are present. Tables here are never flattened to a scalar
DatetimeIndex -- this module centralises the "look up the row matching this
event timestamp" logic against the original MultiIndex (or a plain
DatetimeIndex, transparently) so callers don't reimplement level detection.
"""

from __future__ import annotations

import pandas as pd

from tools.data.types.time_index import DataIndex


def signal_timestamps(table: pd.DataFrame | pd.Series) -> pd.DatetimeIndex:
    """The flat, tz-aware DatetimeIndex of actual event timestamps for
    `table` -- the signal/trade_time level when `table.index` is a
    MultiIndex, or the index itself otherwise."""
    return DataIndex(table.index).signal_index


def row_at(table: pd.DataFrame, timestamp: pd.Timestamp, *, asof: bool = False) -> pd.Series:
    """Row matching `timestamp` against `table`'s signal time level.

    Tolerates a MultiIndex with any number of extra levels (trading_day,
    contract scope, etc.) -- exact match by default; `asof=True` returns the
    last row at or before `timestamp` (used where the schedule doesn't
    always land exactly on a real bar, e.g. session-boundary gaps).
    """
    data_index = DataIndex(table.index)
    if not data_index.is_multi:
        ts = data_index.tz_align(timestamp)
        if ts in data_index.signal_index:
            return table.loc[ts]
        if not asof:
            raise KeyError(timestamp)
        row = table.asof(ts)
        if row.isna().all():
            raise KeyError(f"no row at or before {ts!r}")
        return row

    if not asof and not data_index.contains(timestamp):
        raise KeyError(timestamp)
    value = data_index.asof_value(timestamp)
    selected = table.xs(value, level=data_index.level_for_xs)
    # .xs with one MultiIndex level fixed still returns a DataFrame (not a
    # Series) whenever other levels remain -- even when exactly one row
    # matches the signal timestamp, since those remaining levels (trading_day,
    # contract scope, ...) stay as the result's index. Squeeze to that row.
    if isinstance(selected, pd.DataFrame):
        if len(selected) != 1:
            raise KeyError(f"ambiguous row(s) for timestamp={value!r}: {len(selected)} matches")
        selected = selected.iloc[0]
    return selected


def timestamp_in_table(table: pd.DataFrame | pd.Series, timestamp: pd.Timestamp) -> bool:
    """Whether `timestamp` matches an actual row via the signal time level."""
    return DataIndex(table.index).contains(timestamp)


def series_up_to(series: pd.Series, timestamp: pd.Timestamp) -> pd.Series:
    """`series` restricted to rows at or before `timestamp`, ordered by the
    signal time level (works whether `series.index` is a plain DatetimeIndex
    or a (trading_day, ..., trade_time) MultiIndex)."""
    data_index = DataIndex(series.index)
    ts = data_index.tz_align(timestamp)
    sig = data_index.signal_index
    order = sig.argsort()
    mask = sig[order] <= ts
    return series.iloc[order[mask]]
