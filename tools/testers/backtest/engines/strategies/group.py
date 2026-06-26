"""Cross-sectional group testing expressed as independent strategies."""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pandas as pd

from ..native.contracts import PortfolioIntent, TargetKind
from ..native.runtime import EventDraft, EventEnvelope, EventRuntime, EventTopic
from ..factors.events import FactorSignal
from .allocation import AllocationInput, WeightAllocator
from .rebalance import RebalanceTrigger


class QuantileGroupStrategy:
    """One quantile group, one strategy identity, and one virtual portfolio."""

    def __init__(
        self,
        *,
        factor_alias: str,
        strategy_id: str,
        portfolio_id: str,
        instruments: tuple[str, ...],
        group_number: int,
        group_count: int,
        allocator: WeightAllocator,
        allocation_inputs: Callable[[pd.Timestamp, np.ndarray], AllocationInput],
        rebalance_trigger: RebalanceTrigger,
    ) -> None:
        if not 1 <= group_number <= group_count:
            raise ValueError("group_number must be within 1..group_count")
        self.factor_alias = factor_alias
        self.strategy_id = strategy_id
        self.portfolio_id = portfolio_id
        self.instruments = instruments
        self.group_number = group_number
        self.group_count = group_count
        self.allocator = allocator
        self.allocation_inputs = allocation_inputs
        self.rebalance_trigger = rebalance_trigger

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
        groups = np.array_split(np.asarray([item[0] for item in ranked], dtype=object), self.group_count)
        selected_names = set(groups[self.group_number - 1].tolist())
        selected = np.asarray([
            instrument in selected_names for instrument in self.instruments
        ], dtype=bool)
        if not self.rebalance_trigger.should_rebalance(event.timestamp, selected):
            return None
        weights = self.allocator.allocate(
            self.allocation_inputs(event.timestamp, selected)
        )
        intent = PortfolioIntent(
            timestamp=event.timestamp,
            strategy_id=self.strategy_id,
            portfolio_id=self.portfolio_id,
            target_kind=TargetKind.WEIGHT,
            values=weights,
            instruments=self.instruments,
        )
        return EventDraft(EventTopic.PORTFOLIO_INTENT, event.timestamp, intent)
