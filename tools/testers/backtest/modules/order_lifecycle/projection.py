"""JSON-safe projection of exchange-style order lifecycle facts."""

from __future__ import annotations

from dataclasses import asdict

from tools.testers.backtest.engines.native.order import derive_group_status

from .projection_values import enum_values, timestamp_text, timestamp_values
from .projection_paired import project_paired_intents

def project_strategy_order_audit(state, strategy) -> dict:
    store = state.order_store
    orders = [
        order for order in store.orders_by_id.values()
        if order.strategy == strategy
    ]
    order_ids = {order.order_id for order in orders}
    group_ids = {order.order_group_id for order in orders if order.order_group_id}
    attempts_by_order: dict[str, list] = {}
    for attempt in store.attempts_by_id.values():
        if attempt.order_id in order_ids:
            attempts_by_order.setdefault(attempt.order_id, []).append(attempt)
    fills = [
        fill for order_id in sorted(order_ids)
        for fill in store.fills_by_order.get(order_id, ())
    ]
    return {
        "strategy_id": str(getattr(strategy, "alias", strategy)),
        "groups": [
            project_group(store.groups_by_id[group_id], store)
            for group_id in sorted(group_ids)
            if group_id in store.groups_by_id
        ],
        "paired_intents": project_paired_intents(orders),
        "orders": [
            project_order(order, attempts_by_order.get(order.order_id, ()))
            for order in orders
        ],
        "attempts": [
            timestamp_values(attempt.to_audit_dict())
            for attempts in attempts_by_order.values()
            for attempt in attempts
        ],
        "fills": [enum_values(asdict(fill)) for fill in fills],
        "settlements": [
            asdict(store.settlements_by_fill[fill.fill_id])
            for fill in fills
            if fill.fill_id in store.settlements_by_fill
        ],
        "actions": [
            enum_values(asdict(action))
            for order_id in sorted(order_ids)
            for action in store.actions_by_order.get(order_id, ())
        ],
    }


def project_group(group, store) -> dict:
    orders = [
        store.orders_by_id[order_id]
        for order_id in group.child_order_ids
        if order_id in store.orders_by_id
    ]
    return {
        "order_group_id": group.order_group_id,
        "parent_intent_id": group.parent_intent_id,
        "created_at": timestamp_text(group.created_at),
        "supersedes_group_id": group.supersedes_group_id,
        "execution_policy": group.execution_policy,
        "status": derive_group_status(tuple(order.status.value for order in orders)),
        "products": sorted({
            str(getattr(order.instrument, "name", order.instrument))
            for order in orders
        }),
        "child_count": len(orders),
        "offsets": [order.offset.value for order in orders],
        "child_order_ids": list(group.child_order_ids),
        "requested_quantity": sum(order.current_order_quantity for order in orders),
        "filled_quantity": sum(order.filled_quantity for order in orders),
        "active_leaves": sum(order.remaining_quantity for order in orders),
        "terminal_unfilled": sum(order.unfilled_quantity for order in orders),
    }


def project_order(order, attempts) -> dict:
    next_attempt = max(attempts, key=lambda item: item.timestamp) if attempts else None
    return {
        "order_id": order.order_id,
        "order_group_id": order.order_group_id,
        "parent_intent_id": order.parent_intent_id,
        "product": str(getattr(order.instrument, "name", order.instrument)),
        "side": order.side.value,
        "offset": order.offset.value,
        "leg_role": order.leg_role.value,
        "status": order.status.value,
        "requested_quantity": order.current_order_quantity,
        "filled_quantity": order.filled_quantity,
        "active_leaves": order.remaining_quantity,
        "terminal_unfilled": order.unfilled_quantity,
        "submitted_at": timestamp_text(order.submitted_at),
        "eligible_at": timestamp_text(order.eligible_at),
        "revision": order.revision,
        "matching_model": order.get("matching_model"),
        "capacity": order.get("capacity_details"),
        "next_attempt_at": (
            timestamp_text(next_attempt.timestamp)
            if next_attempt is not None and not order.status.terminal
            else None
        ),
    }
