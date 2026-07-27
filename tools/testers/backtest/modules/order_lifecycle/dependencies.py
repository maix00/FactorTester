"""Activate blocked OrderGroup children when prerequisite Orders fill."""

from __future__ import annotations

from typing import Any

from tools.testers.backtest.engines.native.events import EventDraft, EventKind
from tools.testers.backtest.engines.native.order import (
    OrderActionType,
    OrderStatus,
)

from .actions import record_order_action
from .schedule import create_order_attempt, order_status_event


def activate_ready_dependents(state: Any, ctx: Any) -> list[EventDraft]:
    group_ids = {
        order.order_group_id
        for strategy in ctx.active_strategies
        for order in ctx.payloads_for(strategy)
        if order.order_group_id
    }
    drafts: list[EventDraft] = []
    for group_id in group_ids:
        group = state.order_store.groups_by_id.get(group_id)
        if group is None:
            continue
        children = [
            state.order_store.orders_by_id[order_id]
            for order_id in group.child_order_ids
        ]
        for order in children:
            if order.status is not OrderStatus.BLOCKED:
                continue
            dependencies = [
                state.order_store.orders_by_id[order_id]
                for order_id in order.get("depends_on_order_ids", ())
            ]
            if dependencies and all(
                dependency.status is OrderStatus.FILLED
                for dependency in dependencies
            ):
                market_timestamp = max(
                    dependency.get(
                        "active_market_timestamp",
                        dependency.get("price_timestamp", ctx.timestamp),
                    )
                    for dependency in dependencies
                )
                attempt = create_order_attempt(
                    state, order, timestamp=ctx.timestamp,
                    market_timestamp=market_timestamp,
                )
                try:
                    emit_status_events = state.config_for(order.strategy).uses_flow(
                        "strategy_runtime_on_order_status_event"
                    )
                except KeyError:
                    emit_status_events = False
                if emit_status_events:
                    drafts.append(order_status_event(order, timestamp=ctx.timestamp))
                order.status = OrderStatus.ACCEPTED
                if emit_status_events:
                    drafts.append(order_status_event(order, timestamp=ctx.timestamp))
                drafts.append(EventDraft(
                    EventKind.ORDER, ctx.timestamp, order.strategy, attempt,
                ))
            elif any(
                dependency.status.terminal
                and dependency.status is not OrderStatus.FILLED
                for dependency in dependencies
            ):
                order.revision += 1
                record_order_action(
                    state, order, OrderActionType.CANCEL,
                    timestamp=ctx.timestamp,
                    reason="prerequisite close order did not fill",
                )
                order.status = OrderStatus.CANCELLED
                order.reject_reason = "prerequisite close order did not fill"
                state.order_store.remove_from_live_indexes(order)
    return drafts
