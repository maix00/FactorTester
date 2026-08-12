"""Intent-policy catalog, StrategyBook resolution, and execution adapters."""

from __future__ import annotations

from typing import Any

_BUILTIN_POLICIES: dict[str, Any] = {}


def register_strategy_intent_policy(strategy_kind: str, policy: Any) -> None:
    _BUILTIN_POLICIES[str(strategy_kind)] = policy


def strategy_intent_policy_for(strategy_kind: str) -> Any | None:
    return _BUILTIN_POLICIES.get(str(strategy_kind))


def resolved_policy_batches(
    state: Any,
    strategies: Any,
    *,
    expected_kind: str | None = None,
    precomputed_only: bool = False,
) -> list[tuple[Any, list[Any]]]:
    from tools.testers.backtest.modules.strategy_book import resolve_strategy_intent_policy
    from tools.testers.backtest.modules.target import TargetStrategyModule

    batches: list[tuple[Any, list[Any]]] = []
    for strategy in strategies:
        config = state.config_for(strategy)
        if precomputed_only and not config.uses_flow("signal_precomputed"):
            continue
        kind = str(config.get(TargetStrategyModule.strategy_kind, "group") or "group")
        if expected_kind is not None and kind != expected_kind:
            continue
        default_policy = strategy_intent_policy_for(kind)
        if default_policy is None:
            continue
        policy = resolve_strategy_intent_policy(state, strategy, default_policy)
        for batched_policy, selected in batches:
            if batched_policy is policy:
                selected.append(strategy)
                break
        else:
            batches.append((policy, [strategy]))
    return batches


def generate_strategy_intents(state: Any, ctx: Any, *, expected_kind: str) -> None:
    for policy, strategies in resolved_policy_batches(
        state, ctx.active_strategies, expected_kind=expected_kind
    ):
        policy.generate_strategy_intents(state, ctx, strategies)


def precompute_strategy_intents(state: Any, ctx: Any) -> None:
    from tools.testers.backtest.modules.strategy_book import apply_strategy_intent_precompute_policy

    batches = resolved_policy_batches(state, ctx.active_strategies, precomputed_only=True)
    for policy, strategies in batches:
        apply_strategy_intent_precompute_policy(state, ctx, strategies, policy)
