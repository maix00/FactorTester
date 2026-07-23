"""Event adapter for the built-in group strategy intent policy."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from tools.testers.backtest.modules.factor import FactorModule
from tools.testers.backtest.modules.factor_signal import FactorSignalModule
from tools.testers.backtest.modules.target import TargetStrategyModule, target_weight_intent
from tools.testers.backtest.modules.group.selection import (
    compute_group_target_weights,
    validate_group_factor_roles,
)


def group_quantile_membership(
    state, ctx, strategies: Sequence[object] | None = None,
) -> None:
    from tools.testers.backtest.modules.group_membership import GroupMembershipModule
    from tools.testers.backtest.modules.group.precompute import apply_precomputed_target_intents

    active = strategies if strategies is not None else ctx.active_strategies
    if apply_precomputed_target_intents(state, ctx, active):
        return
    established = state.target_store.strategy_established_target_weights
    previous_membership = state.target_store.strategy_selection_cache
    ranked_cache: dict[frozenset, Sequence[tuple[Any, float]]] = {}
    bucket_cache: dict[tuple[frozenset, int, int], frozenset] = {}
    for strategy in active:
        config = state.config_for(strategy)
        validate_group_factor_roles(config)
        roles = ctx.get_for(FactorModule.factor_role_values, strategy, {}) or {}
        primary = ctx.get_for(FactorSignalModule.signal_value, strategy, {})
        weights, members, reason = compute_group_target_weights(
            state, ctx, strategy, roles.get("ranking", primary),
            established=established.get(strategy),
            last_membership=previous_membership.get(strategy),
            ranked_cache=ranked_cache,
            bucket_cache=bucket_cache,
        )
        ctx.set_for(GroupMembershipModule.target_weights, strategy, weights)
        ctx.set_for(
            TargetStrategyModule.trade_intent,
            strategy,
            target_weight_intent(weights, reason=reason),
        )
        if reason not in {"buy_and_hold_established_target", "membership_unchanged"} and weights:
            established[strategy] = weights
            previous_membership[strategy] = members
            record_target_trace(state, strategy, ctx.timestamp, weights)


def record_target_trace(state, strategy, timestamp, weights: dict) -> None:
    if timestamp is not None:
        state.target_store.record_target_trace(strategy, timestamp, weights)


def target_trace_for(state, strategy) -> dict:
    return state.target_store.target_trace_for(strategy)
