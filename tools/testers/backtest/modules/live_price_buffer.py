"""Amortized storage for legacy live-factor price tables.

Legacy factors receive a pandas ``DataFrame`` on SIGNAL.  Repeatedly using
``pd.concat([old_table, one_row])`` makes a one-row-per-signal replay copy the
whole history on every step.  This buffer grows its NumPy storage in chunks
and exposes a pandas view of only the populated rows.  Pandas' copy-on-write
semantics keep a factor's normal DataFrame operations from mutating the
append-only backing store.

Timezone-aware indexes use the compatibility path because a fixed
``datetime64[ns]`` array cannot retain their timezone without rebuilding the
index.  FactorTester event timestamps are normally naive, so the fast path
covers the native replay while preserving the old behavior for other callers.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

import numpy as np
import pandas as pd

from .causal_bar import CausalBar


class LivePriceTableBuffer:
    """Append visible causal bars and expose a DataFrame snapshot."""

    _INITIAL_CAPACITY = 1024

    def __init__(self, table: pd.DataFrame | None = None) -> None:
        self._columns: list[Any] = []
        self._column_positions: dict[Any, int] = {}
        self._values = np.empty((0, 0), dtype=float)
        self._time_dtype = np.dtype("datetime64[ns]")
        self._times = np.empty(0, dtype=self._time_dtype)
        self._start = 0
        self._length = 0
        self._timestamps: set[pd.Timestamp] = set()
        self._index_name: Any = None
        self._columns_name: Any = None
        self._fast = True
        self._slow_table: pd.DataFrame | None = None
        if table is not None:
            self._load_table(table)

    def append(
        self,
        bars: Sequence[CausalBar],
        *,
        lookback_bars: int | None = None,
    ) -> pd.DataFrame:
        """Append bars, preserving last-write-wins duplicate timestamp rules."""

        if lookback_bars is not None and lookback_bars <= 0:
            raise ValueError("live lookback bars must be positive")
        if not bars:
            return self.frame()
        if not self._fast:
            return self._append_slow(bars, lookback_bars=lookback_bars)

        if any(bar.bar_end in self._timestamps for bar in bars):
            # A duplicate existing timestamp must move to the last position,
            # matching DataFrame.drop_duplicates(keep="last").  This is rare
            # (normally only a corrected/replayed bar), so retain the exact
            # compatibility implementation for that case.
            return self._append_slow(bars, lookback_bars=lookback_bars)

        self._upgrade_time_dtype_if_needed(bars)
        self._ensure_columns(bars)
        self._ensure_capacity(self._length + len(bars))
        for bar in bars:
            row = self._length
            for column, value in bar.values.items():
                self._values[row, self._column_positions[column]] = float(value)
            self._times[row] = bar.bar_end.to_datetime64()
            self._timestamps.add(bar.bar_end)
            self._length += 1
        if lookback_bars is not None:
            self._trim_to_lookback_bars(lookback_bars)
        return self.frame()

    def frame(self) -> pd.DataFrame:
        """Return the current logical table without copying populated values."""

        if not self._fast:
            if self._slow_table is None:
                return pd.DataFrame()
            return self._slow_table
        index = pd.DatetimeIndex(
            self._times[self._start:self._length], copy=False
        )
        index.name = self._index_name
        frame = pd.DataFrame(
            self._values[self._start:self._length],
            index=index,
            columns=self._columns,
            copy=False,
        )
        frame.columns.name = self._columns_name
        return frame

    def _append_slow(
        self,
        bars: Sequence[CausalBar],
        *,
        lookback_bars: int | None = None,
    ) -> pd.DataFrame:
        pending = pd.DataFrame(
            [dict(bar.values) for bar in bars],
            index=pd.DatetimeIndex([bar.bar_end for bar in bars]),
        )
        pending = pending.iloc[~pending.index.duplicated(keep="last")]
        current = self.frame()
        if current.empty and not len(current.columns):
            merged = pending
        else:
            merged = pd.concat([current, pending])
            merged = merged.iloc[~merged.index.duplicated(keep="last")]
        self._load_table(merged)
        if lookback_bars is not None:
            if self._fast:
                self._trim_to_lookback_bars(lookback_bars)
            elif self._slow_table is not None:
                self._slow_table = self._slow_table.iloc[-lookback_bars:]
                self._length = len(self._slow_table)
                self._timestamps = {
                    pd.Timestamp(timestamp) for timestamp in self._slow_table.index
                }
        return self.frame()

    def _load_table(self, table: pd.DataFrame) -> None:
        self._index_name = table.index.name
        self._columns_name = table.columns.name
        self._columns = list(table.columns)
        self._column_positions = {
            column: position for position, column in enumerate(self._columns)
        }
        self._length = len(table)
        self._start = 0
        self._timestamps = {
            pd.Timestamp(timestamp) for timestamp in table.index
        }
        timezone = getattr(table.index, "tz", None)
        self._fast = isinstance(table.index, pd.DatetimeIndex) and timezone is None
        if not self._fast:
            self._slow_table = table
            self._values = np.empty((0, 0), dtype=float)
            self._time_dtype = np.dtype("datetime64[ns]")
            self._times = np.empty(0, dtype=self._time_dtype)
            return

        capacity = max(self._INITIAL_CAPACITY, self._length)
        self._values = np.full(
            (capacity, len(self._columns)), np.nan, dtype=float
        )
        if self._length:
            self._values[:self._length] = table.to_numpy(dtype=float, copy=False)
        self._time_dtype = np.dtype(table.index.to_numpy().dtype)
        self._times = np.empty(capacity, dtype=self._time_dtype)
        if self._length:
            self._times[:self._length] = table.index.to_numpy(
                dtype=self._time_dtype, copy=True
            )
        self._slow_table = None

    def _trim_to_lookback_bars(self, lookback_bars: int) -> None:
        """Keep exactly the last resolved number of logical bars."""

        if lookback_bars <= 0:
            raise ValueError("live lookback bars must be positive")
        active_times = self._times[self._start:self._length]
        active_length = len(active_times)
        if active_length <= lookback_bars:
            return
        removed_end = self._length - lookback_bars
        for timestamp in self._times[self._start:removed_end]:
            self._timestamps.discard(pd.Timestamp(timestamp))
        self._start = removed_end

    def _ensure_columns(self, bars: Iterable[CausalBar]) -> None:
        new_columns = [
            column
            for bar in bars
            for column in bar.values
            if column not in self._column_positions
        ]
        if not new_columns:
            return
        # Preserve first-seen column order, as pandas concat does.
        new_columns = list(dict.fromkeys(new_columns))
        old_width = len(self._columns)
        self._columns.extend(new_columns)
        self._column_positions.update({
            column: old_width + offset
            for offset, column in enumerate(new_columns)
        })
        expanded = np.full(
            (len(self._values), len(self._columns)), np.nan, dtype=float
        )
        if self._length and old_width:
            expanded[:self._length, :old_width] = self._values[:self._length]
        self._values = expanded

    def _upgrade_time_dtype_if_needed(self, bars: Sequence[CausalBar]) -> None:
        """Preserve pandas' timestamp resolution when a finer bar appears."""

        if not bars:
            return
        requested = max(
            (np.dtype(bar.bar_end.asm8.dtype) for bar in bars),
            key=lambda dtype: np.datetime_data(dtype)[0] == "ns",
        )
        if requested.kind != "M":
            return
        current_unit = np.datetime_data(self._time_dtype)[0]
        requested_unit = np.datetime_data(requested)[0]
        if self._length == 0 and not self._timestamps:
            if current_unit != requested_unit:
                self._time_dtype = requested
                self._times = np.empty(len(self._times), dtype=requested)
            return
        # ``datetime64[ns]`` is finer than ``datetime64[us]``.  Avoid a
        # lossy downgrade, but upgrade the backing array when a nanosecond bar
        # arrives after a microsecond-only history.
        if current_unit == requested_unit or current_unit == "ns":
            return
        if current_unit == "us" and requested_unit == "ns":
            times = np.empty(len(self._times), dtype=requested)
            if self._length:
                times[:self._length] = self._times[:self._length]
            self._times = times
            self._time_dtype = requested

    def _ensure_capacity(self, required: int) -> None:
        if required <= len(self._values):
            return
        if self._start:
            active_length = self._length - self._start
            values = np.full_like(self._values, np.nan)
            values[:active_length] = self._values[self._start:self._length]
            times = np.empty_like(self._times)
            times[:active_length] = self._times[self._start:self._length]
            self._values = values
            self._times = times
            self._length = active_length
            self._start = 0
            if required <= len(self._values):
                return
        capacity = max(
            self._INITIAL_CAPACITY,
            len(self._values) * 2,
            required,
        )
        expanded = np.full(
            (capacity, len(self._columns)), np.nan, dtype=float
        )
        if self._length:
            expanded[:self._length] = self._values[:self._length]
        self._values = expanded
        times = np.empty(capacity, dtype=self._time_dtype)
        if self._length:
            times[:self._length] = self._times[:self._length]
        self._times = times
