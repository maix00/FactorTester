"""Threshold selection state and signed target allocation."""

from __future__ import annotations

from typing import Any

from tools.testers.backtest.modules.group_membership import (
    _allocate_weights,
    _tradable_signal_values,
)


def signed_weights(
    state: Any,
    ctx: Any,
    strategy: Any,
    long_members: frozenset,
    short_members: frozenset,
    side_mode: str,
) -> dict[Any, float]:
    if side_mode == "long_short_spread":
        weights: dict[Any, float] = {}
        for product, weight in _allocate_weights(state, ctx, strategy, long_members).items():
            weights[product] = 0.5 * weight
        for product, weight in _allocate_weights(state, ctx, strategy, short_members).items():
            weights[product] = weights.get(product, 0.0) - 0.5 * weight
        return {product: weight for product, weight in weights.items() if abs(weight) > 1e-12}
    if side_mode == "short_only":
        return {
            product: -weight
            for product, weight in _allocate_weights(state, ctx, strategy, short_members).items()
        }
    return _allocate_weights(state, ctx, strategy, long_members)


def rankable_signal_values(
    signal_value: dict,
    current_prices: dict | None,
    tradable_status: dict | None,
) -> dict:
    return _tradable_signal_values(signal_value, current_prices, tradable_status)


def last_threshold_selection(state: Any, strategy: Any) -> dict[str, frozenset]:
    cached = state.target_store.strategy_selection_cache.get((strategy, "threshold"))
    if isinstance(cached, dict):
        return {
            "long": frozenset(cached.get("long", frozenset())),
            "short": frozenset(cached.get("short", frozenset())),
        }
    return {"long": frozenset(), "short": frozenset()}


def last_threshold_weights(state: Any, strategy: Any) -> dict[Any, float] | None:
    cached = state.target_store.strategy_established_target_weights.get((strategy, "threshold"))
    return dict(cached) if isinstance(cached, dict) else None


def store_threshold_selection(
    state: Any,
    strategy: Any,
    selection: dict[str, frozenset],
    weights: dict[Any, float],
) -> None:
    state.target_store.strategy_selection_cache[(strategy, "threshold")] = selection
    state.target_store.strategy_established_target_weights[(strategy, "threshold")] = dict(weights)
