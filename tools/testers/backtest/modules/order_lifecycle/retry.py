"""Carry a live Order remainder to its next eligible completed bar."""

from __future__ import annotations

from typing import Any

import pandas as pd

from tools.testers.backtest.engines.native.events import EventDraft, EventKind
from tools.testers.backtest.engines.native.order import OrderStatus
from tools.testers.backtest.modules.engine import bar_price_visibility_timestamp
from tools.testers.backtest.modules.market_data import (
    market_price_tables_for,
    resolved_bar_frequency_for_strategy,
)

from .finalize import record_order_lifecycle_state
from .dependencies import activate_ready_dependents
from .offsets import reclassify_deferred_close_today
from .schedule import create_order_attempt, order_status_event


def finalize_and_retry_orders(state: Any, ctx: Any, retry_ref: Any) -> None:
    drafts: list[EventDraft] = []
    for strategy in ctx.active_strategies:
        for order in ctx.payloads_for(strategy):
            if _requires_retry(order):
                schedule = _next_schedule(state, order)
                if schedule is None:
                    order.status = OrderStatus.EXPIRED
                    state.order_store.remove_from_live_indexes(order)
                else:
                    event_ts, market_ts = schedule
                    # A volume-limited order can carry an unfilled remainder
                    # across a trading-day boundary. Its original
                    # CLOSE_TODAY offset then no longer matches the lot age;
                    # apply the same correction used on first dispatch.
                    previous_market_ts = order.get(
                        "active_market_timestamp", order.get("price_timestamp")
                    )
                    reclassify_deferred_close_today(
                        order,
                        signal_timestamp=previous_market_ts,
                        market_timestamp=market_ts,
                        trading_day_resolver=state.market_data_store.trading_day_resolver,
                    )
                    attempt = create_order_attempt(
                        state,
                        order,
                        timestamp=event_ts,
                        market_timestamp=market_ts,
                    )
                    emit_status_events = state.config_for(order.strategy).uses_flow(
                        "strategy_runtime_on_order_status_event"
                    )
                    if emit_status_events:
                        drafts.append(order_status_event(order, timestamp=ctx.timestamp))
                    order.status = OrderStatus.ACCEPTED
                    if emit_status_events:
                        drafts.append(order_status_event(order, timestamp=event_ts))
                    drafts.append(EventDraft(EventKind.ORDER, event_ts, strategy, attempt))
    drafts.extend(activate_ready_dependents(state, ctx))
    if drafts:
        ctx.set(retry_ref, drafts)
    record_order_lifecycle_state(state, ctx)


def _requires_retry(order: Any) -> bool:
    return bool(
        order.get("matching_model") == "bar_volume_limited"
        and not order.status.terminal
        and order.remaining_quantity > 1e-12
    )


def _next_schedule(state: Any, order: Any) -> tuple[pd.Timestamp, pd.Timestamp] | None:
    basis = str(order.get("execution_price_basis", "close") or "close").lower()
    tables = market_price_tables_for(state)
    table = tables.get(basis) if isinstance(tables, dict) else None
    if not isinstance(table, pd.DataFrame) or order.instrument not in table:
        raise KeyError(f"market data does not provide {basis!r} for retrying {order.instrument}")
    index = pd.DatetimeIndex(table[order.instrument].dropna().index)
    current = pd.Timestamp(order.get("active_market_timestamp", order.get("price_timestamp")))
    position = int(index.searchsorted(current, side="right"))
    if position >= len(index):
        return None
    market_ts = pd.Timestamp(index[position])
    config = state.config_for(order.strategy)
    event_ts = bar_price_visibility_timestamp(
        index,
        price_pos=position,
        basis=basis,
        config=config,
        bar_freq=resolved_bar_frequency_for_strategy(state, order.strategy),
    )
    return event_ts, market_ts
