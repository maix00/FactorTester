"""Ordered precompute adapter for threshold state transitions."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, cast

import pandas as pd

from tools.testers.backtest.modules.market_data import MarketDataModule, current_prices_at
from tools.testers.backtest.modules.target import target_weight_intent
from tools.testers.backtest.modules.time_index_lookup import row_at_index_key, signal_event_times

from .selection import compute_threshold_target_weights
from .state import rankable_signal_values


class ThresholdPrecomputeContext:
    def __init__(self, *, timestamp: pd.Timestamp, prices: dict) -> None:
        self.timestamp = timestamp
        self._values = {
            MarketDataModule.current_prices: prices,
            MarketDataModule.current_tradable_status: None,
        }

    def get(self, ref, default=None):
        return self._values.get(ref, default)

    def get_for(self, ref, strategy, default=None):
        return default


def precompute_threshold_target_intents(state: Any, strategies: Sequence[object]) -> None:
    signal_store = state.factor_signal_store
    established: dict[Any, dict[Any, float]] = {}
    selections: dict[Any, dict[str, frozenset]] = {}
    by_event: dict[Any, list[tuple[Any, Any, dict, dict[str, dict]]]] = {}
    for strategy in strategies:
        table = signal_store.precomputed_table_for(strategy)
        if table is None:
            continue
        state.target_store.precomputed_target_intents.setdefault(strategy, {})
        role_tables = signal_store.precomputed_role_tables_for(strategy)
        for event_time in signal_event_times(table):
            by_event.setdefault(event_time.index_key, []).append((
                strategy,
                event_time,
                signal_values_from_table(table, event_time.index_key),
                {
                    role: signal_values_from_table(role_table, event_time.index_key)
                    for role, role_table in role_tables.items()
                },
            ))

    ordered = sorted(by_event.values(), key=lambda items: cast(pd.Timestamp, items[0][1].timestamp))
    for items in ordered:
        timestamp = cast(pd.Timestamp, items[0][1].timestamp)
        prices = current_prices_at(state, timestamp)
        ctx = ThresholdPrecomputeContext(timestamp=timestamp, prices=prices)
        for strategy, event_time, signal_value, role_values in items:
            weights, selection, reason = compute_threshold_target_weights(
                state,
                ctx,
                strategy,
                rankable_signal_values(signal_value, prices, None),
                factor_values_by_role={
                    role: rankable_signal_values(values, prices, None)
                    for role, values in role_values.items()
                },
                previous_selection=selections.get(strategy),
                previous_weights=established.get(strategy),
            )
            selections[strategy] = selection
            established[strategy] = weights
            intent = target_weight_intent(weights, reason=reason)
            target_table = state.target_store.precomputed_target_intents[strategy]
            target_table[event_time.index_key] = intent
            target_table[event_time.timestamp] = intent


def signal_values_from_table(table: pd.DataFrame, index_key: Any) -> dict:
    try:
        row = row_at_index_key(table, index_key) if index_key is not None else table.iloc[-1]
    except KeyError:
        return {}
    return {
        product: float(cast(Any, row[product]))
        for product in table.columns
        if not pd.isna(row[product])
    }
