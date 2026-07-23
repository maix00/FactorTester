"""Read factor and role values by frozen signal index key."""

from typing import Any, cast

import pandas as pd

from tools.testers.backtest.modules.time_index_lookup import row_at_index_key


def signal_values_from_table(table: pd.DataFrame, index_key: Any) -> dict:
    try:
        row = row_at_index_key(table, index_key) if index_key is not None else table.iloc[-1]
    except KeyError:
        return {}
    return {product: float(cast(Any, row[product])) for product in table.columns}


def precomputed_factor_values(signal_store, strategy, index_key: Any) -> tuple[dict, dict]:
    primary_table = signal_store.precomputed_table_for(strategy)
    primary = signal_values_from_table(primary_table, index_key) if primary_table is not None else {}
    roles = {
        role: signal_values_from_table(table, index_key)
        for role, table in signal_store.precomputed_role_tables_for(strategy).items()
    }
    return primary, roles
