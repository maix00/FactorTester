"""Event-time strategy actor for precomputed group-membership signals."""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np
import pandas as pd

from ..event_driven.contracts import PortfolioIntent, TargetKind
from ..event_driven.runtime import EventDraft, EventEnvelope, EventRuntime, EventTopic
from ..factors.events import FactorSignal
from ..execution.trading import MarketState
from .allocation import (
    AllocationInput,
    AllocationInputsUnavailable,
    EqualMarginAllocator,
    EqualNotionalAllocator,
    InverseVolatilityAllocator,
    TrailingVolatilityEstimator,
)
from .rebalance import BuyAndHold, MembershipChange, OnFactorSignal


class MembershipAllocationStrategy:
    """Calculate target weights causally inside the native event runtime."""

    def __init__(
        self,
        *,
        factor_alias: str,
        strategy_id: str,
        portfolio_id: str,
        instruments: tuple[str, ...],
        market: MarketState,
        config: Mapping[str, object],
        margin_ratios: Mapping[pd.Timestamp, Mapping[str, float]],
        active_timestamps: frozenset[pd.Timestamp],
    ) -> None:
        self.factor_alias = factor_alias
        self.strategy_id = strategy_id
        self.portfolio_id = portfolio_id
        self.instruments = instruments
        self.market = market
        self.config = dict(config)
        self.margin_ratios = margin_ratios
        self.active_timestamps = active_timestamps
        self.allocation_name = str(config.get("allocation_policy") or "inverse_volatility")
        self.allocator = _allocator(self.allocation_name)
        self.rebalance = _rebalance(str(config.get("rebalance_mode") or "on_factor_signal"))
        lookback = int(config.get("volatility_lookback") or 20)
        self.estimator = TrailingVolatilityEstimator(
            instruments,
            lookback=lookback,
            min_observations=min(
                lookback,
                max(2, int(config.get("volatility_min_observations") or 2)),
            ),
            annualization=float(config.get("volatility_annualization") or 252.0),
        )
        self._previous_prices: dict[str, float] | None = None
        self.target_trace: dict[str, dict[str, float]] = {}
        self.fallback_events: list[dict[str, object]] = []

    def on_factor_signal(
        self, event: EventEnvelope, runtime: EventRuntime
    ) -> EventDraft | None:
        signal = event.payload
        if not isinstance(signal, FactorSignal):
            raise TypeError("factor.signal payload must be FactorSignal")
        current_prices = {name: float(self.market.prices[name]) for name in self.instruments}
        if self._previous_prices is not None:
            self.estimator.update({
                name: current_prices[name] / self._previous_prices[name] - 1.0
                for name in self.instruments
            })
        self._previous_prices = current_prices
        if pd.Timestamp(event.timestamp) not in self.active_timestamps:
            return None
        selected = np.asarray([
            bool(signal.values.get(name, 0.0)) and np.isfinite(current_prices[name])
            for name in self.instruments
        ])
        if not self.rebalance.should_rebalance(event.timestamp, selected):
            return None
        volatilities = self.estimator.snapshot()
        inputs = AllocationInput(
            self.instruments,
            selected,
            volatilities=volatilities,
            margin_ratios=self.margin_ratios[pd.Timestamp(event.timestamp)],
        )
        try:
            weights = self.allocator.allocate(inputs)
        except AllocationInputsUnavailable as exc:
            if self.allocation_name != "inverse_volatility" or str(
                self.config.get("volatility_warmup") or "equal_notional"
            ) != "equal_notional":
                raise
            weights = EqualNotionalAllocator().allocate(inputs)
            self.fallback_events.append({
                "timestamp": event.timestamp.isoformat(),
                "reason": str(exc),
                "fallback_policy": "equal_notional",
                "volatilities": volatilities,
            })
        self.target_trace[event.timestamp.isoformat()] = {
            name: float(weight)
            for name, weight in zip(self.instruments, weights, strict=True)
            if not np.isclose(weight, 0.0)
        }
        return EventDraft(
            EventTopic.PORTFOLIO_INTENT,
            event.timestamp,
            PortfolioIntent(
                timestamp=event.timestamp,
                strategy_id=self.strategy_id,
                portfolio_id=self.portfolio_id,
                target_kind=TargetKind.WEIGHT,
                values=weights,
                instruments=self.instruments,
            ),
        )

    @property
    def diagnostics(self) -> dict[str, object]:
        return {
            "volatility_warmup_fallback_count": len(self.fallback_events),
            "volatility_warmup_fallbacks": self.fallback_events,
            "last_volatilities": self.estimator.snapshot(),
        }


def _allocator(name: str):
    if name == "inverse_volatility":
        return InverseVolatilityAllocator()
    if name == "equal_notional":
        return EqualNotionalAllocator()
    if name == "equal_margin":
        return EqualMarginAllocator()
    raise ValueError(f"unsupported allocation policy: {name}")


def _rebalance(name: str):
    if name == "on_factor_signal":
        return OnFactorSignal()
    if name == "membership_change":
        return MembershipChange()
    if name == "buy_and_hold":
        return BuyAndHold()
    raise ValueError(f"unsupported rebalance policy: {name}")
