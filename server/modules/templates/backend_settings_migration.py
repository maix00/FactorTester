"""Migrate saved template snapshots to flat backend-registered group fields."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from tools.testers.settings import backtest_setting_registry


STRUCTURAL_GROUP_KEYS = {
    "id", "name", "parentId", "testerId", "factorAlias", "factorAliases",
    "factor_combination_mode", "factorCombinationMode", "splitCount", "groupIndex",
    "isAllGroups", "addBatch", "needsRegenerate", "startDate", "endDate",
    "overrides", "_expanded", "productMask", "product_names", "productNames", "batchId",
    "product_path_selection", "product_path_selection_id",
}
STRUCTURAL_LS_KEYS = {
    "id", "name", "batchId", "longGroupId", "shortGroupId", "needsRegenerate", "metadata",
}
LEGACY_LOCAL_KEYS = {"dates", "initialCapital", "calendarFreq", "backendBacktestSettings"}
LEGACY_GROUP_KEYS = {
    "feeMode", "feeRate", "feeMap", "feeSensitivity", "useCloseToday",
    "rebalanceMode", "liquidityMode", "liquidityPercent", "marginMode",
}


def migrate_snapshot_backend_settings(
    snapshot: dict[str, Any],
    product_groups: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], bool]:
    """Return a snapshot whose backtest settings live on flat group/strategy rows."""
    if not isinstance(snapshot, dict):
        return snapshot, False
    migrated = deepcopy(snapshot)
    before = deepcopy(migrated)

    defaults = _defaults()
    product_path_selections = _migrate_product_path_selections(migrated, product_groups or [])
    local_defaults = _extract_local_values(migrated)
    backend_group_values = _extract_backend_group_values(migrated)
    group_settings = migrated.get("group_settings")
    if isinstance(group_settings, dict):
        _attach_product_path_selections_to_groups(group_settings, product_path_selections)
        _inherit_group_product_path_selections(group_settings.get("groups"))
        _normalize_product_path_selection_fields(group_settings.get("groups"), product_groups or [])
        _normalize_product_path_selection_fields(group_settings.get("lsConfigs"), product_groups or [])
        _remove_legacy_group_tester_ids(group_settings.get("groups"))
        _migrate_items(group_settings.get("groups"), backend_group_values, defaults, STRUCTURAL_GROUP_KEYS)
        _migrate_items(group_settings.get("lsConfigs"), backend_group_values, defaults, STRUCTURAL_LS_KEYS)

    migrated.pop("time_data", None)
    migrated.pop("backendBacktestSettings", None)
    execution = migrated.get("execution")
    execution = deepcopy(execution) if isinstance(execution, dict) else {}
    execution_settings = execution.get("settings")
    if not isinstance(execution_settings, dict):
        execution_settings = deepcopy(migrated.get("local_settings") or {})
    for key in list(execution_settings.keys()):
        if key in LEGACY_LOCAL_KEYS or key == "backendBacktestSettings":
            execution_settings.pop(key, None)
    for key, value in local_defaults.items():
        if defaults.get(key) != value:
            execution_settings[key] = value
        else:
            execution_settings.pop(key, None)
    _normalize_product_path_selection(
        execution_settings.get("product_path_selection"), product_groups or [],
    )
    migrated.pop("local_settings", None)
    migrated.pop("settings", None)
    execution["settings"] = execution_settings
    migrated["execution"] = execution

    return migrated, migrated != before


def _migrate_product_path_selections(snapshot: dict[str, Any], product_groups: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    raw_items = snapshot.get("submissions") or []
    selections: dict[str, dict[str, Any]] = {}
    seen: set[str] = set()
    for index, item in enumerate(raw_items if isinstance(raw_items, list) else []):
        if not isinstance(item, dict):
            continue
        original_selection_id = str(
            item.get("product_path_selection_id")
            or item.get("selection_id")
            or item.get("id")
            or f"product-path-selection-{index + 1}"
        )
        paths = list(item.get("selected_paths") or item.get("paths") or [])
        paths = _canonical_paths(paths)
        matched_group = _match_product_group(paths, item, product_groups)
        product_group = str((matched_group or {}).get("name") or item.get("product_group") or "")
        template_id = str(
            item.get("product_group_template_id")
            or item.get("template_id")
            or (matched_group or {}).get("id")
            or ""
        )
        selection_id = template_id or original_selection_id
        if selection_id in seen:
            if original_selection_id and original_selection_id not in selections and selection_id in selections:
                selections[original_selection_id] = selections[selection_id]
            continue
        seen.add(selection_id)
        source_type = str(
            item.get("source_type")
            or ("user_product_group_template" if template_id else "manual_selection")
        )
        selection: dict[str, Any] = {
            "product_path_selection_id": selection_id,
        }
        if not template_id and paths:
            selection["paths"] = list(paths)
        selections[selection_id] = selection
        if original_selection_id and original_selection_id != selection_id:
            selections[original_selection_id] = selection
    snapshot.pop("submissions", None)
    snapshot.pop("product_path_selections", None)
    return selections


def _attach_product_path_selections_to_groups(
    group_settings: dict[str, Any],
    selections_by_id: dict[str, dict[str, Any]],
) -> None:
    if not selections_by_id:
        return
    groups = group_settings.get("groups")
    if not isinstance(groups, list):
        return
    for group in groups:
        if not isinstance(group, dict):
            continue
        selection_id = str(group.get("product_path_selection_id") or group.get("testerId") or "")
        selection = selections_by_id.get(selection_id)
        if selection is not None:
            group["product_path_selection"] = selection


def _normalize_product_path_selection_fields(items: Any, product_groups: list[dict[str, Any]]) -> None:
    if not isinstance(items, list):
        return
    for item in items:
        if isinstance(item, dict):
            _normalize_product_path_selection(item.get("product_path_selection"), product_groups)


def _inherit_group_product_path_selections(groups: Any) -> None:
    if not isinstance(groups, list):
        return
    groups_by_id = {
        str(group.get("id")): group
        for group in groups
        if isinstance(group, dict) and group.get("id")
    }
    for group in groups:
        if not isinstance(group, dict):
            continue
        if isinstance(group.get("product_path_selection"), dict):
            continue
        parent = groups_by_id.get(str(group.get("parentId") or ""))
        parent_selection = parent.get("product_path_selection") if isinstance(parent, dict) else None
        if isinstance(parent_selection, dict):
            group["product_path_selection"] = deepcopy(parent_selection)


def _normalize_product_path_selection(selection: Any, product_groups: list[dict[str, Any]] | None = None) -> None:
    if not isinstance(selection, dict):
        return
    selection_id = str(
        selection.get("product_path_selection_id")
        or selection.get("selection_id")
        or selection.get("id")
        or selection.get("product_group_template_id")
        or selection.get("path_id")
        or selection.get("template_id")
        or ""
    ).strip()
    template_id = str(
        selection.get("product_group_template_id")
        or selection.get("path_id")
        or selection.get("template_id")
        or ""
    ).strip()
    is_product_group_ref = bool(template_id)
    if template_id:
        selection_id = template_id
    normalized_paths: list[str] = []
    paths = selection.get("paths") or selection.get("selected_paths")
    if isinstance(paths, list):
        normalized_paths = _canonical_paths(paths)
        matched_group = _match_product_group(normalized_paths, selection, product_groups or [])
        if matched_group:
            template_id = str(matched_group.get("id") or "").strip()
            if template_id:
                selection_id = template_id
                is_product_group_ref = True
    if selection_id:
        selection.clear()
        selection["product_path_selection_id"] = selection_id
        if normalized_paths and not is_product_group_ref:
            selection["paths"] = list(normalized_paths)


def _remove_legacy_group_tester_ids(groups: Any) -> None:
    if not isinstance(groups, list):
        return
    for group in groups:
        if isinstance(group, dict):
            group.pop("testerId", None)


def _canonical_paths(paths: Any) -> list[str]:
    return sorted({str(path) for path in (paths or []) if str(path).strip()})


def _match_product_group(paths: list[str], item: dict[str, Any], product_groups: list[dict[str, Any]]) -> dict[str, Any] | None:
    template_id = str(item.get("product_group_template_id") or item.get("template_id") or "").strip()
    if template_id:
        for group in product_groups:
            if str(group.get("id") or "") == template_id:
                return group
    wanted = set(paths)
    for group in product_groups:
        if set(_canonical_paths(group.get("paths") or [])) == wanted:
            return group
    name = str(item.get("product_group") or "").strip()
    if name:
        for group in product_groups:
            if str(group.get("name") or "") == name:
                return group
    return None


def _defaults() -> dict[str, Any]:
    manifest = backtest_setting_registry.get("group_test").manifest()
    return {
        key: value.get("value")
        for key, value in (manifest.get("defaults") or {}).items()
        if isinstance(value, dict)
    }


def _extract_local_values(snapshot: dict[str, Any]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    time_data = snapshot.get("time_data")
    local_settings = snapshot.get("local_settings") if isinstance(snapshot.get("local_settings"), dict) else {}
    backend = local_settings.get("backendBacktestSettings") if isinstance(local_settings, dict) else None
    if isinstance(backend, dict) and isinstance(backend.get("local_values"), dict):
        values.update(backend["local_values"])
    defaults = _defaults()
    if isinstance(local_settings, dict):
        for key in defaults:
            if key in local_settings:
                values[key] = local_settings[key]

    source = time_data if isinstance(time_data, dict) else None
    dates = local_settings.get("dates") if isinstance(local_settings, dict) else None
    if source is None and isinstance(dates, dict):
        source = {
            "start_date": dates.get("startDate") or dates.get("startDt"),
            "end_date": dates.get("endDate") or dates.get("endDt"),
            "start_time": _legacy_time(dates.get("startHour"), dates.get("startMinute")),
            "end_time": _legacy_time(dates.get("endHour"), dates.get("endMinute")),
            "timezone": dates.get("tz"),
            "time_precision": dates.get("precision"),
        }
    if isinstance(source, dict):
        _set(values, "start_date", source.get("start_date") or source.get("start"))
        _set(values, "end_date", source.get("end_date") or source.get("end"))
        _set(values, "start_time", source.get("start_time") or "09:00")
        _set(values, "end_time", source.get("end_time") or "15:00")
        _set(values, "timezone", source.get("timezone") or "Asia/Shanghai")
        _set(values, "time_precision", source.get("time_precision") or "exact")

    capital = local_settings.get("initialCapital") if isinstance(local_settings, dict) else None
    if isinstance(capital, dict):
        _set(values, "initial_capital", capital.get("initialCapital"))
    calendar = local_settings.get("calendarFreq") if isinstance(local_settings, dict) else None
    if isinstance(calendar, dict):
        _set(values, "calendar_frequency", calendar.get("groupCalendarFreq") if calendar.get("autoGroupCalendarFreq") is False else "auto")
    return values


def _extract_backend_group_values(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    local_settings = snapshot.get("local_settings") if isinstance(snapshot.get("local_settings"), dict) else {}
    backend = local_settings.get("backendBacktestSettings") if isinstance(local_settings, dict) else None
    group_values = backend.get("group_values") if isinstance(backend, dict) else None
    return group_values if isinstance(group_values, dict) else {}


def _migrate_items(items: Any, backend_group_values: dict[str, dict[str, Any]], defaults: dict[str, Any], structural_keys: set[str]) -> None:
    if not isinstance(items, list):
        return
    backend = None
    for item in items:
        if not isinstance(item, dict):
            continue
        _normalize_strategy_identity(item)
        if "splitCount" in structural_keys and "splitCount" not in item and "groupCount" in item:
            item["splitCount"] = int(item["groupCount"])
            item["groupIndex"] = int(item.get("groupIndex") or 0) + 1
        backend = _legacy_group_values(item)
        existing_backend = backend_group_values.get(str(item.get("id") or ""))
        if isinstance(existing_backend, dict):
            backend.update(existing_backend)
        if "rebalance_mode" in item:
            backend.update(_split_legacy_rebalance_mode(item.get("rebalance_mode")))
        if "rebalance_mode" in backend:
            backend.update(_split_legacy_rebalance_mode(backend.get("rebalance_mode")))
        backend.pop("rebalance_mode", None)
        if item.get("rebalance_trigger") == "buy_and_hold" or backend.get("rebalance_trigger") == "buy_and_hold":
            backend["rebalance_trigger"] = "on_factor_signal"
            backend["position_policy"] = "buy_and_hold"
        item.update(backend)
        # The template snapshot is a backend contract, not a copy of the
        # browser's view model.  Keep registered settings and structural
        # fields only; unknown display metadata is discarded here.  This
        # makes old aliases disappear without keeping their names in the
        # runtime schema or serializer.
        contract_keys = structural_keys | set(defaults) | set(backend)
        for key in list(item.keys()):
            if key == "rebalance_mode":
                item.pop(key, None)
                continue
            if key in LEGACY_GROUP_KEYS:
                item.pop(key, None)
                continue
            if key not in contract_keys:
                item.pop(key, None)
                continue
            if key in structural_keys:
                continue
            if key in defaults and item.get(key) == defaults[key]:
                item.pop(key, None)


def _normalize_strategy_identity(item: dict[str, Any]) -> None:
    """Collapse historical strategy identity spellings before whitelisting."""
    if not str(item.get("id") or "").strip():
        for key in ("strategy_id", "group_id"):
            value = str(item.get(key) or "").strip()
            if value:
                item["id"] = value
                break
    if not str(item.get("name") or "").strip():
        for key in ("display_name", "group_name", "key"):
            value = str(item.get(key) or "").strip()
            if value:
                item["name"] = value
                break
    for key in ("strategy_id", "group_id", "display_name", "group_name", "key"):
        item.pop(key, None)


def _legacy_group_values(item: dict[str, Any]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    if "feeMode" in item:
        mode = str(item.get("feeMode") or "none")
        if mode == "none":
            values["fee_mode"] = "zero"
        elif mode == "per_product" and not item.get("feeMap") and item.get("feeRate") in (None, ""):
            values["fee_mode"] = "auto"
        else:
            if item.get("feeMap"):
                values["fee_mode"] = "custom"
                values["custom_fee_overrides"] = item.get("feeMap")
            else:
                values["fee_mode"] = "fixed"
                _set(values, "fixed_fee_rate", item.get("feeRate"))
    if "rebalanceMode" in item:
        mapping = {
            "each_period": "on_factor_signal",
            "on_factor_signal": "on_factor_signal",
            "buy_and_hold": "buy_and_hold",
            "membership_change": "membership_change",
            "daily": "scheduled",
            "scheduled": "scheduled",
        }
        values.update(_split_legacy_rebalance_mode(mapping.get(str(item.get("rebalanceMode") or ""), "on_factor_signal")))
    if "liquidityMode" in item or "liquidityPercent" in item:
        mode = str(item.get("liquidityMode") or "")
        if mode in {"percent", "volume_participation"}:
            values["liquidity_mode"] = "volume_participation"
            try:
                percent = float(item.get("liquidityPercent") or 0.0)
                values["participation_rate"] = percent / 100.0 if percent > 1 else percent
            except Exception:
                pass
        else:
            values["liquidity_mode"] = "infinite"
    return values


def _split_legacy_rebalance_mode(raw: Any) -> dict[str, str]:
    value = str(raw or "on_factor_signal")
    if value == "buy_and_hold":
        return {
            "rebalance_trigger": "on_factor_signal",
            "position_policy": "buy_and_hold",
        }
    return {
        "rebalance_trigger": value,
        "position_policy": "rebalance_to_target",
    }


def _set(values: dict[str, Any], key: str, value: Any) -> None:
    if value is None:
        return
    if isinstance(value, str) and value == "":
        return
    values[key] = value


def _legacy_time(hour: Any, minute: Any) -> str | None:
    if hour is None or minute is None:
        return None
    try:
        return f"{int(hour):02d}:{int(minute):02d}"
    except Exception:
        return None
