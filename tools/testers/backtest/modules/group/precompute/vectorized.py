"""Vectorized optimization of the standard group selection plan."""

from __future__ import annotations

from typing import Any, cast

import pandas as pd

from tools.testers.backtest.modules.factor import factor_role_bindings_for
from tools.testers.backtest.modules.market_data import current_prices_table_for
from tools.testers.backtest.modules.time_index_lookup import signal_event_times
from tools.testers.backtest.modules.group.allocation import rolling_volatility_table
from tools.testers.backtest.modules.group.selection import product_name
from tools.testers.backtest.modules.group.precompute.timeline import (
    PrecomputedIntentAxis,
    PrecomputedIntentTimeline,
)


def can_vectorize(state, strategy) -> bool:
    from tools.testers.backtest.modules.group_membership import GroupMembershipModule

    config = state.config_for(strategy)
    roles = factor_role_bindings_for(config)
    return (
        not ({"screen", "sizing"} & set(roles))
        and config.get(GroupMembershipModule.screen_rule, "disabled") == "disabled"
        and config.get(GroupMembershipModule.position_policy, "rebalance_to_target") == "rebalance_to_target"
        and config.get(GroupMembershipModule.rebalance_trigger, "on_factor_signal") == "on_factor_signal"
        and config.get(GroupMembershipModule.allocation_policy, "equal_notional")
        in {"equal_notional", "inverse_volatility"}
    )


def precompute_vectorized(
    state,
    signal_table: pd.DataFrame,
    strategies: list[Any],
    *,
    price_alignment_cache: list[tuple[pd.Index, tuple[Any, ...], pd.DataFrame]] | None = None,
) -> bool:
    from tools.testers.backtest.modules.group_membership import GroupMembershipModule

    if signal_table.empty or not strategies:
        return True
    if not isinstance(signal_table.index, pd.DatetimeIndex):
        return False
    price_table = current_prices_table_for(state)
    if not isinstance(price_table, pd.DataFrame) or price_table.empty:
        return False
    products = sorted(signal_table.columns, key=product_name)
    if not products:
        return True
    try:
        signal = signal_table.loc[:, products]
        products_key = tuple(products)
        prices = None
        if price_alignment_cache is not None:
            for cached_index, cached_products, cached_prices in price_alignment_cache:
                if (
                    cached_products == products_key
                    and cached_index.equals(signal.index)
                ):
                    prices = cached_prices
                    break
        if prices is None:
            prices = price_table.reindex(signal.index, method="ffill").reindex(
                columns=products,
            )
            if price_alignment_cache is not None:
                price_alignment_cache.append((signal.index, products_key, prices))
    except Exception:
        return False
    index = cast(pd.DatetimeIndex, signal.index)
    rankable = signal.where(prices.notna() & (prices > 0))
    ranks = rankable.rank(axis=1, method="first", ascending=False, na_option="bottom")
    valid_counts = rankable.notna().sum(axis=1)
    event_times = list(signal_event_times(signal_table))
    if len(event_times) != len(signal_table.index):
        return False
    axis = PrecomputedIntentAxis(tuple(event_times))
    allocation_tables: dict[tuple[str, int], pd.DataFrame] = {}
    for strategy in strategies:
        config = state.config_for(strategy)
        split_count = int(config.get(GroupMembershipModule.split_count, 1) or 1)
        group_index = int(config.get(GroupMembershipModule.group_index, 0) or 0)
        if split_count <= 0:
            weights = pd.DataFrame(0.0, index=signal.index, columns=products)
        else:
            starts = (valid_counts * group_index / split_count).round()
            ends = (valid_counts * (group_index + 1) / split_count).round()
            membership = ranks.gt(starts, axis=0) & ranks.le(ends, axis=0) & rankable.notna()
            mask = config.get(GroupMembershipModule.product_mask_names)
            if mask:
                allowed = {str(name) for name in mask}
                membership = membership.loc[:, [
                    product for product in membership.columns if product_name(product) in allowed
                ]]
            weights = _weights(state, index, membership, strategy, allocation_tables)
        _store(state, strategy, axis, weights)
    return True


def _weights(state, index, membership, strategy, cache) -> pd.DataFrame:
    from tools.testers.backtest.modules.group_membership import GroupMembershipModule

    if membership.empty:
        return pd.DataFrame(0.0, index=index, columns=[])
    config = state.config_for(strategy)
    counts = membership.sum(axis=1).replace(0, pd.NA)
    if config.get(GroupMembershipModule.allocation_policy, "equal_notional") != "inverse_volatility":
        return membership.astype(float).div(counts, axis=0).fillna(0.0)
    lookback = int(config.get(GroupMembershipModule.volatility_lookback, 20) or 20)
    key = ("inverse_volatility", lookback)
    inv_vol = cache.get(key)
    if inv_vol is None:
        table = current_prices_table_for(state)
        vol = rolling_volatility_table(state, table, lookback).reindex(
            index, method="ffill",
        ).reindex(columns=membership.columns)
        inv_vol = (1.0 / vol).where(vol > 0)
        cache[key] = inv_vol
    else:
        inv_vol = inv_vol.reindex(columns=membership.columns)
    raw = inv_vol.where(membership)
    warm = membership & raw.isna()
    warm_counts = warm.sum(axis=1)
    fallback_share = (warm_counts / membership.sum(axis=1).replace(0, pd.NA)).fillna(0.0)
    weights = warm.astype(float).div(warm_counts.replace(0, pd.NA), axis=0).mul(fallback_share, axis=0)
    raw = raw.fillna(0.0)
    weights = weights.fillna(0.0).add(
        raw.div(raw.sum(axis=1).replace(0, pd.NA), axis=0).mul(1.0 - fallback_share, axis=0),
        fill_value=0.0,
    )
    return weights.fillna(0.0)


def _store(
    state,
    strategy,
    axis: PrecomputedIntentAxis,
    weights: pd.DataFrame,
) -> None:
    state.target_store.precomputed_target_intents[strategy] = (
        PrecomputedIntentTimeline.from_frame(
            axis,
            weights,
            reason="group_membership",
        )
    )
