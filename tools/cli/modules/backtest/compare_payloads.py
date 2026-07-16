"""Payload builders for backtest compare scenarios."""

from __future__ import annotations

from typing import Any

import click

from tools.cli.core.context import client_from_config
from tools.cli.modules.backtest import template_state as template_state_helpers
from tools.cli.modules.backtest.run_payloads import serialize_ls_config_for_run
from tools.cli.modules.backtest.shared.selectors import selection_label
from tools.cli.modules.products.controller import product_group_selection


def volume_capacity_margin_compare_payload(
    state,
    *,
    volume_rate: float,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, str]]]:
    if not state.backtest_groups:
        raise click.ClickException("没有可对比的分组；请先加载模板或新增分组")
    scenarios: list[dict[str, str]] = [
        {
            "key": "cap_inf_margin_none",
            "label": "无限容量/无保证金",
            "description": "liquidity_mode=infinite, margin_mode=none",
        },
        {
            "key": "cap_limited_margin_none",
            "label": f"容量{volume_rate:g}/无保证金",
            "description": f"liquidity_mode=volume_participation, participation_rate={volume_rate:g}, margin_mode=none",
        },
        {
            "key": "cap_inf_margin_auto",
            "label": "无限容量/保证金auto",
            "description": "liquidity_mode=infinite, margin_mode=auto",
        },
    ]
    groups: list[dict[str, Any]] = []
    ls_configs: list[dict[str, Any]] = []
    ledger_configs: dict[str, dict[str, Any]] = {}
    strategy_book: dict[str, Any] = {"strategies": {}, "cash_pools": {}}
    for scenario in scenarios:
        id_map = {
            draft_group_id(group): scenario_strategy_id(scenario["key"], draft_group_id(group))
            for group in state.backtest_groups
        }
        for group in state.backtest_groups:
            old_id = draft_group_id(group)
            new_id = id_map[old_id]
            cloned = dict(group)
            cloned["id"] = new_id
            cloned["group_id"] = new_id
            cloned["strategy_id"] = new_id
            old_short = str(group.get("shortAlias") or group.get("short_alias") or group.get("name") or old_id)
            cloned["shortAlias"] = f"{scenario['label']} · {old_short}"
            cloned["name"] = f"{scenario['label']} · {group.get('name') or old_short}"
            for parent_key in ("parentId", "parent_id"):
                parent = str(cloned.get(parent_key) or "")
                if parent in id_map:
                    cloned[parent_key] = id_map[parent]
            apply_compare_scenario_settings(cloned, scenario["key"], volume_rate=volume_rate)
            groups.append(cloned)
            register_compare_ledger(strategy_book, ledger_configs, new_id, scenario["key"])
        for index, config in enumerate(state.backtest_ls_configs):
            old_id = str(config.get("strategy_id") or config.get("id") or f"ls-{index}")
            new_id = scenario_strategy_id(scenario["key"], old_id)
            cloned_ls = dict(config)
            cloned_ls["id"] = new_id
            cloned_ls["strategy_id"] = new_id
            old_short = str(config.get("shortAlias") or config.get("name") or old_id)
            cloned_ls["shortAlias"] = f"{scenario['label']} · {old_short}"
            cloned_ls["name"] = f"{scenario['label']} · {config.get('name') or old_short}"
            cloned_ls = serialize_ls_config_for_run(cloned_ls, index=index)
            remap_long_short_leg_ids(cloned_ls, id_map)
            apply_compare_scenario_settings(cloned_ls, scenario["key"], volume_rate=volume_rate)
            ls_configs.append(cloned_ls)
            register_compare_ledger(strategy_book, ledger_configs, new_id, scenario["key"])
    local_settings = dict(state.backtest_local_settings)
    for key in ("liquidity_mode", "participation_rate", "margin_mode"):
        local_settings.pop(key, None)
    payload = {
        "page_uuid": state.page_uuid,
        "local_settings": local_settings,
        "groups": groups,
        "ls_configs": ls_configs,
        "strategy_book": strategy_book,
        "ledger_configs": ledger_configs,
    }
    return payload, groups, ls_configs, scenarios


def factor_grid_payload(
    state,
    *,
    factor_family: str,
    n_values: tuple[str, ...],
    f_values: tuple[str, ...],
    product_groups: tuple[str, ...],
    rev: bool,
    liquidity_mode: str = "inherit",
    participation_rate: float = 0.02,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, str]]]:
    if not state.backtest_groups:
        raise click.ClickException("没有可研究的分组；请先加载模板或新增分组")
    factor_family = str(factor_family or state.factor_family or state.page_settings.get("factor_family") or "").strip()
    if not factor_family:
        raise click.ClickException("factor-grid 缺少因子家族；请传 --factor-family")
    n_list = [str(item).strip() for item in (n_values or ("1m", "2m", "3m", "5m", "10m")) if str(item).strip()]
    f_list = [str(item).strip() for item in (f_values or ("1m",)) if str(item).strip()]
    if not n_list or not f_list:
        raise click.ClickException("--n 和 --f 至少各有一个候选")
    client = client_from_config()
    product_group_selections = factor_grid_product_group_selections(client, product_groups)
    scenarios: list[dict[str, str]] = []
    groups: list[dict[str, Any]] = []
    ls_configs: list[dict[str, Any]] = []
    ledger_configs: dict[str, dict[str, Any]] = {}
    strategy_book: dict[str, Any] = {"strategies": {}, "cash_pools": {}}
    for n_value in n_list:
        for f_value in f_list:
            alias = factor_grid_alias(factor_family, n_value, f_value, rev=rev)
            register_factor_alias(state, client, alias, factor_family=factor_family)
            product_items = product_group_selections or [None]
            for product_group_selection_item in product_items:
                product_label = (
                    selection_label(product_group_selection_item)
                    if product_group_selection_item is not None
                    else "继承产品组"
                )
                scenario_key = factor_grid_key(alias, product_label)
                scenario_label = f"{alias} · {product_label}"
                scenarios.append({
                    "key": scenario_key,
                    "label": scenario_label,
                    "description": f"factor={alias}, product_group={product_label}",
                })
                scenario_source_groups = factor_grid_source_groups(
                    state.backtest_groups,
                    overrides_product_group=product_group_selection_item is not None,
                )
                id_map = {
                    draft_group_id(group): scenario_strategy_id(scenario_key, draft_group_id(group))
                    for group in scenario_source_groups
                }
                for group in scenario_source_groups:
                    old_id = draft_group_id(group)
                    new_id = id_map[old_id]
                    cloned = dict(group)
                    cloned["id"] = new_id
                    cloned["group_id"] = new_id
                    cloned["strategy_id"] = new_id
                    old_short = str(group.get("shortAlias") or group.get("short_alias") or group.get("name") or old_id)
                    cloned["shortAlias"] = f"{scenario_label} · {old_short}"
                    cloned["name"] = f"{scenario_label} · {group.get('name') or old_short}"
                    cloned["factor"] = alias
                    cloned["factorAlias"] = alias
                    cloned["factor_family_alias"] = factor_family
                    apply_factor_grid_capacity_override(cloned, liquidity_mode=liquidity_mode, participation_rate=participation_rate)
                    if product_group_selection_item is not None:
                        cloned["product_path_selection"] = dict(product_group_selection_item)
                    for parent_key in ("parentId", "parent_id"):
                        parent = str(cloned.get(parent_key) or "")
                        if parent in id_map:
                            cloned[parent_key] = id_map[parent]
                    cloned["compare_scenario"] = scenario_key
                    groups.append(cloned)
                    register_factor_grid_ledger(strategy_book, ledger_configs, new_id, cloned)
                for index, config in enumerate(state.backtest_ls_configs):
                    old_id = str(config.get("strategy_id") or config.get("id") or f"ls-{index}")
                    new_id = scenario_strategy_id(scenario_key, old_id)
                    cloned_ls = dict(config)
                    cloned_ls["id"] = new_id
                    cloned_ls["strategy_id"] = new_id
                    old_short = str(config.get("shortAlias") or config.get("name") or old_id)
                    cloned_ls["shortAlias"] = f"{scenario_label} · {old_short}"
                    cloned_ls["name"] = f"{scenario_label} · {config.get('name') or old_short}"
                    apply_factor_grid_capacity_override(cloned_ls, liquidity_mode=liquidity_mode, participation_rate=participation_rate)
                    cloned_ls = serialize_ls_config_for_run(cloned_ls, index=index)
                    remap_long_short_leg_ids(cloned_ls, id_map)
                    cloned_ls["compare_scenario"] = scenario_key
                    ls_configs.append(cloned_ls)
                    register_factor_grid_ledger(strategy_book, ledger_configs, new_id, cloned_ls)
    payload = {
        "page_uuid": state.page_uuid,
        "local_settings": dict(state.backtest_local_settings),
        "groups": groups,
        "ls_configs": ls_configs,
        "strategy_book": strategy_book,
        "ledger_configs": ledger_configs,
    }
    return payload, groups, ls_configs, scenarios


def factor_grid_alias(factor_family: str, n_value: str, f_value: str, *, rev: bool) -> str:
    alias = f"{factor_family}|N:{n_value}|$F:{f_value}"
    if rev:
        alias += "|$Rev"
    return alias


def factor_grid_key(alias: str, product_label: str) -> str:
    raw = f"{alias}__{product_label}"
    return "fg_" + "".join(ch if ch.isalnum() else "_" for ch in raw)[:96]


def factor_grid_source_groups(groups: list[dict[str, Any]], *, overrides_product_group: bool) -> list[dict[str, Any]]:
    if not overrides_product_group:
        return list(groups)
    return [group for group in groups if not group_has_product_mask(group)]


def group_has_product_mask(group: dict[str, Any]) -> bool:
    for key in ("productMask", "product_mask", "product_mask_names"):
        value = group.get(key)
        if isinstance(value, dict) and any(bool(item) for item in value.values()):
            return True
        if isinstance(value, (list, tuple, set)) and bool(value):
            return True
    return False


def apply_factor_grid_capacity_override(target: dict[str, Any], *, liquidity_mode: str, participation_rate: float) -> None:
    if liquidity_mode == "inherit":
        return
    target["liquidity_mode"] = liquidity_mode
    if liquidity_mode == "volume_participation":
        target["participation_rate"] = participation_rate


def register_factor_grid_ledger(
    strategy_book: dict[str, Any],
    ledger_configs: dict[str, dict[str, Any]],
    strategy_id: str,
    settings: dict[str, Any],
) -> None:
    ledger_id = f"private:{strategy_id}"
    strategy_book.setdefault("strategies", {})[strategy_id] = {
        "ledger_ids": [ledger_id],
        "default_ledger_id": ledger_id,
    }
    strategy_book.setdefault("cash_pools", {})[ledger_id] = ledger_id
    ledger_config_keys = {
        "fee_mode",
        "fixed_fee_rate",
        "margin_mode",
        "fixed_margin_ratio",
        "accounting_mode",
        "daily_mark_to_market_enabled",
        "cost_basis_method",
        "use_int_position",
        "tradability_policy",
        "clearing_rounding_policy",
        "cash_reserve_ratio",
        "cash_reserve_major",
        "margin_call_mode",
        "liquidation_target_buffer",
    }
    ledger_configs[ledger_id] = {
        key: settings[key]
        for key in ledger_config_keys
        if key in settings
    }


def factor_grid_product_group_selections(client, product_groups: tuple[str, ...]) -> list[dict[str, Any]]:
    names = [str(item).strip() for item in product_groups if str(item).strip()]
    if not names:
        return []
    candidates = client.list_candidates("product_path_candidates")
    selections: list[dict[str, Any]] = []
    for name in names:
        match = next(
            (
                item for item in candidates
                if name in {
                    str(item.get("name") or ""),
                    str(item.get("label") or ""),
                    str(item.get("id") or ""),
                    str(item.get("product_path_selection_id") or ""),
                }
            ),
            None,
        )
        if match is None:
            raise click.ClickException(f"未找到产品组候选: {name}")
        selections.append(product_group_selection(match))
    return selections


def register_factor_alias(state, client, alias: str, *, factor_family: str) -> None:
    candidates = list(state.page_settings.get("factor_candidates") or [])
    known = {str(item.get("factor_alias") or item.get("alias") or "") for item in candidates if isinstance(item, dict)}
    if alias in known:
        return
    params = template_state_helpers.params_from_factor_alias(alias, factor_family)
    data = client.add_candidate("factor", {
        "factor_family_alias": factor_family,
        "params": params,
        "page_uuid": state.page_uuid,
    })
    factor_alias = str(data.get("factor_alias") or alias)
    candidates.append({"factor_alias": factor_alias, "params": params})
    state.page_settings["factor_candidates"] = candidates


def apply_compare_scenario_settings(target: dict[str, Any], scenario_key: str, *, volume_rate: float) -> None:
    if scenario_key == "cap_limited_margin_none":
        target["liquidity_mode"] = "volume_participation"
        target["participation_rate"] = volume_rate
        target["margin_mode"] = "none"
    elif scenario_key == "cap_inf_margin_auto":
        target["liquidity_mode"] = "infinite"
        target.pop("participation_rate", None)
        target["margin_mode"] = "auto"
    else:
        target["liquidity_mode"] = "infinite"
        target.pop("participation_rate", None)
        target["margin_mode"] = "none"
    target["compare_scenario"] = scenario_key


def register_compare_ledger(
    strategy_book: dict[str, Any],
    ledger_configs: dict[str, dict[str, Any]],
    strategy_id: str,
    scenario_key: str,
) -> None:
    ledger_id = f"private:{strategy_id}"
    strategy_book.setdefault("strategies", {})[strategy_id] = {
        "ledger_ids": [ledger_id],
        "default_ledger_id": ledger_id,
    }
    strategy_book.setdefault("cash_pools", {})[ledger_id] = ledger_id
    ledger_configs[ledger_id] = {
        "margin_mode": "auto" if scenario_key == "cap_inf_margin_auto" else "none",
    }


def scenario_strategy_id(scenario_key: str, raw_id: str) -> str:
    clean = str(raw_id).replace(":", "_").replace("/", "_").replace(" ", "_")
    return f"cmp_{scenario_key}__{clean}"


def draft_group_id(group: dict[str, Any]) -> str:
    group_id = str(group.get("id") or group.get("group_id") or group.get("strategy_id") or "").strip()
    if not group_id:
        raise click.ClickException(f"分组缺少 id: {group.get('name') or group}")
    return group_id


def remap_long_short_leg_ids(config: dict[str, Any], id_map: dict[str, str]) -> None:
    for key in ("longGroupId", "long_group_id", "shortGroupId", "short_group_id"):
        value = str(config.get(key) or "")
        if value in id_map:
            config[key] = id_map[value]
    for key in ("long", "short"):
        legs = config.get(key)
        if not isinstance(legs, list):
            continue
        remapped = []
        for leg in legs:
            if isinstance(leg, dict):
                item = dict(leg)
                for leg_key in ("group_id", "strategy_id", "id"):
                    value = str(item.get(leg_key) or "")
                    if value in id_map:
                        item[leg_key] = id_map[value]
                remapped.append(item)
            else:
                value = str(leg)
                remapped.append(id_map.get(value, value))
        config[key] = remapped
