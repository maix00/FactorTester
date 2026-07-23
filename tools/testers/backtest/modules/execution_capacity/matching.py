"""Allocate completed-bar capacity once across a same-time ORDER batch."""

from __future__ import annotations

from typing import Any

from tools.testers.backtest.engines.native.order import OrderSide
from tools.testers.backtest.modules.market_data import current_volume_at

from .effects import classify_order_effect, execution_priority
from .policy import effective_matching_model


def allocate_order_capacity(state: Any, ctx: Any, module: Any, execution_module: Any) -> None:
    orders = [
        order
        for strategy in ctx.active_strategies
        for order in ctx.payloads_for(strategy)
        if not order.status.terminal and not order.get("reject_reason")
    ]
    for order in orders:
        order.execution_effect = classify_order_effect(state, order)
    allocations: dict[Any, list[dict[str, Any]]] = {}
    volume_by_timestamp: dict[Any, dict[Any, float]] = {}
    for order in sorted(orders, key=execution_priority):
        config = state.config_for(order.strategy)
        model = effective_matching_model(
            config,
            execution_module.matching_model,
            module.liquidity_mode,
        )
        fill_quantity, details = _allocate_one(
            state, order, config, model, module, volume_by_timestamp,
        )
        sign = 1.0 if order.side is OrderSide.BUY else -1.0
        order.quantity = sign * fill_quantity
        order.set("matching_model", model)
        order.set("attempt_fill_quantity", fill_quantity)
        order.set("capacity_limited_attempt", model == "bar_volume_limited")
        order.set("capacity_details", details)
        if fill_quantity <= 1e-12:
            order.set("no_fill_reason", "bar capacity exhausted")
        allocations.setdefault(order.strategy, []).append({
            "order_id": order.order_id,
            "attempt_id": order.get("active_attempt_id", ""),
            "fill_quantity": fill_quantity,
            **details,
        })
    for strategy, rows in allocations.items():
        ctx.set_for(module.capacity_allocations, strategy, rows)


def _allocate_one(
    state: Any,
    order: Any,
    config: Any,
    model: str,
    module: Any,
    volume_by_timestamp: dict[Any, dict[Any, float]],
) -> tuple[float, dict[str, Any]]:
    if model == "next_bar_full_fill":
        return order.remaining_quantity, {"model": model, "capacity": None, "consumed_before": 0.0}
    market_timestamp = order.get("active_market_timestamp", order.get("price_timestamp"))
    volumes = volume_by_timestamp.get(market_timestamp)
    if volumes is None:
        volumes = current_volume_at(state, market_timestamp)
        volume_by_timestamp[market_timestamp] = volumes
    if order.instrument not in volumes:
        raise KeyError(f"bar volume missing for {order.instrument} at {market_timestamp}")
    rate = float(config.get(module.participation_rate, 0.1) or 0.0)
    capacity = max(rate * float(volumes[order.instrument]), 0.0)
    ledger = state.ledger_for(order)
    key = (ledger.ledger_id, order.instrument, market_timestamp, order.side.value)
    previous_limit = state.order_store.capacity_limit_by_key.setdefault(key, capacity)
    if abs(previous_limit - capacity) > 1e-12:
        raise ValueError(f"inconsistent capacity policy for execution key {key!r}")
    consumed = state.order_store.capacity_consumed_by_key.get(key, 0.0)
    fill_quantity = min(order.remaining_quantity, max(capacity - consumed, 0.0))
    state.order_store.capacity_consumed_by_key[key] = consumed + fill_quantity
    return fill_quantity, {
        "model": model,
        "market_timestamp": str(market_timestamp),
        "participation_rate": rate,
        "bar_volume": float(volumes[order.instrument]),
        "capacity": capacity,
        "consumed_before": consumed,
        "consumed_after": consumed + fill_quantity,
    }
