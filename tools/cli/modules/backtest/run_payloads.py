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
        "ls_configs": list(state.backtest_ls_configs),
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
