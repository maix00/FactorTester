"""Causal execution-time resolution for group-produced orders."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, cast

import pandas as pd

from tools.testers.backtest.modules.engine import (
    BarVisibilityPolicy,
    bar_price_visibility_timestamp,
    resolve_bar_visibility_policy,
)
from tools.testers.backtest.modules.execution_capacity import effective_matching_model
from tools.testers.backtest.modules.market_data import (
    current_prices_table_for,
    market_data_store_for,
    market_price_tables_for,
    resolved_bar_frequency_for_strategy,
)
from tools.testers.backtest.modules.order_execution import OrderExecutionModule
from tools.testers.backtest.modules.time_index_lookup import signal_timestamps
from tools.testers.backtest.modules.volume_capacity import VolumeCapacityMode


@dataclass(frozen=True, slots=True)
class ExecutionScheduleContext:
    """Resolved, immutable inputs shared by one strategy signal batch.

    A signal batch can contain many product legs, but timing/model/basis and
    bar frequency are strategy-level settings.  Passing them through avoids
    re-reading the same configuration for every leg while keeping the
    product-specific index lookup and the existing per-product cache intact.
    """

    config: Any
    timing: str
    model: str
    basis: str
    delay: int
    bar_freq: Any
    table: pd.DataFrame | None
    visibility_policy_cache: "_VisibilityPolicyCache" = field(
        default_factory=lambda: _VisibilityPolicyCache()
    )


@dataclass(slots=True)
class _VisibilityPolicyCache:
    """Lazy cache preserving validation order for a scheduling batch."""

    value: BarVisibilityPolicy | None = None


def resolve_execution_schedule(
    state, ctx, strategy, product: Any | None = None, *,
    signal_timestamp_fn=signal_timestamps,
    schedule_context: ExecutionScheduleContext | None = None,
) -> tuple[pd.Timestamp, pd.Timestamp] | None:
    from tools.testers.backtest.modules.group_membership import GroupMembershipModule

    if ctx.timestamp is None:
        raise ValueError("execution scheduling requires an event timestamp")
    current_ts = cast(pd.Timestamp, ctx.timestamp)
    if schedule_context is None:
        config = state.config_for(strategy)
        timing = config.get(GroupMembershipModule.execution_timing, "next_bar")
        model = effective_matching_model(
            config, OrderExecutionModule.matching_model, VolumeCapacityMode.liquidity_mode,
        )
        basis = execution_basis(config, model)
        delay = max(int(config.get(GroupMembershipModule.execution_delay_bars, 1) or 1), 1)
        table = price_table(state, basis)
        bar_freq = resolved_bar_frequency_for_strategy(state, strategy)
        if bar_freq is None and table is not None:
            bar_freq = market_data_store_for(state).execution_frequency_for(table)
    else:
        config = schedule_context.config
        timing = schedule_context.timing
        model = schedule_context.model
        basis = schedule_context.basis
        delay = schedule_context.delay
        bar_freq = schedule_context.bar_freq
        table = schedule_context.table
    if timing != "next_bar":
        raise ValueError("order execution timing must be next-bar open or completed-bar capacity")
    if model == "next_bar_full_fill" and basis != "open":
        raise ValueError("next-bar full-fill execution requires next-bar open price")
    if table is None:
        return current_ts, current_ts
    key = schedule_cache_key(
        current_ts, delay, basis, bar_freq, table, product,
    )
    cache = state.target_store.execution_schedule_cache
    if key in cache:
        return cache[key]
    index = price_index(table, product, signal_timestamp_fn, state=state)
    if not len(index):
        position = -1
    elif index.is_monotonic_increasing:
        # ``searchsorted(left)`` is the scalar equivalent of a one-element
        # ``get_indexer(..., method="bfill")`` call, without allocating a
        # temporary Index on every order leg.
        position = int(index.searchsorted(current_ts, side="left"))
        if position >= len(index):
            position = -1
    else:
        position = int(index.get_indexer(pd.Index([current_ts]), method="bfill")[0])
    if position < 0 or position + delay >= len(index):
        cache[key] = None
        return None
    price_position = position + delay
    price_ts = cast(pd.Timestamp, index[price_position])
    visibility_policy = None
    if schedule_context is not None:
        visibility_policy = schedule_context.visibility_policy_cache.value
        if visibility_policy is None:
            visibility_policy = resolve_bar_visibility_policy(config)
            schedule_context.visibility_policy_cache.value = visibility_policy
    event_ts = bar_price_visibility_timestamp(
        index, price_pos=price_position, basis=basis,
        config=config, bar_freq=bar_freq,
        visibility_policy=visibility_policy,
    )
    cache[key] = (event_ts, price_ts)
    return cache[key]


def resolve_execution_timestamp(
    state, ctx, strategy, *, signal_timestamp_fn=signal_timestamps,
) -> pd.Timestamp:
    schedule = resolve_execution_schedule(
        state, ctx, strategy, signal_timestamp_fn=signal_timestamp_fn,
    )
    if schedule is None:
        raise ValueError("next-bar order execution has no future bar to target")
    return schedule[0]


def resolve_next_execution_opportunity(
    state,
    strategy,
    product: Any,
    *,
    after_timestamp: pd.Timestamp,
) -> tuple[pd.Timestamp, pd.Timestamp, str, str] | None:
    """Find the first causally executable bar strictly after an event."""
    config = state.config_for(strategy)
    model = effective_matching_model(
        config,
        OrderExecutionModule.matching_model,
        VolumeCapacityMode.liquidity_mode,
    )
    basis = execution_basis(config, model)
    table = price_table(state, basis)
    if table is None:
        return None
    index = price_index(table, product, signal_timestamps, state=state)
    price_pos = int(index.searchsorted(after_timestamp, side="right"))
    if price_pos >= len(index):
        return None
    price_ts = cast(pd.Timestamp, index[price_pos])
    event_ts = bar_price_visibility_timestamp(
        index,
        price_pos=price_pos,
        basis=basis,
        config=config,
        bar_freq=(
            resolved_bar_frequency_for_strategy(state, strategy)
            or market_data_store_for(state).execution_frequency_for(table)
        ),
    )
    if event_ts <= after_timestamp:
        raise ValueError(
            "next execution opportunity must be after the triggering event"
        )
    return event_ts, price_ts, basis, model


def execution_basis(config, model: str) -> str:
    ref = (
        OrderExecutionModule.volume_execution_price_basis
        if model == "bar_volume_limited"
        else OrderExecutionModule.execution_price_basis
    )
    default = "close" if model == "bar_volume_limited" else "open"
    return str(config.get(ref, default) or default).lower()


def price_table(state, basis: str) -> pd.DataFrame | None:
    tables = market_price_tables_for(state)
    table = tables.get(basis) if isinstance(tables, dict) else None
    if isinstance(table, pd.DataFrame) and not table.empty:
        return table
    fallback = current_prices_table_for(state)
    return fallback if isinstance(fallback, pd.DataFrame) and not fallback.empty else None


def price_index(
    table: pd.DataFrame,
    product: Any | None,
    signal_timestamp_fn,
    *,
    state: Any | None = None,
) -> pd.DatetimeIndex:
    if state is not None:
        return market_data_store_for(state).execution_price_index(table, product)
    if product is None or product not in table.columns:
        return signal_timestamp_fn(table)
    series = table[product].dropna()
    return signal_timestamp_fn(series) if not series.empty else pd.DatetimeIndex([])


def schedule_cache_key(current_ts, delay, basis, bar_freq, table, product):
    freq = getattr(bar_freq, "name", str(bar_freq)) if bar_freq is not None else None
    product_name = str(getattr(product, "name", product)) if product is not None else None
    return current_ts.value, str(current_ts.tz), delay, basis, freq, id(table), product_name
