"""Long-Short quantile strategy as a peer event-runtime lane."""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pandas as pd

from ..event_driven.contracts import PortfolioIntent, TargetKind
from ..event_driven.runtime import EventDraft, EventEnvelope, EventRuntime, EventTopic
from ..factors.events import FactorSignal
from .allocation import AllocationInput, WeightAllocator
from .rebalance import RebalancePolicy


class QuantileLongShortStrategy:
    def __init__(
        self,
        *,
        factor_alias: str,
        strategy_id: str,
        portfolio_id: str,
        instruments: tuple[str, ...],
        group_count: int,
        long_group_number: int,
        short_group_number: int,
        allocator: WeightAllocator,
        allocation_inputs: Callable[[pd.Timestamp, np.ndarray, float], AllocationInput],
        rebalance_policy: RebalancePolicy,
        gross_exposure: float = 1.0,
    ) -> None:
        if (
            group_count < 2
            or not 1 <= long_group_number <= group_count
            or not 1 <= short_group_number <= group_count
            or long_group_number == short_group_number
            or not 0 < gross_exposure <= 2
        ):
            raise ValueError("invalid Long-Short quantile configuration")
        self.factor_alias = factor_alias
        self.strategy_id = strategy_id
        self.portfolio_id = portfolio_id
        self.instruments = instruments
        self.group_count = group_count
        self.long_group_number = long_group_number
        self.short_group_number = short_group_number
        self.allocator = allocator
        self.allocation_inputs = allocation_inputs
        self.rebalance_policy = rebalance_policy
        self.gross_exposure = gross_exposure

    def on_factor_signal(
        self, event: EventEnvelope, runtime: EventRuntime
    ) -> EventDraft | None:
        signal = event.payload
        if not isinstance(signal, FactorSignal):
            raise TypeError("factor.signal payload must be FactorSignal")
        if signal.factor_alias != self.factor_alias:
            return None
        ranked = sorted(
            (
                (instrument, float(signal.values[instrument]))
                for instrument in self.instruments
                if np.isfinite(signal.values[instrument])
            ),
            key=lambda item: (item[1], item[0]),
        )
        groups = np.array_split(
            np.asarray([item[0] for item in ranked], dtype=object), self.group_count
        )
        long_names = set(groups[self.long_group_number - 1].tolist())
        short_names = set(groups[self.short_group_number - 1].tolist())
        long_selected = np.asarray(
            [instrument in long_names for instrument in self.instruments], dtype=bool
        )
        short_selected = np.asarray(
            [instrument in short_names for instrument in self.instruments], dtype=bool
        )
        membership = long_selected | short_selected
        if not self.rebalance_policy.should_rebalance(event.timestamp, membership):
            return None
        leg_exposure = self.gross_exposure / 2.0
        long_weights = self.allocator.allocate(
            self.allocation_inputs(event.timestamp, long_selected, leg_exposure)
        )
        short_weights = self.allocator.allocate(
            self.allocation_inputs(event.timestamp, short_selected, leg_exposure)
        )
        intent = PortfolioIntent(
            timestamp=event.timestamp,
            strategy_id=self.strategy_id,
            portfolio_id=self.portfolio_id,
            target_kind=TargetKind.WEIGHT,
            values=long_weights - short_weights,
            instruments=self.instruments,
        )
        return EventDraft(EventTopic.PORTFOLIO_INTENT, event.timestamp, intent)
