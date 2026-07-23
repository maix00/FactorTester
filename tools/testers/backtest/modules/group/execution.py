"""Dispatch atomic group Orders to their first matching opportunity."""

from __future__ import annotations

from tools.testers.backtest.engines.native.events import EventDraft, EventKind
from tools.testers.backtest.engines.native.order import OrderStatus
from tools.testers.backtest.modules.execution_capacity import effective_matching_model
from tools.testers.backtest.modules.order_construct import OrderConstructModule
from tools.testers.backtest.modules.order_execution import OrderExecutionModule
from tools.testers.backtest.modules.order_lifecycle import create_order_attempt
from tools.testers.backtest.modules.strategy_book import strategy_book_store_for
from tools.testers.backtest.modules.time_index_lookup import signal_timestamps
from tools.testers.backtest.modules.volume_capacity import VolumeCapacityMode

from .execution_schedule import (
    execution_basis,
    resolve_execution_schedule as _resolve_execution_schedule,
)


def resolve_execution_schedule(state, ctx, strategy, product=None):
    return _resolve_execution_schedule(
        state, ctx, strategy, product,
        signal_timestamp_fn=signal_timestamps,
    )


def resolve_execution_timestamp(state, ctx, strategy):
    schedule = resolve_execution_schedule(state, ctx, strategy)
    if schedule is None:
        raise ValueError("next-bar order execution has no future bar to target")
    return schedule[0]


def schedule_order_execution(state, ctx) -> None:
    from tools.testers.backtest.modules.group_membership import GroupMembershipModule

    pending = state.order_store.pending_orders
    conflict = strategy_book_store_for(state).policies.pending_order_conflict
    drafts: list[EventDraft] = []
    for strategy in ctx.active_strategies:
        config = state.config_for(strategy)
        model = effective_matching_model(
            config, OrderExecutionModule.matching_model,
            VolumeCapacityMode.liquidity_mode,
        )
        basis = execution_basis(config, model)
        for order in ctx.get_for(OrderConstructModule.orders, strategy, []):
            if should_skip_order(order):
                continue
            order.set("execution_price_basis", basis)
            order.set("matching_model", model)
            if order.status is OrderStatus.BLOCKED:
                continue
            schedule = resolve_execution_schedule(
                state, ctx, strategy, order.instrument,
            )
            if schedule is None:
                continue
            execution_ts, price_ts = schedule
            apply_pending_conflict(
                state, strategy, order, ctx.timestamp, pending, conflict,
            )
            attempt = create_order_attempt(
                state, order, timestamp=execution_ts,
                market_timestamp=price_ts,
            )
            pending[(strategy, order.instrument)] = order
            drafts.append(EventDraft(
                EventKind.ORDER, execution_ts, strategy, attempt,
            ))
    if drafts:
        ctx.set(GroupMembershipModule.dispatched_order_events, drafts)


def should_skip_order(order) -> bool:
    return bool(
        abs(float(getattr(order, "quantity", 0.0) or 0.0)) <= 1e-12
        or order.get("reject_reason")
    )


def apply_pending_conflict(
    state, strategy, order, timestamp, pending, conflict,
) -> None:
    if conflict is not None:
        conflict(state, strategy, order, timestamp)
        return
    stale = pending.get((strategy, order.instrument))
    if (
        stale is not None
        and stale.status == OrderStatus.SCHEDULED
        and stale.get("price_timestamp", stale.timestamp) > timestamp
    ):
        stale.status = OrderStatus.CANCELLED
