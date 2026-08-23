"""Resolve grouped-research settings from one frozen RunSpec payload."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from tools.testers.backtest.modules.registry import GroupTestModuleRegistry
from tools.testers.settings import backtest_setting_registry
from tools.testers.settings.resolver import resolve_group_settings

from .factor_roles import resolve_factor_ref, resolve_factor_role_bindings


_GROUP_INHERIT_UNIQUE_KEYS = {"id", "name", "parentId", "_expanded"}
_AUTO_INFERRED_LEDGER_DEFAULTS = {
    "cost_basis_method": "WeightAverage",
    "daily_mark_to_market_enabled": False,
}
_group_test_registry: GroupTestModuleRegistry | None = None


def groups_with_parent_fallback(groups: list[dict]) -> list[dict]:
    """Build the runtime view where derived groups inherit omitted fields."""
    groups_by_id = {
        str(group.get("id")): group
        for group in groups
        if isinstance(group, dict) and group.get("id")
    }
    resolving: set[str] = set()
    resolved: dict[str, dict] = {}

    def resolve(group: dict) -> dict:
        group_id = str(group.get("id") or "")
        if group_id and group_id in resolved:
            return deepcopy(resolved[group_id])
        if group_id:
            if group_id in resolving:
                return deepcopy(group)
            resolving.add(group_id)
        merged = deepcopy(group)
        parent = groups_by_id.get(str(group.get("parentId") or ""))
        if isinstance(parent, dict):
            parent_view = resolve(parent)
            for key, value in parent_view.items():
                if key in _GROUP_INHERIT_UNIQUE_KEYS:
                    continue
                if merged.get(key) in (None, ""):
                    merged[key] = deepcopy(value)
        if group_id:
            resolving.discard(group_id)
            resolved[group_id] = deepcopy(merged)
        return merged

    return [resolve(group) if isinstance(group, dict) else group for group in groups]


def get_group_test_registry() -> GroupTestModuleRegistry:
    global _group_test_registry
    if _group_test_registry is None:
        _group_test_registry = GroupTestModuleRegistry()
    return _group_test_registry


def resolve_flat_backtest_settings(
    payload: dict[str, Any],
    groups: list[dict[str, Any]],
    ls_configs: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    app = backtest_setting_registry.get("group_test")
    setting_keys = set(app.settings)
    raw_local_settings = payload.get("local_settings")
    top_level_setting_keys = setting_keys.intersection(payload)
    # The immutable RunSpec stores registered settings only under
    # ``local_settings``.  The job runner, however, receives an explicit
    # execution projection that mirrors those values at the top level for the
    # legacy runtime call contract.  That projection carries the complete
    # nested RunSpec as proof of its source; accept it only when every mirror
    # exactly matches the nested authority.  A client-authored payload with
    # top-level settings, or a conflicting mirror, remains invalid.
    run_spec = payload.get("run_spec")
    run_spec_configuration = (
        run_spec.get("configuration") if isinstance(run_spec, dict) else None
    )
    run_spec_analysis = (
        run_spec_configuration.get("analyses", {}).get("backtest")
        if isinstance(run_spec_configuration, dict)
        and isinstance(run_spec_configuration.get("analyses"), dict)
        else None
    )
    run_spec_local_settings = (
        run_spec_analysis.get("local_settings")
        if isinstance(run_spec_analysis, dict)
        else None
    )
    nested_run_spec = (
        isinstance(raw_local_settings, dict)
        and isinstance(run_spec_local_settings, dict)
    )
    mirrored_runtime_settings = (
        nested_run_spec
        and raw_local_settings == run_spec_local_settings
        and all(
            raw_local_settings.get(key) == payload.get(key)
            for key in top_level_setting_keys
        )
    )
    if top_level_setting_keys and not mirrored_runtime_settings:
        raise ValueError(
            "registered settings must be nested under local_settings, "
            f"not top-level: {sorted(top_level_setting_keys)}"
        )
    local_values = (
        {
            key: raw_local_settings[key]
            for key in setting_keys
            if key in raw_local_settings
        }
        if isinstance(raw_local_settings, dict)
        else {}
    )
    group_ids: list[str] = []
    group_values: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(list(groups) + list(ls_configs or [])):
        if not isinstance(item, dict):
            continue
        group_id = str(item.get("id") or f"group-{index}")
        group_ids.append(group_id)
        group_values[group_id] = {
            key: item[key]
            for key in setting_keys
            if key in item
        }
    return resolve_group_settings(
        app,
        local_values=local_values,
        group_values=group_values,
        group_ids=group_ids,
    )


def payload_local_settings(payload: dict[str, Any]) -> dict[str, Any]:
    local_settings = payload.get("local_settings")
    return local_settings if isinstance(local_settings, dict) else {}


def _setting_value_label(definition: Any, value: Any) -> str:
    text = str(value)
    for option in definition.options:
        if str(option.value) == text:
            return option.label
    return text


def silent_default_settings_for_run(
    payload: dict[str, Any],
    groups: list[dict[str, Any]],
    ls_configs: list[dict[str, Any]],
    resolved: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Summarize strategy defaults applied to a sparse request."""
    app = backtest_setting_registry.get("group_test")
    silent_keys = ("allocation_policy", "rebalance_trigger", "position_policy")
    local_settings = payload_local_settings(payload)
    explicit_local = set(local_settings) if local_settings else set(payload)
    explicit_by_group: dict[str, set[str]] = {}
    for index, item in enumerate(list(groups) + list(ls_configs or [])):
        if not isinstance(item, dict):
            continue
        group_id = str(item.get("id") or f"group-{index}")
        explicit_by_group[group_id] = set(item)

    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for key in silent_keys:
        definition = app.settings.get(key)
        if definition is None or key in explicit_local:
            continue
        applied_values = []
        any_explicit_group = False
        for group_id, values in resolved.items():
            if key in explicit_by_group.get(group_id, set()):
                any_explicit_group = True
                continue
            if key in values:
                applied_values.append(values[key])
        if any_explicit_group or not applied_values:
            continue
        first = applied_values[0]
        if any(value != first for value in applied_values[1:]):
            continue
        value_label = _setting_value_label(definition, first)
        dedupe_key = (definition.label, value_label)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        result.append({
            "setting_key": key,
            "label": definition.label,
            "value": str(first),
            "value_label": value_label,
            "module": definition.module,
        })
    return result


def runtime_datetimes(payload: dict[str, Any]):
    from tools.data.types import DataTime

    local_settings = payload_local_settings(payload)

    def value(key: str, default: Any = None) -> Any:
        return (
            local_settings[key]
            if local_settings.get(key) not in (None, "")
            else default
        )

    precision = str(value("precision") or value("time_precision") or "exact")
    timezone = None if precision == "trading_day" else value("timezone")
    start_dt = DataTime.from_dict({
        "date": value("start_date"),
        "time": None if precision == "trading_day" else value("start_time"),
        "timezone": timezone,
    }, precision=precision)
    end_dt = DataTime.from_dict({
        "date": value("end_date"),
        "time": None if precision == "trading_day" else value("end_time"),
        "timezone": timezone,
    }, precision=precision)
    missing = []
    if not start_dt.is_set:
        missing.append("start_date")
    if not end_dt.is_set:
        missing.append("end_date")
    if missing:
        raise ValueError("运行时间范围缺失: " + ", ".join(missing))
    return start_dt, end_dt


def resolve_run_datetimes(
    local_settings: dict[str, Any],
    resolved_settings: dict[str, dict[str, Any]],
):
    del resolved_settings
    return runtime_datetimes({"local_settings": local_settings})


def group_product_path_selection_id(group: dict[str, Any]) -> str:
    selection = group.get("product_path_selection")
    if isinstance(selection, dict):
        selection_id = str(
            selection.get("product_path_selection_id")
            or selection.get("selection_id")
            or selection.get("id")
            or ""
        )
        if selection_id:
            return selection_id
    return str(group.get("product_path_selection_id") or "")


def _product_list_from_group_payload(group: dict) -> list[str] | None:
    raw = group.get("productMask")
    if raw is None:
        raw = group.get("productList")
    if isinstance(raw, dict):
        selected = [str(name) for name, enabled in raw.items() if enabled]
        return selected or None
    if isinstance(raw, list):
        selected = [str(name) for name in raw if name]
        return selected or None
    return None


def _strip_implicit_auto_ledger_defaults(
    settings: dict[str, Any],
    *,
    local_settings: dict[str, Any],
    group_payload: dict[str, Any],
) -> None:
    engine_mode = str(settings.get("engine_mode") or "auto").lower()
    if engine_mode not in {"auto", "exact"}:
        return
    for key, default in _AUTO_INFERRED_LEDGER_DEFAULTS.items():
        if key in local_settings or key in group_payload:
            continue
        if settings.get(key) == default:
            settings.pop(key, None)


def _factor_refs_from_group(group: dict[str, Any]) -> list[str]:
    raw = group.get("factor_candidate_refs")
    if not isinstance(raw, list):
        raise ValueError("factor_candidate_refs must be an array")
    return list(dict.fromkeys(
        str(value).strip() for value in raw if str(value or "").strip()
    ))


def _factor_combination_mode(group: dict[str, Any]) -> str:
    return str(
        group.get("factor_combination_mode")
        or group.get("factorCombinationMode")
        or ""
    ).strip()


def resolve_group_strategy_settings(
    group: dict,
    *,
    resolved_backtest_settings: dict[str, dict[str, Any]],
    fallback_group_settings: dict[str, Any],
    page_uuid: str,
    data: dict,
    page_factors_dict: dict,
    selection_cache: dict[str, Any],
    username: str = "",
) -> dict[str, Any]:
    """Resolve one quantile strategy from a frozen group payload."""
    from server.modules.shared.factor_tester_runtime import (
        selection_for_product_path_selection,
    )

    group_id = str(group.get("id") or "")
    group_settings = dict(
        resolved_backtest_settings.get(group_id) or fallback_group_settings
    )
    local_settings = payload_local_settings(data)
    _strip_implicit_auto_ledger_defaults(
        group_settings,
        local_settings=local_settings,
        group_payload=group,
    )

    raw_split_count = group.get("splitCount")
    if raw_split_count is None:
        raise ValueError(f"缺少 splitCount: group={group.get('name') or group_id}")
    group_settings["split_count"] = int(raw_split_count)
    group_settings["group_index"] = int(group.get("groupIndex", 1)) - 1
    group_settings["display_name"] = str(
        group.get("name") or group_id
    )

    selection_id = group_product_path_selection_id(group)
    if not selection_id:
        raise ValueError(
            f"缺少 product_path_selection: group={group.get('name') or group_id}"
        )
    selection = selection_cache.get(selection_id)
    if selection is None:
        selection = selection_for_product_path_selection(
            data, selection_id, page_uuid=page_uuid
        )
        selection_cache[selection_id] = selection
    group_settings["product_path_selection"] = selection
    product_list = _product_list_from_group_payload(group)
    if product_list:
        group_settings["product_mask_names"] = tuple(product_list)

    factor_refs = _factor_refs_from_group(group)
    factor_combination_mode = _factor_combination_mode(group)
    if not factor_refs:
        raise ValueError(
            f"缺少因子候选: group={group.get('name') or group_id}"
        )
    if len(factor_refs) > 1 and not factor_combination_mode:
        raise ValueError(
            f"多个因子候选需要组合方式: group={group.get('name') or group_id}"
        )
    group_settings["factor_refs"] = tuple(factor_refs)
    group_settings["factor_combination_mode"] = factor_combination_mode
    group_settings["factor"] = resolve_factor_ref(
        factor_refs[0],
        data=data,
        page_factors=page_factors_dict,
        page_uuid=page_uuid,
        username=username,
    )
    raw_role_bindings = group.get("factorRoleBindings")
    if raw_role_bindings is None:
        raw_role_bindings = group.get(
            "factor_role_bindings", group_settings.get("factor_role_bindings")
        )
    group_settings["factor_role_bindings"] = resolve_factor_role_bindings(
        raw_role_bindings,
        data=data,
        page_factors=page_factors_dict,
        page_uuid=page_uuid,
        username=username,
    )
    return group_settings


def _resolve_long_short_leg_ids(
    config: dict[str, Any],
    key: str,
    legacy_key: str,
) -> list[dict[str, Any]]:
    raw = config.get(key)
    if not raw and config.get(legacy_key):
        raw = [{"group_id": config.get(legacy_key), "weight": 1.0}]
    snake_key = {
        "longGroupId": "long_group_id",
        "shortGroupId": "short_group_id",
    }.get(legacy_key)
    if not raw and snake_key and config.get(snake_key):
        raw = [{"group_id": config.get(snake_key), "weight": 1.0}]
    if not isinstance(raw, list):
        return []
    result: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, dict):
            group_id = str(
                item.get("group_id")
                or item.get("strategy_id")
                or item.get("id")
                or ""
            )
            weight = item.get("weight", 1.0)
        else:
            group_id = str(item or "")
            weight = 1.0
        if group_id:
            result.append({
                "strategy_id": group_id,
                "group_id": group_id,
                "weight": weight,
            })
    return result


def resolve_long_short_strategy_settings(
    config: dict[str, Any],
    *,
    resolved_backtest_settings: dict[str, dict[str, Any]],
    source_settings_by_alias: dict[str, dict[str, Any]],
    fallback_group_settings: dict[str, Any],
    local_settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a peer long-short strategy from source strategy ids."""
    del resolved_backtest_settings
    strategy_id = str(config.get("strategy_id") or config.get("id") or "")
    long_legs = _resolve_long_short_leg_ids(config, "long", "longGroupId")
    short_legs = _resolve_long_short_leg_ids(config, "short", "shortGroupId")
    if not strategy_id:
        raise ValueError("Long-Short 缺少 id")
    if not long_legs or not short_legs:
        raise ValueError(f"Long-Short {strategy_id} 缺少 long/short legs")

    source_ids = [leg["strategy_id"] for leg in long_legs + short_legs]
    first_source = next(
        (
            source_settings_by_alias[source_id]
            for source_id in source_ids
            if source_id in source_settings_by_alias
        ),
        None,
    )
    if first_source is None:
        raise ValueError(
            f"Long-Short {strategy_id} 引用的源策略不存在: {source_ids}"
        )

    settings = dict(fallback_group_settings)
    settings.update(first_source)
    settings.update({
        key: value
        for key, value in config.items()
        if value not in (None, "")
        and key not in {
            "id", "strategy_id", "name", "long", "short",
            "longGroupId", "shortGroupId", "long_group_id", "short_group_id",
        }
    })
    settings["strategy_intent_mode"] = "long_short"
    settings["strategy_kind"] = "long_short"
    settings["strategy_id"] = strategy_id
    settings["display_name"] = str(
        config.get("name") or strategy_id
    )
    settings["long_leg_strategy_ids"] = long_legs
    settings["short_leg_strategy_ids"] = short_legs
    product_list = _product_list_from_group_payload(config)
    if product_list:
        settings["product_mask_names"] = tuple(product_list)
    _strip_implicit_auto_ledger_defaults(
        settings,
        local_settings=local_settings or {},
        group_payload=config,
    )
    return settings


def build_group_owner_rows(
    groups: list[dict],
    *,
    is_ls: bool,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, group in enumerate(groups):
        if not isinstance(group, dict):
            continue
        strategy_id = str(group.get("id") or f"group-{index}")
        display_name = str(group.get("name") or f"G{index}")
        rows.append({
            "strategy_id": strategy_id,
            "display_name": display_name,
            "group_id": strategy_id,
            "group_name": display_name,
            "group_index": int(group.get("groupIndex", 1)) - 1,
            "product_path_selection_id": group_product_path_selection_id(group),
            "factor_ref": str((group.get("factor_candidate_refs") or [""])[0]),
            "is_ls": is_ls,
        })
    return rows


def build_long_short_owner_rows(
    ls_configs: list[dict],
    *,
    source_owner_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, config in enumerate(ls_configs):
        if not isinstance(config, dict):
            continue
        group_id = long_short_strategy_id(config, index)
        long_legs = _resolve_long_short_leg_ids(config, "long", "longGroupId")
        short_legs = _resolve_long_short_leg_ids(config, "short", "shortGroupId")
        first_source: dict[str, Any] = next(
            (
                source_owner_by_id.get(leg["strategy_id"])
                for leg in long_legs + short_legs
                if source_owner_by_id.get(leg["strategy_id"]) is not None
            ),
            {},
        ) or {}
        display_name = str(config.get("name") or group_id)
        rows.append({
            "strategy_id": group_id,
            "display_name": display_name,
            "group_id": group_id,
            "group_name": display_name,
            "group_index": -1,
            "product_path_selection_id": str(
                first_source.get("product_path_selection_id") or ""
            ),
            "factor_alias": str(first_source.get("factor_alias") or ""),
            "is_ls": True,
        })
    return rows


def long_short_strategy_id(config: dict[str, Any], index: int) -> str:
    strategy_id = str(
        config.get("strategy_id") or config.get("id") or ""
    ).strip()
    return strategy_id or f"ls-{index}"
