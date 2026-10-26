"""Trading-day and session partition scopes."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class TradingDayScope:
    pass


@dataclass(frozen=True)
class SessionScope:
    gap: str = "3h"

    @property
    def gap_ns(self) -> int:
        return int(pd.Timedelta(self.gap).value)


def scope_trading_day() -> TradingDayScope:
    return TradingDayScope()


def scope_session(gap: str = "3h") -> SessionScope:
    return SessionScope(gap)
