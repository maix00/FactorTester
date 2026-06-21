"""General strategy actors that translate factor signals into portfolio intent."""

from __future__ import annotations

from collections.abc import Callable

import numpy as np

from ..event_driven.contracts import PortfolioIntent, TargetKind
from ..event_driven.runtime import EventDraft, EventEnvelope, EventRuntime, EventTopic
from ..factors.events import FactorSignal


class SignalStrategy:
    """Translate factor signals into targets without touching orders or state."""

    def __init__(
        self,
        strategy_id: str,
        portfolio_id: str,
        instruments: tuple[str, ...],
        target_builder: Callable[[FactorSignal], np.ndarray],
    ) -> None:
        if not strategy_id or not portfolio_id:
            raise ValueError("strategy_id and portfolio_id must not be empty")
        self.strategy_id = strategy_id
        self.portfolio_id = portfolio_id
        self.instruments = instruments
        self._target_builder = target_builder

    def on_factor_signal(
        self, event: EventEnvelope, runtime: EventRuntime
    ) -> EventDraft:
        signal = event.payload
        if not isinstance(signal, FactorSignal):
            raise TypeError("factor.signal payload must be FactorSignal")
        intent = PortfolioIntent(
            timestamp=event.timestamp,
            strategy_id=self.strategy_id,
            portfolio_id=self.portfolio_id,
            target_kind=TargetKind.QUANTITY,
            values=self._target_builder(signal),
            instruments=self.instruments,
        )
        return EventDraft(EventTopic.PORTFOLIO_INTENT, event.timestamp, intent)
