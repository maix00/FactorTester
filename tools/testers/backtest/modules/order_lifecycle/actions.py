"""Immutable submit/cancel/replace request lineage."""

from __future__ import annotations

from typing import Any

from tools.testers.backtest.engines.native.order import (
    OrderAction,
    OrderActionType,
)


def record_order_action(
    state: Any,
    order: Any,
    action: OrderActionType,
    *,
    timestamp: Any,
    reason: str = "",
) -> OrderAction:
    previous = state.order_store.actions_by_order.get(order.order_id, ())
    request = OrderAction(
        request_id=f"{order.order_id}:request:{len(previous) + 1}",
        order_id=order.order_id,
        action=action,
        submitted_at=timestamp,
        revision=order.revision,
        previous_request_id=previous[-1].request_id if previous else "",
        reason=reason,
    )
    state.order_store.record_action(request)
    return request


def record_initial_submit(state: Any, order: Any, timestamp: Any) -> None:
    if not state.order_store.actions_by_order.get(order.order_id):
        record_order_action(
            state, order, OrderActionType.SUBMIT, timestamp=timestamp,
        )
