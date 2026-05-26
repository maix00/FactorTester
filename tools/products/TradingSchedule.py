from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from typing import Iterable, Optional

import pandas as pd


@dataclass(frozen=True)
class TradingSession:
    start: time
    end: time

    def contains(self, value: time) -> bool:
        if self.start <= self.end:
            return self.start <= value <= self.end
        return value >= self.start or value <= self.end


@dataclass(frozen=True)
class TradingSchedule:
    sessions: tuple[TradingSession, ...]

    @classmethod
    def from_strings(cls, *values: Optional[str]) -> Optional['TradingSchedule']:
        sessions: list[TradingSession] = []
        for value in values:
            if value is None or str(value).strip().lower() in {"", "nan", "none"}:
                continue
            for part in str(value).split(","):
                bounds = [item.strip() for item in part.strip().split("-")]
                if len(bounds) != 2:
                    raise ValueError(f"Invalid trading session interval: {part!r}")
                sessions.append(TradingSession(_parse_time(bounds[0]), _parse_time(bounds[1])))
        return cls(tuple(sessions)) if sessions else None

    def contains_timestamps(self, timestamps: Iterable[pd.Timestamp]) -> list[bool]:
        return [any(session.contains(pd.Timestamp(ts).time()) for session in self.sessions) for ts in timestamps]


def _parse_time(value: str) -> time:
    parsed = pd.Timestamp(value)
    return parsed.time()
