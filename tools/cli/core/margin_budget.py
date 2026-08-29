"""Manifest-compatible workspace margin-budget operations."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


def margin_budget_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    backtest = payload.get("analyses", {}).get("backtest", {})
    local = (backtest.get("execution") or {}).get("settings") or {}
    rows = []
    for group in backtest.get("groups") or []:
        if not isinstance(group, dict):
            continue
        mode = str(_effective(group, local, "margin_mode", "auto"))
        rows.append({
            "group_id": str(group.get("id") or group.get("group_id") or ""),
            "name": str(group.get("name") or group.get("display_name") or ""),
            "margin_mode": mode,
            "enabled": mode.lower() not in {"none", "off", "zero"},
            "allocation_policy": _effective(group, local, "allocation_policy", "equal_notional"),
            "target_margin_utilization": float(_effective(
                group, local, "target_margin_utilization", 0.30,
            )),
            "max_margin_utilization": float(_effective(
                group, local, "max_margin_utilization", 0.40,
            )),
            "margin_utilization_tolerance": float(_effective(
                group, local, "margin_utilization_tolerance", 0.01,
            )),
        })
    return rows


def configure_margin_budget(
    payload: dict[str, Any],
    group_id: str,
    *,
    target: float | None,
    maximum: float | None,
    tolerance: float | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    result = deepcopy(payload)
    backtest = result.setdefault("analyses", {}).setdefault("backtest", {})
    groups = backtest.get("groups") or []
    group = next(
        (item for item in groups if str(item.get("id") or item.get("group_id") or "") == group_id),
        None,
    )
    if group is None:
        raise ValueError(f"unknown strategy group: {group_id}")
    for key, value in (
        ("target_margin_utilization", target),
        ("max_margin_utilization", maximum),
        ("margin_utilization_tolerance", tolerance),
    ):
        if value is not None:
            group[key] = float(value)
    row = next(item for item in margin_budget_rows(result) if item["group_id"] == group_id)
    if not 0 < row["target_margin_utilization"] <= row["max_margin_utilization"] < 1:
        raise ValueError("margin utilization requires 0 < target <= max < 1")
    if row["margin_utilization_tolerance"] < 0:
        raise ValueError("margin utilization tolerance must be non-negative")
    return result, row


def _effective(group: dict[str, Any], local: dict[str, Any], key: str, default: Any) -> Any:
    return group.get(key, local.get(key, default))
