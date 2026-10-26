"""Scope definitions shared by groupby and signal alignment."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class TradingDayScope:
    pass


@dataclass(frozen=True, slots=True)
class TradingSession:
    """One authoritative exchange session, labelled by trading day."""
    start_ns: int
    end_ns: int
    trading_day: object = None

    def __post_init__(self):
        if self.end_ns <= self.start_ns:
            raise ValueError("session end must follow session start")


@dataclass(frozen=True)
class SessionScope:
    """Session partitions come from the frozen trading calendar, not a gap."""

    sessions: tuple[TradingSession, ...]

    def __post_init__(self):
        if not self.sessions:
            raise ValueError("SessionScope requires at least one trading session")

    def session_index_at(self, timestamp_ns: int) -> int:
        starts = [session.start_ns for session in self.sessions]
        index = max(0, pd.Series(starts).searchsorted(int(timestamp_ns), side="right") - 1)
        if int(timestamp_ns) < self.sessions[index].start_ns or int(timestamp_ns) > self.sessions[index].end_ns:
            raise ValueError("timestamp is outside the frozen session calendar")
        return index


def scope_trading_day() -> TradingDayScope:
    return TradingDayScope()


def scope_session(sessions) -> SessionScope:
    return SessionScope(tuple(sessions))
