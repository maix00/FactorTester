"""Nautilus bar/instrument events as TradeResearch interval boundaries.

Nautilus supplies the event clock (completed bars and instrument-status
events).  TradeResearch supplies the authoritative trading-day/session
calendar.  This adapter records the latest occurrence of each event as a bar
ordinal; it does not derive a trading day from a calendar date.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd


@dataclass(slots=True)
class NautilusEventTimeline:
    calendar: Any | None = None
    bar_ordinal: int = 0
    latest: dict[str, int] = field(default_factory=dict)
    _trading_day: Any | None = None
    _session: int | None = None

    def on_bar(self, bar: Any, *, trading_day: Any | None = None) -> None:
        self.bar_ordinal += 1
        ts_ns = int(getattr(bar, "ts_init", getattr(bar, "ts_event", 0)))
        day = trading_day
        session = None
        if self.calendar is not None:
            session, _size = self.calendar.window_for_timestamp(ts_ns, 1)
            if day is None:
                day = self.calendar.sessions[session].trading_day
        if day is not None and day != self._trading_day:
            self._trading_day = day
            self.latest["trading_day_start"] = self.bar_ordinal
        if session is not None and session != self._session:
            self._session = session
            self.latest["session_start"] = self.bar_ordinal
        self.latest["bar"] = self.bar_ordinal

    def on_instrument_status(
        self, status: Any, *, instrument_id: Any | None = None,
    ) -> None:
        """Record a Nautilus instrument status change (halt/resume/close)."""
        name = str(getattr(status, "name", status))
        self.latest[f"instrument_status:{name}"] = self.bar_ordinal
        if instrument_id is not None:
            self.latest[f"instrument_status:{instrument_id}:{name}"] = self.bar_ordinal

    def on_roll(self, trade_date: Any) -> None:
        """Record a contract-roll event supplied by the strategy/data layer."""
        self.latest["contract_roll"] = self.bar_ordinal
        self.latest[f"contract_roll:{pd.Timestamp(trade_date).date()}"] = self.bar_ordinal

    def latest_occurrence(self, event: str) -> int | None:
        return self.latest.get(event)
