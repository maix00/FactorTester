"""FactorExpr bridge for Backtrader Strategy.next callbacks."""

from __future__ import annotations

from collections.abc import Mapping

import pandas as pd

from ...factors.events import FactorSignal
from ..factor_step import FactorStepAdapter
from ..frameworks import IncrementalFactorSource, PrecomputedFactorSource


_LINES = {
    "OPEN": "open",
    "HIGH": "high",
    "LOW": "low",
    "CLOSE": "close",
    "VOLUME": "volume",
    "OPEN_INTEREST": "openinterest",
}


class BacktraderFactorAdapter:
    """Read Backtrader data lines and execute a canonical factor source."""

    def __init__(
        self,
        factor_alias: str,
        factor_source: PrecomputedFactorSource | IncrementalFactorSource,
        instruments: tuple[str, ...],
    ) -> None:
        self.stepper = FactorStepAdapter(factor_alias, factor_source, instruments)
        unsupported = self.stepper.required_columns - _LINES.keys()
        if unsupported:
            raise ValueError(f"Backtrader factor columns are unsupported: {sorted(unsupported)}")

    def on_next(
        self,
        feeds: Mapping[str, object],
        timestamp: pd.Timestamp | None = None,
    ) -> FactorSignal:
        if set(feeds) != set(self.stepper.instruments):
            raise ValueError("Backtrader feeds do not match factor instruments")
        first_feed = feeds[self.stepper.instruments[0]]
        if timestamp is None:
            timestamp = pd.Timestamp(first_feed.datetime.datetime(0))
        fields = {
            instrument: {
                column: float(getattr(feed, _LINES[column])[0])
                for column in self.stepper.required_columns
            }
            for instrument, feed in feeds.items()
        }
        return self.stepper.update(timestamp, fields)
