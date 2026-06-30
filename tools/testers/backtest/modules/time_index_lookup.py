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

from dataclasses import dataclass
from typing import Any, cast

import pandas as pd

from tools.data.types.time_index import DataIndex


@dataclass(frozen=True)
class IndexEventTime:
    timestamp: pd.Timestamp
    index_key: Any
    index_names: tuple[Any, ...]


def signal_timestamps(table: pd.DataFrame | pd.Series) -> pd.DatetimeIndex:
    """Flat event timestamps for `table`.

    Event replay uses the finest/last index level as the actual event time.
    Extra MultiIndex levels such as trading_day remain part of the event
    identity via `signal_event_times`.
    """
    return DataIndex(table.index).finest_index


def signal_event_times(table: pd.DataFrame | pd.Series) -> list[IndexEventTime]:
    """Return replay event keys from the table's original index.

    For MultiIndex tables the timestamp is the last level, while `index_key`
    preserves the full index row (trading_day, contract month, trade_time,
    etc.). This keeps night-session trading-day semantics attached to the
    event instead of flattening everything to one timestamp column.
    """
    index = table.index
    if isinstance(index, pd.MultiIndex):
        names = tuple(index.names)
        timestamps = pd.DatetimeIndex(index.get_level_values(-1))
        return [
            IndexEventTime(cast(pd.Timestamp, pd.Timestamp(timestamp)), tuple(key), names)
            for timestamp, key in zip(timestamps, index.tolist(), strict=True)
        ]
    timestamps = pd.DatetimeIndex(index)
    names = (index.name,)
    return [
        IndexEventTime(cast(pd.Timestamp, pd.Timestamp(timestamp)), cast(pd.Timestamp, pd.Timestamp(timestamp)), names)
        for timestamp in timestamps
    ]


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
        row = cast(pd.Series, table.asof(ts))
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


def row_at_index_key(table: pd.DataFrame, index_key: Any) -> pd.Series:
    """Row matching the exact original index key carried by an EventDraft."""
    if not isinstance(table.index, pd.MultiIndex):
        return table.loc[pd.Timestamp(index_key)]
    key = tuple(index_key) if isinstance(index_key, tuple) else (index_key,)
    selected = table.loc[key]
    if isinstance(selected, pd.DataFrame):
        if len(selected) != 1:
            raise KeyError(f"ambiguous row(s) for index_key={key!r}: {len(selected)} matches")
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
