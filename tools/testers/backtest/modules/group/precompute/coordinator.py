"""Choose the vectorized optimization or causal sequential adapter."""

from __future__ import annotations

from typing import Any

import pandas as pd

from tools.testers.backtest.modules.group.precompute.sequential import precompute_sequential
from tools.testers.backtest.modules.group.precompute.vectorized import (
    can_vectorize,
    precompute_vectorized,
)
from tools.testers.backtest.modules.group.selection import validate_group_factor_roles


def precompute_group_target_intents(state, ctx, strategies) -> None:
    signal_store = state.factor_signal_store
    fallback: list[Any] = []
    grouped: dict[int, tuple[pd.DataFrame, list[Any]]] = {}
    for strategy in strategies:
        validate_group_factor_roles(state.config_for(strategy))
        table = signal_store.precomputed_role_tables_for(strategy).get("ranking")
        if table is None:
            table = signal_store.precomputed_table_for(strategy)
        if table is None:
            continue
        if not can_vectorize(state, strategy):
            fallback.append(strategy)
            continue
        grouped.setdefault(id(table), (table, []))[1].append(strategy)
        state.target_store.precomputed_target_intents.setdefault(strategy, {})
    for table, selected in grouped.values():
        if not precompute_vectorized(state, table, selected):
            fallback.extend(selected)
    precompute_sequential(state, fallback)
