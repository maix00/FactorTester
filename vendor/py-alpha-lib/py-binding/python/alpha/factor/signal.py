"""Causal signal alignment for nested factors."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .core import FactorExpr
from .scopes import SessionScope, TradingDayScope


class SignalAlign(FactorExpr):
    """Resample a factor to a lower signal frequency without look-ahead.

    The signal at target time ``t`` is the last source value with
    ``source_time <= t``; no future value is ever used.
    """

    def __init__(
        self,
        child: FactorExpr,
        signal_freq: str,
        scope=None,
        basepoint: str = "last",
        scope_anchor: str = "start",
        daily_basepoint: str | None = None,
        end_session_skip: bool = False,
        end_session_gap: str | None = None,
        include_current: bool = True,
        partial: str = "drop",
    ):
        if basepoint not in {"last", "first"}:
            raise ValueError("basepoint must be 'last' or 'first'")
        if daily_basepoint is not None and not str(daily_basepoint).count(":"):
            raise ValueError("daily_basepoint must be a time of day")
        if daily_basepoint is not None:
            scope_anchor = str(daily_basepoint)
        if scope_anchor not in {"start", "end"} and not str(scope_anchor).count(":"):
            raise ValueError("scope_anchor must be 'start', 'end', or a time of day")
        if partial not in {"drop", "emit"}:
            raise ValueError("partial must be 'drop' or 'emit'")
        self.child = child
        self.signal_freq = str(signal_freq)
        self.scope = scope
        self.scope_anchor = str(scope_anchor)
        self.partial = partial
        self.basepoint = basepoint
        self.daily_basepoint = daily_basepoint
        self.end_session_skip = end_session_skip
        self.end_session_gap = end_session_gap
        self.include_current = include_current

    def _structural_key(self):
        return ("alpha.factor.SignalAlign", self.signal_freq,
                type(self.scope).__name__ if self.scope is not None else None,
                self.scope_anchor, self.partial, self.basepoint,
                self.daily_basepoint, self.end_session_skip, self.end_session_gap,
                self.include_current, self.child._structural_key())

    def _target_times(self, times: pd.DatetimeIndex, ctx) -> pd.DatetimeIndex:
        def daily_grid(start, end):
            anchor = self.scope_anchor
            if anchor == "end":
                return pd.date_range(end=end.floor(self.signal_freq), start=start, freq=self.signal_freq)
            if anchor != "start":
                clock = pd.Timestamp(anchor).time()
                offset = pd.Timedelta(hours=clock.hour, minutes=clock.minute, seconds=clock.second)
                first = start.normalize() + offset
                if first < start:
                    first += pd.Timedelta(days=1)
                return pd.date_range(first, end, freq=self.signal_freq)
            return pd.date_range(start.ceil(self.signal_freq), end, freq=self.signal_freq)

        if self.scope is None:
            return daily_grid(times[0], times[-1])
        if isinstance(self.scope, TradingDayScope):
            days = ctx.trading_days if ctx.trading_days is not None else times.normalize()
            groups: dict[object, list[int]] = {}
            for position, day in enumerate(days):
                groups.setdefault(day, []).append(position)
            targets = []
            for positions in groups.values():
                start, end = times[positions[0]], times[positions[-1]]
                grid = daily_grid(start, end)
                targets.extend(grid.tolist())
                if self.partial == "emit" and (not grid.empty and grid[-1] < end):
                    targets.append(end)
            return pd.DatetimeIndex(sorted(targets))
        if isinstance(self.scope, SessionScope):
            sessions = self.scope.sessions
            session_index = 0
            groups: dict[int, list[int]] = {}
            for position, timestamp in enumerate(times):
                while session_index + 1 < len(sessions) and timestamp > pd.Timestamp(sessions[session_index].end_ns, tz=timestamp.tz):
                    session_index += 1
                if timestamp < pd.Timestamp(sessions[session_index].start_ns, tz=timestamp.tz) or timestamp > pd.Timestamp(sessions[session_index].end_ns, tz=timestamp.tz):
                    raise ValueError("bar falls outside the frozen session calendar")
                groups.setdefault(session_index, []).append(position)
            targets = []
            for positions in groups.values():
                start, end = times[positions[0]], times[positions[-1]]
                grid = daily_grid(start, end)
                targets.extend(grid.tolist())
                if self.partial == "emit" and (not grid.empty and grid[-1] < end):
                    targets.append(end)
            return pd.DatetimeIndex(sorted(targets))
        raise TypeError(f"unsupported SignalAlign scope {type(self.scope).__name__}")

    def evaluate(self, ctx) -> pd.DataFrame:
        source = self.child.evaluate(ctx)
        if isinstance(source.index, pd.MultiIndex):
            signal_levels = [
                index for index, name in enumerate(source.index.names)
                if str(name).startswith("_SIGNAL@")
            ]
            if not signal_levels:
                raise TypeError("nested SignalAlign requires a _SIGNAL@ level")
            times = pd.DatetimeIndex(
                source.index.get_level_values(signal_levels[-1]),
            )
        elif isinstance(source.index, pd.DatetimeIndex):
            times = source.index
        else:
            raise TypeError("SignalAlign requires a DatetimeIndex source")
        target = self._target_times(times, ctx)
        from alpha import BatchPlan
        source_ns = times.as_unit("ns").asi8
        target_ns = target.as_unit("ns").asi8
        if self.basepoint == "first":
            previous = np.concatenate(([target_ns[0] - 1], target_ns[:-1]))
            positions = np.searchsorted(source_ns, previous, side="right")
            valid_first = positions < len(source_ns)
            positions = np.where(
                valid_first & (source_ns[np.clip(positions, 0, max(len(source_ns) - 1, 0))] <= target_ns)
                if len(source_ns) else np.zeros_like(target_ns, dtype=bool),
                positions, -1,
            )
        elif not self.include_current:
            positions = np.searchsorted(source_ns, target_ns, side="left") - 1
        else:
            positions = BatchPlan.asof_indices(source_ns, target_ns)
        positions = np.asarray(positions, dtype=np.int64)
        valid = positions >= 0
        out = {}
        for product in source.columns:
            values = source[product].to_numpy(dtype=float)
            aligned = np.full(len(positions), np.nan, dtype=float)
            aligned[valid] = values[positions[valid]]
            out[product] = aligned
        return pd.DataFrame(out, index=target)


def _method(self, signal_freq: str, scope=None, basepoint: str = "last", **kwargs):
    # Older callers passed basepoint positionally as the third argument.
    if isinstance(scope, str) and scope in {"last", "first"}:
        basepoint, scope = scope, None
    return SignalAlign(self, signal_freq, scope, basepoint, **kwargs)


FactorExpr.signal_align = _method
