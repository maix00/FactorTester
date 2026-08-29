"""Manifest-driven strategy-intent workspace operations."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


def intent_catalog(manifest: dict[str, Any]) -> dict[str, Any]:
    defaults = manifest.get("defaults") or {}
    role_field = defaults.get("factor_role_bindings") or {}
    serialization = role_field.get("serialization") or {}
    kinds = defaults.get("strategy_intent_mode") or defaults.get("strategy_kind") or {}
    return {
        "application": manifest.get("application") or "group_test",
        "strategy_kinds": [
            {"value": value, "label": label}
            for value, label in _options(kinds.get("options") or [])
        ],
        "allowed_roles": list(serialization.get("allowed_roles") or []),
        "roles_by_strategy_kind": {
            str(kind): list(roles)
            for kind, roles in (serialization.get("roles_by_strategy_kind") or {}).items()
        },
    }


def strategy_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    backtest = _backtest(payload)
    local = (backtest.get("execution") or {}).get("settings") or {}
    rows = []
    for group in backtest.get("groups") or []:
        if not isinstance(group, dict):
            continue
        rows.append({
            "group_id": str(group.get("id") or group.get("group_id") or ""),
            "name": str(group.get("name") or group.get("display_name") or ""),
            "strategy_kind": _effective(group, local, "strategy_intent_mode", "group"),
            "factor_alias": str(group.get("factorAlias") or group.get("factor_alias") or ""),
            "factor_role_bindings": dict(
                group.get("factorRoleBindings") or group.get("factor_role_bindings") or {}
            ),
            "screen_rule": _effective(group, local, "screen_rule", "disabled"),
            "allocation_policy": _effective(group, local, "allocation_policy", "equal_notional"),
        })
    return rows


def configure_strategy(
    payload: dict[str, Any], catalog: dict[str, Any], group_id: str,
    *, bindings: dict[str, str], clear_roles: tuple[str, ...] = (),
    settings: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    result = deepcopy(payload)
    backtest = _backtest(result)
    groups = backtest.get("groups") or []
    group = next((item for item in groups if str(item.get("id") or item.get("group_id") or "") == group_id), None)
    if group is None:
        raise ValueError(f"unknown strategy group: {group_id}")
    local = (backtest.get("execution") or {}).get("settings") or {}
    for key, value in (settings or {}).items():
        if value is not None:
            group[key] = value
    kind = str(_effective(group, local, "strategy_intent_mode", "group"))
    permitted = set((catalog.get("roles_by_strategy_kind") or {}).get(kind) or [])
    current = dict(group.get("factorRoleBindings") or group.get("factor_role_bindings") or {})
    for role in clear_roles:
        current.pop(role, None)
    current.update(bindings)
    unknown = sorted(set(current) - permitted)
    if unknown:
        raise ValueError(f"roles incompatible with strategy kind {kind}: {', '.join(unknown)}")
    # Role-bound factors can be supplied by a Profile worktree only when a
    # Run is previewed/submitted.  They must not be registered in the shared
    # workspace library merely to make an isolated strategy configuration
    # editable.  Keep the durable configuration source-free here and defer
    # executable-source validation to the Run boundary, where the transient
    # source bundle is actually available.
    #
    # Primary-factor registration remains owned by workspace creation and
    # configuration validation.  This exception is deliberately limited to
    # role bindings, whose aliases are the explicit extension point for
    # run-scoped screens, sizing, entry, and exit policies.
    if "screen" in current and _effective(group, local, "screen_rule", "disabled") == "disabled":
        raise ValueError("screen role requires --screen-rule gte|lte|between")
    if "sizing" in current and _effective(group, local, "allocation_policy", "equal_notional") != "factor_sizing":
        raise ValueError("sizing role requires --allocation-policy factor_sizing")
    group.pop("factor_role_bindings", None)
    group["factorRoleBindings"] = current
    return result, next(row for row in strategy_rows(result) if row["group_id"] == group_id)


def parse_bindings(values: tuple[str, ...]) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for raw in values:
        if "=" not in raw:
            raise ValueError("--role must use ROLE=FACTOR_ALIAS")
        role, alias = (part.strip() for part in raw.split("=", 1))
        if not role or not alias:
            raise ValueError("--role must use non-empty ROLE=FACTOR_ALIAS")
        parsed[role] = alias
    return parsed


def _backtest(payload: dict[str, Any]) -> dict[str, Any]:
    return payload.setdefault("analyses", {}).setdefault("backtest", {})


def _effective(group: dict[str, Any], local: dict[str, Any], key: str, default: Any) -> Any:
    return group.get(key, local.get(key, default))


def _options(options: list[Any]) -> list[tuple[Any, Any]]:
    return [
        (item.get("value"), item.get("label")) if isinstance(item, dict) else tuple(item[:2])
        for item in options
    ]
