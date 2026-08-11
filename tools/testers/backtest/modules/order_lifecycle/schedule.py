"""Create immutable execution attempts for one persistent Order."""

from __future__ import annotations

import copy
from typing import Any

from tools.testers.backtest.engines.native.events import EventDraft, EventKind
from tools.testers.backtest.engines.native.order import OrderAttempt, OrderStatus

from .actions import record_initial_submit


def create_order_attempt(
    state: Any,
    order: Any,
    *,
    timestamp: Any,
    market_timestamp: Any,
) -> OrderAttempt:
    if not order.order_id:
        order.order_id = state.order_flow_store.next_order_id(order.strategy, order.timestamp)
    if order.order_id not in state.order_store.orders_by_id:
        state.order_store.register_order(order)
    sequence = int(order.get("attempt_sequence", 0) or 0) + 1
    order.set("attempt_sequence", sequence)
    order.timestamp = timestamp
    order.eligible_at = timestamp
    order.set("price_timestamp", market_timestamp)
    order.status = OrderStatus.SUBMITTED
    record_initial_submit(state, order, timestamp)
    attempt = OrderAttempt(
        attempt_id=f"{order.order_id}:attempt:{sequence}",
        order_id=order.order_id,
        revision=order.revision,
        timestamp=timestamp,
        market_timestamp=market_timestamp,
        _order=order,
    )
    state.order_store.register_attempt(attempt)
    return attempt


def order_status_event(
    order: Any,
    *,
    timestamp: Any,
    status: OrderStatus | None = None,
) -> EventDraft:
    """Snapshot one order transition without sharing mutable order state."""

    snapshot = copy.copy(order)
    snapshot.fields = dict(getattr(order, "fields", {}) or {})
    if status is not None:
        snapshot.status = status
    return EventDraft(EventKind.ORDER_STATUS, timestamp, order.strategy, snapshot)


def order_status_event_if_enabled(
    state: Any,
    order: Any,
    *,
    timestamp: Any,
    status: OrderStatus | None = None,
) -> EventDraft | None:
    """Return a status snapshot only for strategies that consume that axis."""

    config_for = getattr(state, "config_for", None)
    if not callable(config_for):
        return None
    config = config_for(order.strategy)
    if not config.uses_flow("strategy_runtime_on_order_status_event"):
        return None
    return order_status_event(order, timestamp=timestamp, status=status)


def order_transition_events_if_enabled(
    state: Any,
    order: Any,
    *,
    timestamp: Any,
    pending_status: OrderStatus,
) -> tuple[EventDraft, ...]:
    """Return pending-request and terminal snapshots for an internal action."""

    pending = order_status_event_if_enabled(
        state, order, timestamp=timestamp, status=pending_status,
    )
    terminal = order_status_event_if_enabled(
        state, order, timestamp=timestamp,
    )
    if pending is None or terminal is None:
        return ()
    return pending, terminal
