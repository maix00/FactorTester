"""Next-bar order scheduling for group-produced target orders."""

from __future__ import annotations

from typing import Any, cast

import pandas as pd

from tools.testers.backtest.engines.native.events import EventDraft, EventKind
from tools.testers.backtest.engines.native.order import OrderStatus
from tools.testers.backtest.modules.engine import bar_price_visibility_timestamp
from tools.testers.backtest.modules.market_data import (
    current_prices_table_for,
    market_price_tables_for,
    resolved_bar_frequency_for_strategy,
)
from tools.testers.backtest.modules.order_construct import OrderConstructModule
from tools.testers.backtest.modules.order_execution import OrderExecutionModule
from tools.testers.backtest.modules.order_lifecycle import create_order_attempt
from tools.testers.backtest.modules.execution_capacity import effective_matching_model
from tools.testers.backtest.modules.volume_capacity import VolumeCapacityMode
from tools.testers.backtest.modules.strategy_book import strategy_book_store_for
from tools.testers.backtest.modules.time_index_lookup import signal_timestamps


def resolve_execution_schedule(
    state, ctx, strategy, product: Any | None = None,
) -> tuple[pd.Timestamp, pd.Timestamp] | None:
    from tools.testers.backtest.modules.group_membership import GroupMembershipModule

    if ctx.timestamp is None:
        raise ValueError("execution scheduling requires an event timestamp")
    current_ts = cast(pd.Timestamp, ctx.timestamp)
    config = state.config_for(strategy)
    timing = config.get(GroupMembershipModule.execution_timing, "next_bar")
    model = effective_matching_model(
        config,
        OrderExecutionModule.matching_model,
        VolumeCapacityMode.liquidity_mode,
    )
    basis = (
        str(config.get(OrderExecutionModule.volume_execution_price_basis, "close") or "close").lower()
        if model == "bar_volume_limited"
        else str(config.get(OrderExecutionModule.execution_price_basis, "open") or "open").lower()
    )
    if timing != "next_bar":
        raise ValueError("order execution timing must be next-bar open or completed-bar capacity")
    if model == "next_bar_full_fill" and basis != "open":
        raise ValueError("next-bar full-fill execution requires next-bar open price")
    delay = max(int(config.get(GroupMembershipModule.execution_delay_bars, 1) or 1), 1)
    table = _price_table(state, basis)
    if table is None:
        return current_ts, current_ts
    bar_freq = resolved_bar_frequency_for_strategy(state, strategy)
    freq_key = getattr(bar_freq, "name", str(bar_freq)) if bar_freq is not None else None
    product_key = str(getattr(product, "name", product)) if product is not None else None
    key = (current_ts.value, str(current_ts.tz), delay, basis, freq_key, id(table), product_key)
    cache = state.target_store.execution_schedule_cache
    if key in cache:
        return cache[key]
    index = _price_index(table, product)
    pos = index.get_indexer(pd.Index([current_ts]), method="bfill")[0] if len(index) else -1
    if pos < 0 or pos + delay >= len(index):
        cache[key] = None
        return None
    price_pos = pos + delay
    price_ts = cast(pd.Timestamp, index[price_pos])
    event_ts = bar_price_visibility_timestamp(
        index, price_pos=price_pos, basis=basis, config=config, bar_freq=bar_freq,
    )
    cache[key] = (event_ts, price_ts)
    return cache[key]


def resolve_execution_timestamp(state, ctx, strategy) -> pd.Timestamp:
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
        matching_model = effective_matching_model(
            config,
            OrderExecutionModule.matching_model,
            VolumeCapacityMode.liquidity_mode,
        )
        price_basis = (
            config.get(OrderExecutionModule.volume_execution_price_basis, "close")
            if matching_model == "bar_volume_limited"
            else config.get(OrderExecutionModule.execution_price_basis, "open")
        )
        for order in ctx.get_for(OrderConstructModule.orders, strategy, []):
            if abs(float(getattr(order, "quantity", 0.0) or 0.0)) <= 1e-12 or order.get("reject_reason"):
                continue
            order.set("execution_price_basis", price_basis)
            order.set("matching_model", matching_model)
            if order.status is OrderStatus.BLOCKED:
                continue
            schedule = resolve_execution_schedule(state, ctx, strategy, order.instrument)
            if schedule is None:
                continue
            execution_ts, price_ts = schedule
            key = (strategy, order.instrument)
            if conflict is not None:
                conflict(state, strategy, order, ctx.timestamp)
            else:
                stale = pending.get(key)
                if stale is not None and stale.status == OrderStatus.SCHEDULED and stale.get(
                    "price_timestamp", stale.timestamp,
                ) > ctx.timestamp:
                    stale.status = OrderStatus.CANCELLED
            attempt = create_order_attempt(
                state,
                order,
                timestamp=execution_ts,
                market_timestamp=price_ts,
            )
            pending[key] = order
            drafts.append(EventDraft(EventKind.ORDER, execution_ts, strategy, attempt))
    if drafts:
        ctx.set(GroupMembershipModule.dispatched_order_events, drafts)


def _price_table(state, basis: str) -> pd.DataFrame | None:
    tables = market_price_tables_for(state)
    table = tables.get(basis) if isinstance(tables, dict) else None
    if isinstance(table, pd.DataFrame) and not table.empty:
        return table
    fallback = current_prices_table_for(state)
    return fallback if isinstance(fallback, pd.DataFrame) and not fallback.empty else None


def _price_index(table: pd.DataFrame, product: Any | None) -> pd.DatetimeIndex:
    if product is None or product not in table.columns:
        return signal_timestamps(table)
    series = table[product].dropna()
    return signal_timestamps(series) if not series.empty else pd.DatetimeIndex([])
