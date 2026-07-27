"""Clock-owned timer events and scheduling requests for native strategies."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class TimerEvent:
    """One deterministic clock notification delivered to ``on_timer``."""

    name: str
    timestamp: pd.Timestamp
    occurrence: int = 1
    generation: int = 1

    def __post_init__(self) -> None:
        if not str(self.name).strip():
            raise ValueError("timer event name must not be empty")
        object.__setattr__(self, "name", str(self.name))
        object.__setattr__(self, "timestamp", pd.Timestamp(self.timestamp))
        if self.occurrence < 1:
            raise ValueError("timer event occurrence must be positive")
        if self.generation < 1:
            raise ValueError("timer event generation must be positive")


@dataclass(frozen=True)
class TimerSchedule:
    """Immutable timer registration accepted by the scheduler."""

    name: str
    first_timestamp: pd.Timestamp
    interval: pd.Timedelta | None = None
    end_timestamp: pd.Timestamp | None = None

    def __post_init__(self) -> None:
        if not str(self.name).strip():
            raise ValueError("timer name must not be empty")
        object.__setattr__(self, "name", str(self.name))
        object.__setattr__(self, "first_timestamp", pd.Timestamp(self.first_timestamp))
        if self.interval is not None:
            interval = pd.Timedelta(self.interval)
            if interval <= pd.Timedelta(0):
                raise ValueError("timer interval must be positive")
            if self.end_timestamp is None:
                raise ValueError("recurring timer requires end_timestamp")
            object.__setattr__(self, "interval", interval)
        if self.end_timestamp is not None:
            end = pd.Timestamp(self.end_timestamp)
            if end < self.first_timestamp:
                raise ValueError("timer end_timestamp must not precede first_timestamp")
            object.__setattr__(self, "end_timestamp", end)


@dataclass(frozen=True)
class TimerCancel:
    """Immutable request to cancel one strategy-owned timer."""

    name: str

    def __post_init__(self) -> None:
        if not str(self.name).strip():
            raise ValueError("timer name must not be empty")
        object.__setattr__(self, "name", str(self.name))


TimerControl = TimerSchedule | TimerCancel
