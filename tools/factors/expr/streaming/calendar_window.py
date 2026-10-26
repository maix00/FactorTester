"""Trading-calendar windows for session-spanning minute-bar factors.

``N:250d`` means every minute bar in the 250 trading sessions ending at the
current session.  The number of minute bars is not constant: day sessions,
night sessions, half days and product-specific calendars differ.  This module
keeps that semantic in TradeResearch; Nautilus remains an execution adapter.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TradingSession:
    """One authoritative exchange session, labelled by its trading day."""

    trading_day: object
    start_ns: int
    end_ns: int
    bar_count: int

    def __post_init__(self) -> None:
        if self.end_ns <= self.start_ns:
            raise ValueError("session end must follow session start")
        if self.bar_count < 0:
            raise ValueError("session bar count must be non-negative")


class TradingCalendarWindow:
    """Map a session lookback to the exact minute-bar window size."""

    def __init__(self, sessions: tuple[TradingSession, ...]) -> None:
        if not sessions:
            raise ValueError("at least one trading session is required")
        ordered = tuple(sorted(sessions, key=lambda item: item.start_ns))
        for previous, current in zip(ordered, ordered[1:]):
            if current.start_ns < previous.end_ns:
                raise ValueError("trading sessions must not overlap")
        self.sessions = ordered
        self._starts = tuple(item.start_ns for item in ordered)
        cumulative = [0]
        for session in ordered:
            cumulative.append(cumulative[-1] + session.bar_count)
        self._cumulative = tuple(cumulative)

    def session_index(self, timestamp_ns: int) -> int:
        """Return the session containing ``timestamp_ns`` (bar end inclusive)."""
        index = bisect_right(self._starts, int(timestamp_ns)) - 1
        if index < 0 or int(timestamp_ns) > self.sessions[index].end_ns:
            raise ValueError("timestamp is outside the frozen trading calendar")
        return index

    def window_size(self, current_session: int, lookback_sessions: int) -> int:
        """Return the minute bars in the last ``lookback_sessions`` sessions."""
        if not isinstance(lookback_sessions, int) or lookback_sessions <= 0:
            raise ValueError("lookback_sessions must be a positive integer")
        if not 0 <= current_session < len(self.sessions):
            raise ValueError("current session index is out of range")
        start = max(0, current_session - lookback_sessions + 1)
        return self._cumulative[current_session + 1] - self._cumulative[start]

    @classmethod
    def from_bars(cls, bars: object) -> "TradingCalendarWindow":
        """Build sessions from source bars grouped by authoritative trading day.

        Night and day bars sharing one trading day form one session: the
        session opens at the earliest night open and closes at the latest day
        close.  Calendar dates alone are never used to derive the day.
        """
        grouped: dict[object, list[tuple[int, int]]] = {}
        for bar in bars:
            day = getattr(bar, "trading_day", None)
            clock = getattr(bar, "clock", None)
            if day is None or clock is None:
                raise ValueError("bars need trading_day and clock fields")
            grouped.setdefault(day, []).append(
                (int(clock.interval_open_ns), int(clock.interval_end_ns))
            )
        if not grouped:
            raise ValueError("bars contain no trading sessions")
        sessions: list[TradingSession] = []
        for day, intervals in grouped.items():
            start = min(item[0] for item in intervals)
            end = max(item[1] for item in intervals)
            sessions.append(TradingSession(day, start, end, len(intervals)))
        return cls(tuple(sorted(sessions, key=lambda item: item.start_ns)))

    def max_window_size(self, lookback_sessions: int) -> int:
        """Largest minute-bar window over all frozen sessions."""
        if not isinstance(lookback_sessions, int) or lookback_sessions <= 0:
            raise ValueError("lookback_sessions must be a positive integer")
        return max(
            self.window_size(index, lookback_sessions)
            for index in range(len(self.sessions))
        )

    def window_for_timestamp(
        self, timestamp_ns: int, lookback_sessions: int,
    ) -> tuple[int, int]:
        """Return ``(session_index, window_size)`` for a bar timestamp."""
        index = self.session_index(timestamp_ns)
        return index, self.window_size(index, lookback_sessions)

    def eviction_session(self, current_session: int, lookback_sessions: int) -> int | None:
        """First session no longer included in the window, if any."""
        if not 0 <= current_session < len(self.sessions):
            raise ValueError("current session index is out of range")
        start = current_session - lookback_sessions + 1
        return start - 1 if start > 0 else None
