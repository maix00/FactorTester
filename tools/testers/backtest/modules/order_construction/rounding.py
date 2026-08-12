"""Lot-size rounding for sized order deltas."""

from __future__ import annotations

import math

from tools.testers.backtest.modules.market_data import MarketDataModule, market_data_store_for
from tools.testers.backtest.modules.order_flow import order_flow_store_for
from tools.testers.backtest.modules.strategy_book import (
    ledger_for_strategy_product,
    strategy_book_store_for,
)
from tools.testers.backtest.modules.trading_rule import _resolve_use_int_position


def round_to_lot_sizes(state, ctx, module) -> None:
    lot_sizes = ctx.get(MarketDataModule.lot_sizes, None)
    if not lot_sizes:
        lot_sizes = market_data_store_for(state).raw_input.get("lot_sizes") or {}
    audit_store = order_flow_store_for(state)
    for strategy in ctx.active_strategies:
        policy = state.config_for(strategy).get(
            module.quantity_rounding_policy, "floor_to_lot",
        )
        deltas = ctx.get_for(module.raw_deltas, strategy, {})
        rounded = {
            product: default_round_order_quantity(
                quantity,
                effective_lot_size(
                    state, strategy, product, lot_sizes, timestamp=ctx.timestamp,
                ),
                policy,
            )
            for product, quantity in deltas.items()
        }
        ctx.set_for(module.sized_deltas, strategy, rounded)
        ctx.set_for(module.deltas, strategy, rounded)
        if rounded != deltas:
            audit_store.record_strategy_step(
                strategy, timestamp=ctx.timestamp,
                step="quantity_rounding", label="按最小买入手数取整",
                details={
                    "policy": policy,
                    "before": stringify_deltas(deltas),
                    "after": stringify_deltas(rounded),
                },
            )


def default_round_order_quantity(
    quantity: float, lot_size: float | None, policy: str,
) -> float:
    if not lot_size:
        return quantity
    lots = abs(quantity) / lot_size + 1e-12
    rounded_lots = math.floor(lots) if policy == "floor_to_lot" else round(lots)
    sign = 1.0 if quantity > 0 else (-1.0 if quantity < 0 else 0.0)
    return sign * rounded_lots * lot_size


def effective_lot_size(
    state, strategy, product, lot_sizes: dict, *, timestamp=None,
) -> float | None:
    lot_size = lot_sizes.get(product)
    if lot_size:
        return float(lot_size)
    store = strategy_book_store_for(state)
    cache = getattr(getattr(state, "target_store", None), "effective_lot_size_cache", None)
    static_route = store.policies.order_routing is None
    cache_key = (strategy, product)
    if static_route and cache is not None and cache_key in cache:
        return cache[cache_key]
    config = state.config_for(strategy)
    ledger = ledger_for_strategy_product(
        state, strategy, product, timestamp=timestamp,
    )
    result = 1.0 if _resolve_use_int_position(
        config, state.ledger_config_for(ledger)
    ) else None
    if static_route and cache is not None:
        cache[cache_key] = result
    return result


def stringify_deltas(deltas: dict) -> dict[str, float]:
    return {
        str(getattr(product, "name", product)): float(quantity)
        for product, quantity in deltas.items()
    }
