"""Reconcile a target position against actual and live Order leaves."""

from __future__ import annotations

from typing import Any

from tools.testers.backtest.engines.native.order import (
    OrderActionType,
    OrderStatus,
)

from .access import order_stores_for
from .actions import record_order_action
from .schedule import order_transition_events_if_enabled


def reconcile_target_delta(
    state: Any,
    strategy: Any,
    product: Any,
    *,
    actual_quantity: float,
    target_quantity: float,
    timestamp: Any,
    status_event_sink: Any | None = None,
) -> float:
    order_store, audit_store = order_stores_for(state)
    scope = (strategy, product)
    live_ids = order_store.live_order_ids_by_scope.get(scope)
    if not live_ids:
        # The overwhelmingly common target path has no outstanding leaves.
        # Avoid constructing an empty tuple and scanning the global order map.
        return target_quantity - actual_quantity
    live = order_store.live_orders(scope)
    projected = actual_quantity + sum(order.signed_remaining_quantity for order in live)
    if abs(target_quantity - projected) <= 1e-12:
        return 0.0
    superseded_groups = {
        order.order_group_id for order in live if order.order_group_id
    }
    for order in live:
        order.revision += 1
        record_order_action(
            state, order, OrderActionType.REPLACE,
            timestamp=timestamp, reason="latest target superseded leaves",
        )
        order.status = OrderStatus.CANCELLED
        order_store.remove_from_live_indexes(order)
        pending = order_store.pending_orders
        if pending.get(scope) is order:
            pending.pop(scope, None)
        if status_event_sink is not None:
            for event in order_transition_events_if_enabled(
                state, order, timestamp=timestamp,
                pending_status=OrderStatus.PENDING_UPDATE,
            ):
                status_event_sink(event)
        audit_store.record(
            order,
            step="target_reconcile_cancel",
            label="最新目标替换未成交余量",
            timestamp=timestamp,
            details={
                "actual_quantity": actual_quantity,
                "projected_quantity": projected,
                "target_quantity": target_quantity,
            },
        )
    if superseded_groups:
        latest = max(
            superseded_groups,
            key=lambda group_id: getattr(
                order_store.groups_by_id.get(group_id), "created_at", timestamp,
            ),
        )
        order_store.superseded_group_id_by_scope[scope] = latest
    return target_quantity - actual_quantity
