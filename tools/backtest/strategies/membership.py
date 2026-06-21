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
        self.strategy_kind = str(config.get("strategy_kind") or "group")
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
        signed_membership = np.asarray([
            float(signal.values.get(name, 0.0)) if np.isfinite(current_prices[name]) else 0.0
            for name in self.instruments
        ])
        selected = signed_membership != 0 if self.strategy_kind == "long_short" else signed_membership > 0
        if not self.rebalance.should_rebalance(event.timestamp, selected):
            return None
        volatilities = self.estimator.snapshot()
        if self.strategy_kind == "long_short":
            weights = self._allocate_long_short(
                event.timestamp, signed_membership, volatilities
            )
        else:
            weights = self._allocate(
                event.timestamp, selected, volatilities, gross_exposure=1.0
            )
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

    def _allocate(
        self,
        timestamp: pd.Timestamp,
        selected: np.ndarray,
        volatilities: Mapping[str, float],
        *,
        gross_exposure: float,
        leg: str | None = None,
    ) -> np.ndarray:
        inputs = AllocationInput(
            self.instruments,
            selected,
            gross_exposure=gross_exposure,
            volatilities=volatilities,
            margin_ratios=self.margin_ratios[pd.Timestamp(timestamp)],
        )
        try:
            return self.allocator.allocate(inputs)
        except AllocationInputsUnavailable as exc:
            if self.allocation_name != "inverse_volatility" or str(
                self.config.get("volatility_warmup") or "equal_notional"
            ) != "equal_notional":
                raise
            self.fallback_events.append({
                "timestamp": timestamp.isoformat(),
                "leg": leg,
                "reason": str(exc),
                "fallback_policy": "equal_notional",
                "volatilities": volatilities,
            })
            return EqualNotionalAllocator().allocate(inputs)

    def _allocate_long_short(
        self,
        timestamp: pd.Timestamp,
        signed_membership: np.ndarray,
        volatilities: Mapping[str, float],
    ) -> np.ndarray:
        long_selected = signed_membership > 0
        short_selected = signed_membership < 0
        if not np.any(long_selected) or not np.any(short_selected):
            raise ValueError(
                f"Long-Short strategy {self.strategy_id} has an empty leg at "
                f"{timestamp.isoformat()}"
            )
        return self._allocate(
            timestamp, long_selected, volatilities, gross_exposure=0.5, leg="long"
        ) - self._allocate(
            timestamp, short_selected, volatilities, gross_exposure=0.5, leg="short"
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
