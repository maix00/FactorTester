"""Decompose one net position delta into exchange-style atomic Orders."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pandas as pd

from tools.testers.backtest.engines.native.order import (
    Order,
    OrderGroup,
    OrderLegRole,
    OrderOffset,
    OrderStatus,
)

from .lot_offsets import close_buckets


def decompose_position_delta(
    *,
    strategy: Any,
    product: Any,
    timestamp: pd.Timestamp,
    delta: float,
    position: Any,
    group_id: str,
    parent_intent_id: str,
    order_ids: Iterator[str],
    cost_basis_method: str,
    supersedes_group_id: str = "",
) -> tuple[OrderGroup, list[Order]]:
    current = float(getattr(position, "quantity", 0.0) or 0.0)
    close_quantity = (
        min(abs(delta), abs(current))
        if current and delta and (current > 0) != (delta > 0)
        else 0.0
    )
    direction = 1.0 if delta > 0 else -1.0
    orders: list[Order] = []
    close_ids: list[str] = []
    for offset, role, quantity in close_buckets(
        position, close_quantity, cost_basis_method,
    ) if close_quantity > 1e-12 else ():
        order = atomic_order(
            strategy, product, timestamp, direction * quantity,
            next(order_ids), group_id, parent_intent_id, offset, role,
        )
        orders.append(order)
        close_ids.append(order.order_id)
    open_quantity = max(abs(delta) - close_quantity, 0.0)
    if open_quantity > 1e-12:
        order = atomic_order(
            strategy, product, timestamp, direction * open_quantity,
            next(order_ids), group_id, parent_intent_id,
            OrderOffset.OPEN, OrderLegRole.OPEN,
        )
        if close_ids:
            order.status = OrderStatus.BLOCKED
            order.set("depends_on_order_ids", tuple(close_ids))
        orders.append(order)
    group = OrderGroup(
        order_group_id=group_id,
        parent_intent_id=parent_intent_id,
        created_at=timestamp,
        child_order_ids=tuple(order.order_id for order in orders),
        supersedes_group_id=supersedes_group_id,
    )
    return group, orders


def atomic_order(
    strategy, product, timestamp, quantity: float, order_id: str,
    group_id: str, parent_intent_id: str,
    offset: OrderOffset, role: OrderLegRole,
) -> Order:
    return Order(
        instrument=product,
        timestamp=timestamp,
        quantity=quantity,
        intent_quantity=quantity,
        strategy=strategy,
        order_id=order_id,
        order_group_id=group_id,
        parent_intent_id=parent_intent_id,
        offset=offset,
        leg_role=role,
    )
