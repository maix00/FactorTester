"""Run-scoped authoritative order lifecycle store."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from tools.testers.backtest.engines.native.order import (
    Fill,
    FillSettlement,
    Order,
    OrderAction,
    OrderAttempt,
    OrderGroup,
)


@dataclass
class OrderStore:
    """Persistent Orders plus compatibility indexes during migration."""

    pending_orders: dict[Any, Order] = field(default_factory=dict)
    orders_by_id: dict[str, Order] = field(default_factory=dict)
    groups_by_id: dict[str, OrderGroup] = field(default_factory=dict)
    fills_by_order: dict[str, list[Fill]] = field(default_factory=dict)
    actions_by_order: dict[str, list[OrderAction]] = field(default_factory=dict)
    settlements_by_fill: dict[str, FillSettlement] = field(default_factory=dict)
    attempts_by_id: dict[str, OrderAttempt] = field(default_factory=dict)
    live_order_ids_by_scope: dict[Any, list[str]] = field(default_factory=dict)
    capacity_limit_by_key: dict[Any, float] = field(default_factory=dict)
    capacity_consumed_by_key: dict[Any, float] = field(default_factory=dict)
    superseded_group_id_by_scope: dict[Any, str] = field(default_factory=dict)

    def register_order(self, order: Order, *, scope: Any | None = None) -> None:
        if not order.order_id:
            raise ValueError("registered Order requires a stable order_id")
        existing = self.orders_by_id.get(order.order_id)
        if existing is not None and existing is not order:
            raise ValueError(f"duplicate order_id: {order.order_id}")
        self.orders_by_id[order.order_id] = order
        key = scope if scope is not None else (order.strategy, order.instrument)
        ids = self.live_order_ids_by_scope.setdefault(key, [])
        if order.order_id not in ids and not order.status.terminal:
            ids.append(order.order_id)

    def register_group(self, group: OrderGroup) -> None:
        if group.order_group_id in self.groups_by_id:
            raise ValueError(f"duplicate order_group_id: {group.order_group_id}")
        self.groups_by_id[group.order_group_id] = group

    def register_attempt(self, attempt: OrderAttempt) -> None:
        if attempt.attempt_id in self.attempts_by_id:
            raise ValueError(f"duplicate attempt_id: {attempt.attempt_id}")
        self.attempts_by_id[attempt.attempt_id] = attempt

    def attempt_is_actionable(self, attempt: OrderAttempt) -> bool:
        order = self.orders_by_id.get(attempt.order_id)
        return bool(
            order is not None
            and not order.status.terminal
            and order.revision == attempt.revision
        )

    def record_fill(self, fill: Fill) -> Order:
        order = self.orders_by_id[fill.order_id]
        if any(item.fill_id == fill.fill_id for item in self.fills_by_order.get(fill.order_id, ())):
            raise ValueError(f"duplicate fill_id: {fill.fill_id}")
        self.fills_by_order.setdefault(fill.order_id, []).append(fill)
        order.register_fill(fill.quantity)
        if order.status.terminal:
            self.remove_from_live_indexes(order)
        return order

    def record_action(self, action: OrderAction) -> None:
        self.actions_by_order.setdefault(action.order_id, []).append(action)

    def record_settlement(self, settlement: FillSettlement) -> None:
        if settlement.fill_id in self.settlements_by_fill:
            raise ValueError(f"duplicate settlement for fill_id: {settlement.fill_id}")
        self.settlements_by_fill[settlement.fill_id] = settlement

    def live_orders(self, scope: Any) -> tuple[Order, ...]:
        return tuple(
            self.orders_by_id[order_id]
            for order_id in self.live_order_ids_by_scope.get(scope, ())
            if order_id in self.orders_by_id
            and not self.orders_by_id[order_id].status.terminal
        )

    def remove_from_live_indexes(self, order: Order) -> None:
        for ids in self.live_order_ids_by_scope.values():
            if order.order_id in ids:
                ids.remove(order.order_id)
