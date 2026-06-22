"""Migrate saved template snapshots to flat backend-registered group fields."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from tools.backtest.settings import backtest_setting_registry


STRUCTURAL_GROUP_KEYS = {
    "id", "name", "parentId", "testerId", "factorAlias", "splitCount", "groupIndex",
    "isAllGroups", "addBatch", "needsRegenerate", "startDate", "endDate", "shortAlias",
    "overrides", "_expanded", "productMask", "product_names", "productNames",
}
STRUCTURAL_LS_KEYS = {"id", "name", "shortAlias", "longGroupId", "shortGroupId", "needsRegenerate", "metadata"}
LEGACY_LOCAL_KEYS = {"dates", "initialCapital", "calendarFreq", "backendBacktestSettings"}
LEGACY_GROUP_KEYS = {
    "feeMode", "feeRate", "feeMap", "feeSensitivity", "useCloseToday",
    "rebalanceMode", "liquidityMode", "liquidityPercent", "marginMode",
}


def migrate_snapshot_backend_settings(snapshot: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Return a snapshot whose backtest settings live on flat group/strategy rows."""
    if not isinstance(snapshot, dict):
        return snapshot, False
    migrated = deepcopy(snapshot)
    before = deepcopy(migrated)

    defaults = _defaults()
    local_defaults = _extract_local_values(migrated)
    backend_group_values = _extract_backend_group_values(migrated)
    group_settings = migrated.get("group_settings")
    if isinstance(group_settings, dict):
        _migrate_items(group_settings.get("groups"), backend_group_values, defaults, STRUCTURAL_GROUP_KEYS)
        _migrate_items(group_settings.get("lsConfigs"), backend_group_values, defaults, STRUCTURAL_LS_KEYS)

    migrated.pop("time_data", None)
    migrated.pop("backendBacktestSettings", None)
    local_settings = migrated.get("local_settings")
    if not isinstance(local_settings, dict):
        local_settings = {}
    for key in list(local_settings.keys()):
        if key in LEGACY_LOCAL_KEYS or key == "backendBacktestSettings":
            local_settings.pop(key, None)
    for key, value in local_defaults.items():
        if defaults.get(key) != value:
            local_settings[key] = value
        else:
            local_settings.pop(key, None)
    if local_settings:
        migrated["local_settings"] = local_settings
    else:
        migrated.pop("local_settings", None)

    return migrated, migrated != before


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
        for key in list(item.keys()):
            if key == "rebalance_mode":
                item.pop(key, None)
                continue
            if key in LEGACY_GROUP_KEYS:
                item.pop(key, None)
                continue
            if key in structural_keys:
                continue
            if key in defaults and item.get(key) == defaults[key]:
                item.pop(key, None)


def _legacy_group_values(item: dict[str, Any]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    if "feeMode" in item:
        mode = str(item.get("feeMode") or "none")
        if mode == "none":
            values["fee_mode"] = "none"
        elif mode == "per_product" and not item.get("feeMap") and item.get("feeRate") in (None, ""):
            values["fee_mode"] = "market"
        else:
            values["fee_mode"] = "custom"
            _set(values, "custom_fee_rate", item.get("feeRate"))
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
                percent = float(item.get("liquidityPercent"))
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
