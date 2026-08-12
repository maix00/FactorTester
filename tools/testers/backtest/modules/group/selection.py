"""Causal screen, rank, bucket, rebalance, and allocation plan."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pandas as pd

from tools.testers.backtest.modules.factor import FactorModule, factor_role_bindings_for
from tools.testers.backtest.modules.factor_signal import FactorSignalModule
from tools.testers.backtest.modules.market_data import MarketDataModule, is_product_tradable
from tools.testers.backtest.modules.group.allocation import allocate_weights
from tools.testers.backtest.policies.cross_section import rank_cross_section, select_rank_group
from tools.testers.backtest.policies.factor_roles import screen_ranking_values
from tools.testers.backtest.policies.rebalance import (
    reuse_buy_and_hold_target,
    reuse_unchanged_membership_target,
    validate_rebalance_configuration,
)


def compute_group_target_weights(
    state, ctx, strategy, ranking_values: dict, *,
    established: dict[Any, float] | None = None,
    last_membership: frozenset | None = None,
    ranked_cache: dict[frozenset, Sequence[tuple[Any, float]]] | None = None,
    bucket_cache: dict[tuple[frozenset, int, int], frozenset] | None = None,
) -> tuple[dict, frozenset | None, str]:
    from tools.testers.backtest.modules.group_membership import GroupMembershipModule

    config = state.config_for(strategy)
    position_policy = config.get(
        GroupMembershipModule.position_policy, "rebalance_to_target",
    )
    reuse = reuse_buy_and_hold_target(position_policy, established)
    if position_policy == "incremental_buy_and_hold_fixed_leverage":
        reuse = None
    if reuse is not None:
        return reuse[0], last_membership, reuse[1]
    trigger = config.get(GroupMembershipModule.rebalance_trigger, "on_factor_signal")
    allocation = config.get(GroupMembershipModule.allocation_policy, "equal_notional")
    validate_rebalance_configuration(
        trigger,
        allocation_is_membership_only=allocation == "equal_notional",
        allocation_name=allocation,
    )
    ranking_values = tradable_signal_values(
        ranking_values,
        ctx.get(MarketDataModule.current_prices),
        ctx.get(MarketDataModule.current_tradable_status, None),
    )
    roles = ctx.get_for(FactorModule.factor_role_values, strategy, {}) or {}
    primary = ctx.get_for(FactorSignalModule.signal_value, strategy, ranking_values)
    ranking_values = screen_group_universe(
        config, ranking_values, roles.get("screen", primary),
    )
    split_count = config.get(GroupMembershipModule.split_count, 1)
    group_index = config.get(GroupMembershipModule.group_index, 0)
    if not ranking_values or split_count <= 0:
        return {}, None, "empty_group_membership"
    rank_key = frozenset(ranking_values.items())
    ranked = ranked_cache.get(rank_key) if ranked_cache is not None else None
    if ranked is None:
        ranked = rank_cross_section(ranking_values, tie_breaker=product_name)
        if ranked_cache is not None:
            ranked_cache[rank_key] = ranked
    bucket_key = (rank_key, split_count, group_index)
    members = bucket_cache.get(bucket_key) if bucket_cache is not None else None
    if members is None:
        members = select_rank_group(
            ranked, split_count=split_count, group_index=group_index,
        )
        if bucket_cache is not None:
            bucket_cache[bucket_key] = members
    mask = config.get(GroupMembershipModule.product_mask_names)
    if mask:
        allowed = {str(name) for name in mask}
        members = frozenset(product for product in members if product_name(product) in allowed)
    if position_policy == "incremental_buy_and_hold_fixed_leverage":
        locked = frozenset(established or {})
        newcomers = frozenset(product for product in members if product not in locked)
        if established is None:
            if not members:
                return {}, members, "incremental_buy_and_hold_waiting_for_membership"
            return (
                allocate_weights(state, ctx, strategy, members),
                members,
                "incremental_buy_and_hold_initial_membership",
            )
        if not newcomers:
            return established, locked, "incremental_buy_and_hold_established_target"
        combined = frozenset(locked | set(newcomers))
        return (
            allocate_weights(state, ctx, strategy, combined),
            combined,
            "incremental_buy_and_hold_add_members",
        )
    reuse = reuse_unchanged_membership_target(
        trigger, members, last_membership, established,
    )
    if reuse is not None:
        return reuse[0], members, reuse[1]
    return allocate_weights(state, ctx, strategy, members), members, "group_membership"


def validate_group_factor_roles(config) -> None:
    from tools.testers.backtest.modules.group_membership import GroupMembershipModule

    roles = factor_role_bindings_for(config)
    incompatible = sorted(set(roles) - {"ranking", "screen", "sizing"})
    if incompatible:
        raise ValueError(
            "factor roles incompatible with group strategy: "
            + ", ".join(incompatible)
        )
    if "screen" in roles and config.get(GroupMembershipModule.screen_rule, "disabled") == "disabled":
        raise ValueError("screen factor role requires screen_rule to be enabled")
    if "sizing" in roles and config.get(GroupMembershipModule.allocation_policy, "equal_notional") != "factor_sizing":
        raise ValueError("sizing factor role requires allocation_policy='factor_sizing'")


def screen_group_universe(config, ranking_values: dict, screen_values: dict) -> dict:
    from tools.testers.backtest.modules.group_membership import GroupMembershipModule

    return screen_ranking_values(
        ranking_values, screen_values or {},
        rule=str(config.get(GroupMembershipModule.screen_rule, "disabled") or "disabled"),
        lower=float(config.get(GroupMembershipModule.screen_lower, 0.0) or 0.0),
        upper=float(config.get(GroupMembershipModule.screen_upper, 0.0) or 0.0),
    )


def tradable_signal_values(
    values: dict, current_prices: dict | None, tradable_status: dict | None = None,
) -> dict:
    if not values or (tradable_status is not None and not tradable_status):
        return {}
    if tradable_status is None and current_prices is not None and not current_prices:
        return {}
    return {
        product: value for product, value in values.items()
        if is_product_tradable(tradable_status, product, current_prices)
        and not pd.isna(value)
    }


def product_name(product: Any) -> str:
    return str(getattr(product, "name", product))
