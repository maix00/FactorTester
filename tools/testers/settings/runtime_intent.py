"""Canonicalize settings whose value is chosen by the runtime.

The authoring registry deliberately exposes ``auto`` for settings that are
resolved later from the engine, ledger, market rules, or data coverage.  Old
configuration rows can still contain the former display defaults (for
example ``false`` for daily mark-to-market).  Those values are ignored by the
registry when they are not editable in the selected mode, so retaining them in
the frozen RunSpec makes the RunSpec disagree with the actual run.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from . import backtest_setting_registry
from .resolver import resolve_group_settings


_NORMALIZABLE_REASONS = frozenset({
    "invalid_setting_value",
    "local_only_group_value_ignored",
    "non_editable_value_ignored",
})


def normalize_backtest_runtime_setting_intent(
    payload: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Return a payload whose frozen runtime intent matches registry rules.

    Only explicitly supplied values that the registered resolver would ignore
    are changed.  Editable custom values and ordinary business defaults are
    left untouched.  The same resolver is used for the diagnostic pass and
    for execution, so this function does not duplicate runtime policy.
    """
    normalized = deepcopy(payload)
    analyses = normalized.get("analyses")
    if not isinstance(analyses, dict):
        return normalized, []
    backtest = analyses.get("backtest")
    if not isinstance(backtest, dict):
        return normalized, []
    local = backtest.get("local_settings")
    if not isinstance(local, dict):
        return normalized, []

    groups = [
        item for item in (backtest.get("groups") or [])
        if isinstance(item, dict)
    ]
    long_short = [
        item for item in (backtest.get("ls_configs") or [])
        if isinstance(item, dict)
    ]
    all_items = [*groups, *long_short]
    group_ids = [
        str(item.get("id") or f"group-{index}")
        for index, item in enumerate(all_items)
    ]
    if not group_ids:
        return normalized, []

    application = backtest_setting_registry.get("group_test")
    setting_keys = set(application.settings)
    local_values = {
        key: value for key, value in local.items() if key in setting_keys
    }
    group_values = {
        group_id: {
            key: value
            for key, value in item.items()
            if key in setting_keys
        }
        for group_id, item in zip(group_ids, all_items)
    }
    resolved = resolve_group_settings(
        application,
        local_values=local_values,
        group_values=group_values,
        group_ids=group_ids,
    )

    changes: list[dict[str, Any]] = []
    _normalize_local_values(
        local,
        application,
        resolved,
        changes,
    )
    _normalize_group_values(
        all_items,
        group_ids,
        application,
        resolved,
        changes,
    )
    return normalized, changes


def _fallbacks_for(resolved: dict[str, Any], key: str) -> list[dict[str, Any]]:
    return [
        item for item in (resolved.get("_setting_fallbacks") or [])
        if isinstance(item, dict)
        and str(item.get("setting_key") or "") == key
        and str(item.get("reason") or "") in _NORMALIZABLE_REASONS
    ]


def _normalize_local_values(
    local: dict[str, Any],
    application: Any,
    resolved: dict[str, dict[str, Any]],
    changes: list[dict[str, Any]],
) -> None:
    for key, old_value in list(local.items()):
        if key not in application.settings:
            continue
        fallbacks = [
            item for values in resolved.values()
            for item in _fallbacks_for(values, key)
            if item.get("requested_value") == old_value
        ]
        if not fallbacks:
            continue
        new_value = application.settings[key].default
        if old_value == new_value:
            continue
        local[key] = new_value
        changes.append({
            "scope": "local_settings",
            "setting_key": key,
            "requested_value": old_value,
            "applied_value": new_value,
            "reason": "neutral_runtime_intent",
        })


def _normalize_group_values(
    items: list[dict[str, Any]],
    group_ids: list[str],
    application: Any,
    resolved: dict[str, dict[str, Any]],
    changes: list[dict[str, Any]],
) -> None:
    for item, group_id in zip(items, group_ids):
        values = resolved.get(group_id) or {}
        for key, old_value in list(item.items()):
            if key not in application.settings:
                continue
            fallbacks = [
                fallback for fallback in _fallbacks_for(values, key)
                if fallback.get("requested_value") == old_value
            ]
            if not fallbacks:
                continue
            setting = application.settings[key]
            if setting.scope_policy.value == "local_only":
                del item[key]
                new_value: Any = None
                reason = "remove_ignored_local_only_override"
            else:
                new_value = setting.default
                if old_value == new_value:
                    continue
                item[key] = new_value
                reason = "neutral_runtime_intent"
            changes.append({
                "scope": "group",
                "group_id": group_id,
                "setting_key": key,
                "requested_value": old_value,
                "applied_value": new_value,
                "reason": reason,
            })
