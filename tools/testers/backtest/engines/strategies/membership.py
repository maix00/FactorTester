"""Event-time strategy actor for precomputed group-membership signals."""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np
import pandas as pd

from ..event_driven.contracts import PortfolioIntent, TargetKind
from ..event_driven.runtime import EventDraft, EventEnvelope, EventRuntime, EventTopic
from ..factors.events import FactorSignal
from ..execution.trading import MarketState
from tools.testers.settings.strategy_fields import (
    ALLOCATION_POLICY,
    POSITION_POLICY,
    REBALANCE_TRIGGER,
    required_strategy_value,
    strategy_value,
)
from .allocation import (
    AllocationInput,
    AllocationInputsUnavailable,
    EqualMarginAllocator,
    EqualNotionalAllocator,
    InverseVolatilityAllocator,
    TrailingVolatilityEstimator,
)
from .rebalance import MembershipChange, OnFactorSignal


def _target_from_weights(instruments: tuple[str, ...], weights: np.ndarray) -> dict[str, float]:
    weight_values = np.asarray(weights, dtype=float)
    active = ~np.isclose(weight_values, 0.0)
    if not np.any(active):
        return {}
    return {
        instrument: float(weight_values[index])
        for index, instrument in enumerate(instruments)
        if bool(active[index])
    }


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
        self.allocation_name = strategy_value(config, ALLOCATION_POLICY)
        self.allocator = _allocator(self.allocation_name)
        self.rebalance_trigger_name = required_strategy_value(config, REBALANCE_TRIGGER)
        self.position_policy = required_strategy_value(config, POSITION_POLICY)
        self.rebalance_trigger = _rebalance(self.rebalance_trigger_name)
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
        self.empty_leg_events: list[dict[str, object]] = []
        self._position_initialized = False

    def on_factor_signal(
        self, event: EventEnvelope, runtime: EventRuntime
    ) -> EventDraft | None:
        signal = event.payload
        if not isinstance(signal, FactorSignal):
            raise TypeError("factor.signal payload must be FactorSignal")
        current_prices = {name: float(self.market.prices[name]) for name in self.instruments}
        if self._previous_prices is not None:
            returns = np.asarray([
                current_prices[name] / self._previous_prices[name] - 1.0
                for name in self.instruments
            ], dtype=float)
            self.estimator.update_values(returns)
        self._previous_prices = current_prices
        if pd.Timestamp(event.timestamp) not in self.active_timestamps:
            return None
        signed_membership = np.asarray([
            float(signal.values.get(name, 0.0)) if np.isfinite(current_prices[name]) else 0.0
            for name in self.instruments
        ])
        selected = signed_membership != 0 if self.strategy_kind == "long_short" else signed_membership > 0
        if not self.rebalance_trigger.should_rebalance(event.timestamp, selected):
            return None
        if self.position_policy == "buy_and_hold" and self._position_initialized:
            return None
        volatilities = self.estimator.snapshot()
        if self.strategy_kind == "long_short":
            weights = self._allocate_long_short(
                event.timestamp, signed_membership, volatilities
            )
            if weights is None:
                return None
        else:
            weights = self._allocate(
                event.timestamp, selected, volatilities, gross_exposure=1.0
            )
        target = _target_from_weights(self.instruments, weights)
        self.target_trace[event.timestamp.isoformat()] = target
        if target:
            self._position_initialized = True
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
    ) -> np.ndarray | None:
        long_selected = signed_membership > 0
        short_selected = signed_membership < 0
        if not np.any(long_selected) or not np.any(short_selected):
            self.empty_leg_events.append({
                "timestamp": pd.Timestamp(timestamp).isoformat(),
                "long_count": int(np.count_nonzero(long_selected)),
                "short_count": int(np.count_nonzero(short_selected)),
            })
            return None
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
            "long_short_empty_leg_count": len(self.empty_leg_events),
            "long_short_empty_legs": self.empty_leg_events,
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
    raise ValueError(f"unsupported rebalance policy: {name}")
