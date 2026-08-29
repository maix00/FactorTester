"""Prepare one immutable grouped-research RunSpec without loading market bars."""

from __future__ import annotations

import uuid
from copy import deepcopy
from typing import Any

from .settings import (
    build_group_owner_rows,
    build_long_short_owner_rows,
    get_group_test_registry,
    groups_with_parent_fallback,
    long_short_strategy_id,
    payload_execution_settings,
    resolve_flat_backtest_settings,
    resolve_group_strategy_settings,
    resolve_long_short_strategy_settings,
    resolve_run_datetimes,
)
from .strategy_identity import strategy_configuration_id
from .strategy_plan_runtime import (
    apply_custom_strategy_overrides,
    strategy_aliases_for_plan,
    strategy_plan_from_payload,
)


def prepare_group_run_spec(data: dict[str, Any]) -> dict[str, Any]:
    """Resolve immutable group settings and selections without loading bars."""
    payload = deepcopy(data)
    flat_groups_raw = payload.get("groups")
    if not isinstance(flat_groups_raw, list) or not flat_groups_raw:
        raise ValueError("groups 必须是非空数组")
    run_id = str(
        payload.get("run_id") or payload.get("run_token") or uuid.uuid4().hex
    )
    owner = str(payload.get("_owner") or "")
    payload["_group_owner_username"] = owner
    flat_groups = groups_with_parent_fallback(flat_groups_raw)
    payload["groups"] = flat_groups
    flat_ls_configs = payload.get("ls_configs") or []
    if not isinstance(flat_ls_configs, list):
        raise ValueError("ls_configs 必须是数组")

    execution_settings = payload_execution_settings(payload)
    data_source = str(execution_settings.get("data_source") or "").strip()
    frequency = str(execution_settings.get("frequency") or "").strip()
    if data_source and data_source != "auto":
        raise ValueError(
            f"当前分组测试不支持数据源 {data_source}，请使用自动"
        )
    if frequency and frequency != "auto":
        raise ValueError(
            f"当前分组测试不支持数据频率 {frequency}，请使用自动"
        )

    resolved_backtest_settings = resolve_flat_backtest_settings(
        payload,
        flat_groups,
        flat_ls_configs,
    )
    run_registry = get_group_test_registry()
    execution_settings_by_module = run_registry.collect_local_only_settings(
        resolved_backtest_settings
    )
    market_rule_fallback = execution_settings_by_module.get(
        "market_rules", {}
    ).get("market_rule_fallback", "latest_available")
    evaluation_split = execution_settings_by_module.get(
        "evaluation_range", {}
    ).get("evaluation_split") or None
    first_group_id = str(flat_groups[0].get("id") or "group-0")
    fallback_group_settings = resolved_backtest_settings.get(first_group_id, {})
    factor_mode = fallback_group_settings.get("factor_mode", "auto")
    start_dt, end_dt = resolve_run_datetimes(
        execution_settings,
        resolved_backtest_settings,
    )

    selection_cache: dict[str, Any] = {}
    resolved_settings_by_alias: dict[str, dict[str, Any]] = {}
    group_owner: list[dict[str, Any]] = []
    for group in flat_groups:
        if not isinstance(group, dict):
            continue
        group_id = str(
            group.get("id") or f"group-{len(resolved_settings_by_alias)}"
        )
        resolved_settings_by_alias[group_id] = resolve_group_strategy_settings(
            group,
            resolved_backtest_settings=resolved_backtest_settings,
            fallback_group_settings=fallback_group_settings,
            page_uuid="",
            username=owner,
            data=payload,
            page_factors_dict={},
            selection_cache=selection_cache,
        )
    group_owner.extend(build_group_owner_rows(flat_groups, is_ls=False))
    for row in group_owner:
        strategy_id = str(row.get("strategy_id") or "")
        row["strategy_configuration_id"] = strategy_configuration_id(
            row, resolved_settings_by_alias[strategy_id],
        )
    group_owner_by_id = {
        str(row.get("group_id")): row
        for row in group_owner
    }

    normalized_ls_configs: list[dict[str, Any]] = []
    for index, config in enumerate(flat_ls_configs):
        if not isinstance(config, dict):
            continue
        normalized = dict(config)
        strategy_id = long_short_strategy_id(normalized, index)
        normalized["strategy_id"] = strategy_id
        normalized.setdefault("id", strategy_id)
        normalized_ls_configs.append(normalized)
        resolved_settings_by_alias[strategy_id] = (
            resolve_long_short_strategy_settings(
                normalized,
                resolved_backtest_settings=resolved_backtest_settings,
                source_settings_by_alias=resolved_settings_by_alias,
                fallback_group_settings=fallback_group_settings,
                execution_settings=execution_settings,
            )
        )
    long_short_owners = build_long_short_owner_rows(
        normalized_ls_configs,
        source_owner_by_id=group_owner_by_id,
    )
    for row in long_short_owners:
        strategy_id = str(row.get("strategy_id") or "")
        row["strategy_configuration_id"] = strategy_configuration_id(
            row, resolved_settings_by_alias[strategy_id],
        )
    group_owner.extend(long_short_owners)
    if not resolved_settings_by_alias:
        raise ValueError("没有有效的分组配置")

    strategy_plan = strategy_plan_from_payload(payload)
    custom_scope = payload.get("custom_strategy_scope")
    if not isinstance(custom_scope, dict):
        custom_scope = {}
    if strategy_plan:
        aliases = strategy_aliases_for_plan(
            strategy_plan, list(resolved_settings_by_alias),
        )
        apply_custom_strategy_overrides(
            resolved_settings_by_alias,
            strategy_plan,
            aliases,
            overrides=custom_scope.get("overrides"),
            product_mask=custom_scope.get("product_mask"),
        )

    all_products: list[Any] = []
    seen_products: set[Any] = set()
    for selection in selection_cache.values():
        for product in selection.products:
            if product not in seen_products:
                seen_products.add(product)
                all_products.append(product)

    return {
        "payload": payload,
        "run_id": run_id,
        "owner": owner,
        "flat_groups": flat_groups,
        "flat_ls_configs": flat_ls_configs,
        "normalized_ls_configs": normalized_ls_configs,
        "resolved_backtest_settings": resolved_backtest_settings,
        "resolved_settings_by_alias": resolved_settings_by_alias,
        "group_owner": group_owner,
        "all_products": all_products,
        "execution_settings": execution_settings,
        "market_rule_fallback": market_rule_fallback,
        "evaluation_split": evaluation_split,
        "run_registry": run_registry,
        "factor_mode": factor_mode,
        "start_dt": start_dt,
        "end_dt": end_dt,
        "custom_strategy_scope": deepcopy(custom_scope),
    }
