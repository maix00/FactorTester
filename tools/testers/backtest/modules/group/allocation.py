"""Group target allocation adapters over reusable allocation tools."""

from __future__ import annotations

from typing import Any, cast

import pandas as pd

from tools.testers.backtest.modules.factor import FactorModule
from tools.testers.backtest.modules.factor_signal import FactorSignalModule
from tools.testers.backtest.modules.market_data import (
    MarketDataModule,
    current_prices_table_for,
    historical_fields_for_product,
)
from tools.testers.backtest.modules.time_index_lookup import row_at
from tools.testers.backtest.policies.allocation import equal_weight, inverse_measure_weight
from tools.testers.backtest.policies.factor_roles import factor_weight


def allocate_weights(state, ctx, strategy, members: frozenset) -> dict:
    from tools.testers.backtest.modules.group_membership import GroupMembershipModule

    if not members:
        return {}
    config = state.config_for(strategy)
    policy = config.get(GroupMembershipModule.allocation_policy, "equal_notional")
    if policy == "factor_sizing":
        roles = ctx.get_for(FactorModule.factor_role_values, strategy, {}) or {}
        primary = ctx.get_for(FactorSignalModule.signal_value, strategy, {}) or {}
        return factor_weight(
            members,
            roles.get("sizing", primary),
            transform=str(config.get(GroupMembershipModule.sizing_transform, "proportional")),
        )
    if policy == "equal_margin":
        return _equal_margin(ctx, strategy, members)
    if policy != "inverse_volatility":
        return equal_weight(members)

    lookback = config.get(GroupMembershipModule.volatility_lookback, 20)
    warmup = config.get(GroupMembershipModule.volatility_warmup, "equal_notional")
    table = current_prices_table_for(state)
    volatility = {}
    for product in members:
        value = _trailing_volatility(state, table, product, ctx.timestamp, lookback)
        if value is None or value <= 0:
            if warmup == "error":
                raise ValueError(
                    f"insufficient price history to estimate volatility for {product!r} "
                    f"(need {lookback} trailing periods)"
                )
            continue
        volatility[product] = value
    return inverse_measure_weight(members, volatility, missing="equal_share")


def rolling_volatility_table(state, table: pd.DataFrame, lookback: int) -> pd.DataFrame:
    key = (id(table), int(lookback))
    cache = state.target_store.rolling_volatility_tables
    if key not in cache:
        returns = table.pct_change(fill_method=None)
        cache[key] = returns.rolling(
            window=int(lookback), min_periods=int(lookback),
        ).std()
    return cache[key]


def _equal_margin(ctx, strategy, members: frozenset) -> dict:
    ratios = ctx.get_for(
        MarketDataModule.current_historical_fields,
        strategy,
        ctx.get(MarketDataModule.current_historical_fields, {}),
    ) or {}
    measures = {}
    for product in members:
        value = _margin_ratio(ratios, product)
        if value is not None and value > 0:
            measures[product] = value
    return inverse_measure_weight(members, measures, missing="exclude")


def _margin_ratio(fields: dict, product) -> float | None:
    values = historical_fields_for_product(fields, product)
    for key in ("LongMarginRatioByMoney", "ShortMarginRatioByMoney", "MarginRatio"):
        try:
            value = float(cast(Any, values.get(key)))
        except (TypeError, ValueError):
            continue
        if value > 0:
            return value
    return None


def _trailing_volatility(state, table, product, timestamp, lookback: int) -> float | None:
    if table is None or product not in table.columns:
        return None
    try:
        row = row_at(rolling_volatility_table(state, table, lookback), timestamp, asof=True)
    except KeyError:
        return None
    value = row.get(product)
    return float(value) if pd.notna(value) else None
