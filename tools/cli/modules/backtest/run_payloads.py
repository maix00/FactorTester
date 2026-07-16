"""HTTP run-payload serialization helpers for the backtest CLI."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


StrategyBookPayload = Callable[[Any], dict[str, Any]]


def run_payload(
    state: Any,
    *,
    groups: list[dict[str, Any]],
    strategy_book_payload: StrategyBookPayload,
) -> dict[str, Any]:
    payload = {
        "page_uuid": state.page_uuid,
        "local_settings": dict(state.backtest_local_settings),
        "groups": [serialize_group_for_run(group) for group in groups],
        "ls_configs": [
            serialize_ls_config_for_run(config, index=index)
            for index, config in enumerate(state.backtest_ls_configs)
        ],
    }
    if state.backtest_strategy_book:
        payload["strategy_book"] = serialize_strategy_book_for_run(
            strategy_book_payload(state),
            groups,
        )
    if state.backtest_ledger_configs:
        payload["ledger_configs"] = {
            str(ledger): dict(config)
            for ledger, config in state.backtest_ledger_configs.items()
        }
    return payload


def serialize_strategy_book_for_run(payload: dict[str, Any], groups: list[dict[str, Any]]) -> dict[str, Any]:
    strategy_ids: dict[str, str] = {}
    for group in groups:
        strategy_id = str(group.get("id") or "")
        if not strategy_id:
            continue
        for candidate in (group.get("shortAlias"), group.get("name"), strategy_id):
            alias = str(candidate or "")
            if alias:
                strategy_ids[alias] = strategy_id
    strategies = payload.get("strategies")
    if isinstance(strategies, dict):
        payload["strategies"] = {
            strategy_ids.get(str(alias), str(alias)): value
            for alias, value in strategies.items()
        }
    return payload


def serialize_group_for_run(group: dict[str, Any]) -> dict[str, Any]:
    """Translate the CLI's registered field names at the HTTP boundary."""
    payload = dict(group)
    if "split_count" in group:
        payload["splitCount"] = group["split_count"]
    if "group_index" in group:
        payload["groupIndex"] = group["group_index"]
    if "factor" in group:
        payload["factorAlias"] = group["factor"]
    return payload


def serialize_ls_config_for_run(config: dict[str, Any], *, index: int = 0) -> dict[str, Any]:
    """Translate CLI display-oriented long-short refs to server leg refs."""
    payload = dict(config)
    strategy_id = str(payload.get("strategy_id") or payload.get("id") or f"ls-{index}")
    payload.setdefault("id", strategy_id)
    payload.setdefault("strategy_id", strategy_id)
    long_id = _leg_group_id(payload, "long")
    short_id = _leg_group_id(payload, "short")
    if long_id:
        payload.setdefault("longGroupId", long_id)
        payload.setdefault("long_group_id", long_id)
        payload.setdefault("long", [{"group_id": long_id, "strategy_id": long_id, "weight": 1.0}])
    if short_id:
        payload.setdefault("shortGroupId", short_id)
        payload.setdefault("short_group_id", short_id)
        payload.setdefault("short", [{"group_id": short_id, "strategy_id": short_id, "weight": 1.0}])
    return payload


def _leg_group_id(config: dict[str, Any], side: str) -> str:
    group = config.get(f"{side}_group")
    if isinstance(group, dict):
        value = group.get("id") or group.get("group_id") or group.get("strategy_id")
        if value:
            return str(value)
    camel = "longGroupId" if side == "long" else "shortGroupId"
    snake = f"{side}_group_id"
    value = config.get(camel) or config.get(snake)
    if value:
        return str(value)
    legs = config.get(side)
    if isinstance(legs, list) and legs:
        first = legs[0]
        if isinstance(first, dict):
            value = first.get("group_id") or first.get("strategy_id") or first.get("id")
            return str(value or "")
        return str(first or "")
    return ""
