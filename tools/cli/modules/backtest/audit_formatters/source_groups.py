"""Grouping helpers for step-audit field values by source scope."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any


DisplayFieldValue = Callable[[str, Any], Any]
DisplayKey = Callable[[Any], str]
Normalize = Callable[[Any], Any]


def join(values: list[Any]) -> str:
    unique = sorted({str(value) for value in values if value not in (None, "")})
    return ", ".join(unique) if unique else "无"


def source_group_label(entries: list[dict[str, Any]], *, shared_group: bool = False) -> str:
    scopes = {str(entry.get("scope") or "") for entry in entries}
    strategies = join([
        strategy
        for entry in entries
        for strategy in (
            entry.get("strategies")
            if isinstance(entry.get("strategies"), list)
            else [entry.get("strategy")]
        )
    ])
    ledgers = join([entry.get("ledger") for entry in entries])
    cash_pools = join([entry.get("cash_pool") for entry in entries])

    if scopes <= {"strategy_config"}:
        if strategies == "无":
            return "[共享]"
        return f"策略配置 {strategies}"
    if scopes <= {"strategy_context"}:
        if strategies == "无":
            return "[共享]"
        return f"策略上下文 {strategies}"
    if scopes <= {"ledger"}:
        if len(entries) > 1:
            return ledger_group_label(entries, prefix="合并")
        return f"账本 {ledgers} | 现金池 {cash_pools} | 策略 {strategies}"
    if scopes <= {"ledger_config"}:
        if len(entries) > 1:
            return ledger_group_label(entries, prefix="合并账本配置")
        return f"账本配置 {ledgers} | 现金池 {cash_pools} | 策略 {strategies}"
    if scopes <= {"context"}:
        return "[共享]"
    if scopes <= {"context", "strategy_context"}:
        if strategies == "无":
            return "[共享]"
        return f"共享上下文 + 策略上下文 {strategies}"
    if scopes <= {"context", "strategy_config"}:
        if strategies == "无":
            return "[共享]"
        return f"共享上下文 + 策略配置 {strategies}"
    return "[合并] " + "；".join(source_label(entry) for entry in entries)


def ledger_group_label(entries: list[dict[str, Any]], *, prefix: str) -> str:
    ledgers = {str(entry.get("ledger") or "") for entry in entries if entry.get("ledger") not in (None, "")}
    cash_pools = {str(entry.get("cash_pool") or "") for entry in entries if entry.get("cash_pool") not in (None, "")}
    strategies = {
        str(strategy)
        for entry in entries
        for strategy in (entry.get("strategies") if isinstance(entry.get("strategies"), list) else [])
        if strategy not in (None, "")
    }
    parts = [f"{prefix} {len(ledgers)} 个账本"]
    if cash_pools:
        parts.append(f"{len(cash_pools)} 个现金池")
    if strategies:
        parts.append(f"{len(strategies)} 个策略")
    return " / ".join(parts)


def source_route_rows(entries: list[dict[str, Any]]) -> list[tuple[str, str, str]]:
    scopes = {str(entry.get("scope") or "") for entry in entries}
    if len(entries) <= 1 or not scopes <= {"ledger", "ledger_config"}:
        return []
    rows = []
    for entry in entries:
        rows.append((
            str(entry.get("ledger") or "?"),
            str(entry.get("cash_pool") or "?"),
            ", ".join(str(strategy) for strategy in (entry.get("strategies") or [])) or "无",
        ))
    return sorted(rows)


def source_route_display(entries: list[dict[str, Any]]) -> tuple[str, list[tuple[str, str, str]]]:
    rows = source_route_rows(entries)
    if not rows:
        return "empty", []
    return "table", rows


def grouped_values(
    field_name: str,
    values: list[dict[str, Any]],
    *,
    display_field_value: DisplayFieldValue,
    display_key: DisplayKey,
) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for entry in values:
        if not isinstance(entry, dict):
            continue
        display_value = display_field_value(field_name, entry.get("value"))
        key = display_key(display_value)
        bucket = groups.setdefault(key, {"value": display_value, "entries": []})
        bucket["entries"].append(entry)
    return list(groups.values())


def value_is_empty(value: Any, *, normalize: Normalize) -> bool:
    if value is None:
        return True
    normalized = normalize(value)
    if normalized is None:
        return True
    if normalized == "":
        return True
    if isinstance(normalized, (list, tuple, dict, set)) and len(normalized) == 0:
        return True
    if isinstance(normalized, str) and normalized.strip().lower() in {"null", "none", "[]", "{}"}:
        return True
    return False


def source_label(entry: Mapping[str, Any]) -> str:
    scope = str(entry.get("scope") or "")
    if scope == "strategy_config":
        return f"策略配置 {entry.get('strategy') or '?'}"
    if scope == "strategy_context":
        return f"策略上下文 {entry.get('strategy') or '?'}"
    if scope == "ledger":
        strategies = ", ".join(entry.get("strategies") or []) or "无"
        return (
            f"账本 {entry.get('ledger') or '?'} | 现金池 {entry.get('cash_pool') or '?'}"
            f" | 策略 {strategies}"
        )
    if scope == "ledger_config":
        strategies = ", ".join(entry.get("strategies") or []) or "无"
        return (
            f"账本配置 {entry.get('ledger') or '?'} | 现金池 {entry.get('cash_pool') or '?'}"
            f" | 策略 {strategies}"
        )
    return "共享上下文"
