"""Timestamp-ordered causal fallback for group intent precomputation."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, cast

import pandas as pd

from tools.testers.backtest.modules.market_data import (
    _historical_fields_for_strategy,
    current_historical_fields_at,
    current_prices_at,
)
from tools.testers.backtest.modules.target import target_weight_intent
from tools.testers.backtest.modules.time_index_lookup import signal_event_times
from tools.testers.backtest.modules.group.precompute.context import TargetPrecomputeContext
from tools.testers.backtest.modules.group.precompute.values import (
    precomputed_factor_values,
    signal_values_from_table,
)
from tools.testers.backtest.modules.group.selection import compute_group_target_weights


def precompute_sequential(state, strategies: Sequence[Any]) -> None:
    from tools.testers.backtest.modules.group_membership import GroupMembershipModule

    signal_store = state.factor_signal_store
    by_event: dict[Any, list[tuple[Any, Any, dict, dict, dict]]] = {}
    for strategy in strategies:
        table = signal_store.precomputed_role_tables_for(strategy).get("ranking")
        if table is None:
            table = signal_store.precomputed_table_for(strategy)
        if table is None:
            continue
        state.target_store.precomputed_target_intents.setdefault(strategy, {})
        for event_time in signal_event_times(table):
            primary, roles = precomputed_factor_values(
                signal_store, strategy, event_time.index_key,
            )
            by_event.setdefault(event_time.index_key, []).append((
                strategy, event_time,
                signal_values_from_table(table, event_time.index_key),
                primary, roles,
            ))

    established: dict[Any, dict[Any, float]] = {}
    previous: dict[Any, frozenset | None] = {}
    ordered = sorted(
        by_event.values(), key=lambda items: cast(pd.Timestamp, items[0][1].timestamp),
    )
    for items in ordered:
        timestamp = cast(pd.Timestamp, items[0][1].timestamp)
        prices = current_prices_at(state, timestamp)
        needs_fields = any(
            state.config_for(strategy).get(
                GroupMembershipModule.allocation_policy, "equal_notional",
            ) == "equal_margin"
            for strategy, _event, _signal, _primary, _roles in items
        )
        base_fields = current_historical_fields_at(state, timestamp) if needs_fields else {}
        field_cache: dict[Any, dict] = {}
        ranked_cache: dict[frozenset, Sequence[tuple[Any, float]]] = {}
        bucket_cache: dict[tuple[frozenset, int, int], frozenset] = {}
        for strategy, event_time, signal, primary, roles in items:
            config = state.config_for(strategy)
            fields = _strategy_fields(
                state, strategy, config, timestamp, base_fields, field_cache,
            ) if needs_fields else {}
            context = TargetPrecomputeContext(
                timestamp=timestamp, prices=prices, historical_fields=base_fields,
                strategy_fields={strategy: fields}, factor_values={strategy: primary},
                role_values={strategy: roles},
            )
            weights, members, reason = compute_group_target_weights(
                state, context, strategy, signal,
                established=established.get(strategy),
                last_membership=previous.get(strategy),
                ranked_cache=ranked_cache, bucket_cache=bucket_cache,
            )
            if reason not in {"buy_and_hold_established_target", "membership_unchanged"} and weights:
                established[strategy] = weights
                previous[strategy] = members
            intent = target_weight_intent(weights, reason=reason)
            table = state.target_store.precomputed_target_intents[strategy]
            table[event_time.index_key] = intent
            table[timestamp] = intent


def _strategy_fields(state, strategy, config, timestamp, base_fields, cache):
    fields = cache.get(strategy)
    if fields is None:
        ledger = state.ledger_for_strategy(strategy)
        fields = _historical_fields_for_strategy(
            base_fields, config, timestamp,
            ledger_config=state.ledger_config_for(ledger),
        )
        cache[strategy] = fields
    return fields
