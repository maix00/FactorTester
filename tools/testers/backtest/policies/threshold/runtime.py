"""Threshold policy event adapter."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pandas as pd

from tools.testers.backtest.modules.factor import FactorModule
from tools.testers.backtest.modules.factor_signal import FactorSignalModule
from tools.testers.backtest.modules.group_membership import _record_target_trace
from tools.testers.backtest.modules.market_data import MarketDataModule
from tools.testers.backtest.modules.target import TargetStrategyModule, target_weight_intent
from tools.testers.backtest.modules.threshold_signal import ThresholdSignalModule
from tools.testers.backtest.policies.contracts import StrategyIntentPolicy

from .precompute import precompute_threshold_target_intents
from .selection import compute_threshold_target_weights
from .state import rankable_signal_values, store_threshold_selection


class ThresholdSignalIntentPolicy(StrategyIntentPolicy):
    def generate_strategy_intents(
        self, state: object, ctx: object, strategies: Sequence[object]
    ) -> None:
        threshold_signal_target(state, ctx, strategies)

    def precompute_strategy_intents(
        self, state: object, ctx: object, strategies: Sequence[object]
    ) -> None:
        precompute_threshold_target_intents(state, strategies)


def threshold_signal_target(
    state: Any,
    ctx: Any,
    strategies: Sequence[object] | None = None,
) -> None:
    active = strategies if strategies is not None else ctx.active_strategies
    prices = ctx.get(MarketDataModule.current_prices)
    tradable = ctx.get(MarketDataModule.current_tradable_status, None)
    for strategy in active:
        config = state.config_for(strategy)
        if str(config.get(TargetStrategyModule.strategy_kind, "group") or "group") != "threshold":
            continue
        if apply_precomputed_threshold_intent(state, ctx, strategy):
            continue
        signal_value = rankable_signal_values(
            ctx.get_for(FactorSignalModule.signal_value, strategy, {}), prices, tradable
        )
        raw_roles = ctx.get_for(FactorModule.factor_role_values, strategy, {}) or {}
        role_values = {
            str(role): rankable_signal_values(values, prices, tradable)
            for role, values in raw_roles.items()
        }
        weights, selection, reason = compute_threshold_target_weights(
            state, ctx, strategy, signal_value, factor_values_by_role=role_values
        )
        ctx.set_for(ThresholdSignalModule.target_weights, strategy, weights)
        ctx.set_for(
            TargetStrategyModule.trade_intent,
            strategy,
            target_weight_intent(weights, reason=reason),
        )
        store_threshold_selection(state, strategy, selection, weights)
        _record_target_trace(state, strategy, ctx.timestamp, weights)


def apply_precomputed_threshold_intent(state: Any, ctx: Any, strategy: Any) -> bool:
    if ctx.timestamp is None:
        return False
    table = state.target_store.precomputed_target_intents.get(strategy)
    if table is None:
        return False
    key = target_intent_event_key(ctx, strategy)
    intent = table.get(key) or table.get(pd.Timestamp(ctx.timestamp))
    if intent is None:
        intent = target_weight_intent({}, reason="precomputed_threshold_missing")
    ctx.set_for(ThresholdSignalModule.target_weights, strategy, intent.weights)
    ctx.set_for(TargetStrategyModule.trade_intent, strategy, intent)
    _record_target_trace(state, strategy, ctx.timestamp, intent.weights)
    return True


def target_intent_event_key(ctx: Any, strategy: Any) -> Any:
    try:
        draft = ctx.draft_for(strategy)
    except Exception:
        return pd.Timestamp(ctx.timestamp)
    return draft.index_key if draft.index_key is not None else pd.Timestamp(ctx.timestamp)
