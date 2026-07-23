"""Eligibility and deterministic ordering for one ORDER batch."""

from __future__ import annotations

from tools.testers.backtest.engines.native.order import OrderStatus
from .balances import normalise_fill_quantity


def settlement_order(state, ctx) -> list[tuple[object, object]]:
    from tools.testers.backtest.modules.execution_capacity.effects import (
        classify_order_effect,
        execution_priority,
    )

    rows = [
        (strategy, order)
        for strategy in ctx.active_strategies
        for order in ctx.payloads_for(strategy)
    ]
    for _, order in rows:
        order.execution_effect = classify_order_effect(state, order)
    return sorted(rows, key=lambda row: execution_priority(row[1]))


def prepare_order_fill(state, ctx, strategy, order, audit_store) -> bool:
    if order.status == OrderStatus.CANCELLED:
        return False
    reject_reason = order.get("reject_reason")
    if reject_reason:
        reject_order(ctx, order, audit_store, str(reject_reason))
        return False
    if (
        order.get("capacity_limited_attempt")
        and float(order.get("attempt_fill_quantity", 0.0) or 0.0) <= 1e-12
    ):
        audit_store.record(
            order, step="execution_capacity", label="本 bar 未获得成交容量",
            timestamp=ctx.timestamp,
            details=dict(order.get("capacity_details", {}) or {}),
        )
        return False
    if not order.get("capacity_limited_attempt"):
        order.accepted_quantity = abs(float(order.quantity))
    before = float(order.quantity)
    after = normalise_fill_quantity(
        state, strategy, order.instrument, before,
    )
    if after != before:
        order.quantity = after
        audit_store.record(
            order, step="fill_quantity_rounding", label="成交数量取整",
            timestamp=ctx.timestamp,
            details={"before_quantity": before, "after_quantity": float(after)},
        )
    if abs(float(order.quantity or 0.0)) <= 1e-12:
        reject_order(ctx, order, audit_store, "订单数量取整为 0")
        return False
    return True


def reject_order(ctx, order, audit_store, reason: str) -> None:
    order.status = OrderStatus.REJECTED
    order.reject_reason = reason
    audit_store.record(
        order, step="apply_order_fill", label="订单拒绝",
        timestamp=ctx.timestamp, details={"reject_reason": reason},
    )
