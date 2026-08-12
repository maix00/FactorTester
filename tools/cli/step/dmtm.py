"""Daily-mark-to-market audit projection."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import click

from .values import scalar, table_from_mappings


def render(value: Any) -> list[str]:
    if not isinstance(value, Mapping) or not any(value.get(key) for key in (
        "events", "resolved", "accounting_inputs", "market_rule_inputs",
        "cash_changes", "position_changes", "margin_changes",
    )):
        return []
    lines = [click.style("DMTM 审计", bold=True)]
    lines.extend(_section("事件", value.get("events")))
    lines.extend(_accounting(value.get("accounting_inputs")))
    lines.extend(_resolved(value.get("resolved")))
    lines.extend(_market_rules(value.get("market_rule_inputs")))
    lines.extend(_cash(value.get("cash_changes")))
    lines.extend(_positions(value.get("position_changes")))
    lines.extend(_section("保证金变化", value.get("margin_changes")))
    return lines


def _section(title: str, rows: Any) -> list[str]:
    items = [item for item in rows or [] if isinstance(item, Mapping)]
    if not items:
        return [f"  {title}: 0"]
    return [f"  {title}: {len(items)}", *table_from_mappings(items, indent="    ")]


def _accounting(records: Any) -> list[str]:
    rows = []
    for record in records or []:
        if not isinstance(record, Mapping):
            continue
        values = [item for item in record.get("values") or [] if isinstance(item, Mapping)]
        grouped: dict[str, int] = {}
        for item in values:
            grouped[scalar(item.get("value"))] = grouped.get(scalar(item.get("value")), 0) + 1
        rows.extend({"field": record.get("field"), "value": item, "ledgers": count} for item, count in grouped.items())
    return [f"  会计输入: {len(records or [])}", *table_from_mappings(rows, indent="    ")]


def _resolved(records: Any) -> list[str]:
    grouped: dict[str, dict[str, Any]] = {}
    for record in records or []:
        value = record.get("value") if isinstance(record, Mapping) else None
        if not isinstance(value, Mapping):
            continue
        for ledger, instruments in value.items():
            if not isinstance(instruments, Mapping):
                continue
            for instrument, item in instruments.items():
                if isinstance(item, Mapping):
                    row = grouped.setdefault(str(ledger), {"ledger": ledger, "instruments": 0, "enabled": 0, "sources": set(), "methods": set()})
                    row["instruments"] += 1
                    row["enabled"] += bool(item.get("enabled"))
                    row["sources"].add(str(item.get("source")))
                    row["methods"].add(str(item.get("cost_basis_method")))
    rows = [{**row, "sources": sorted(row["sources"]), "methods": sorted(row["methods"])} for row in grouped.values()]
    return [f"  DMTM 解析: {sum(row['instruments'] for row in rows)} instruments", *table_from_mappings(rows, indent="    "),
            click.style("    逐合约解析结果请使用 job step-field 查看。", dim=True)]


def _market_rules(records: Any) -> list[str]:
    rows = []
    for record in records or []:
        if not isinstance(record, Mapping):
            continue
        contextual = next((item.get("value") for item in record.get("values") or [] if isinstance(item, Mapping) and item.get("value") is not None), None)
        if isinstance(contextual, Mapping):
            nested = all(isinstance(item, Mapping) for item in contextual.values())
            detail = ", ".join(contextual) if nested and len(contextual) <= 8 else f"items={len(contextual)}"
        else:
            detail = scalar(contextual)
        rows.append({"field": record.get("field"), "summary": detail})
    return [f"  市场规则输入: {len(rows)}", *table_from_mappings(rows, indent="    ")]


def _money_parts(value: Any, prefix: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or value.get("type") != "DataMoney":
        return {prefix: scalar(value)}
    return {
        f"{prefix}_major": value.get("major_units"), f"{prefix}_minor": value.get("minor_units"),
        "currency": value.get("currency"), "scale": value.get("scale"),
    }


def _cash(records: Any) -> list[str]:
    rows = []
    for item in records or []:
        if not isinstance(item, Mapping):
            continue
        before, after = item.get("before"), item.get("after")
        row = {"ledger": item.get("ledger"), **_money_parts(before, "before"), **_money_parts(after, "after")}
        if isinstance(before, Mapping) and isinstance(after, Mapping):
            row["delta_major"] = (after.get("major_units") or 0) - (before.get("major_units") or 0)
            row["delta_minor"] = (after.get("minor_units") or 0) - (before.get("minor_units") or 0)
        rows.append(row)
    return [f"  现金变化: {len(rows)}", *table_from_mappings(rows, indent="    ")]


def _positions(records: Any) -> list[str]:
    grouped: dict[str, dict[str, Any]] = {}
    for record in records or []:
        if not isinstance(record, Mapping):
            continue
        for change in record.get("changes") or []:
            if not isinstance(change, Mapping):
                continue
            before = change.get("before") if isinstance(change.get("before"), Mapping) else {}
            after = change.get("after") if isinstance(change.get("after"), Mapping) else {}
            ledger = str(record.get("ledger"))
            row = grouped.setdefault(ledger, {"ledger": ledger, "instruments": 0, "settled": 0,
                                               "margin_before_major": 0.0, "margin_after_major": 0.0,
                                               "margin_before_minor": 0, "margin_after_minor": 0})
            row["instruments"] += 1
            row["settled"] += after.get("settlement_price") is not None
            for source, prefix in ((before, "margin_before"), (after, "margin_after")):
                money = source.get("margin_reserved")
                if isinstance(money, Mapping):
                    row[f"{prefix}_major"] += float(money.get("major_units") or 0)
                    row[f"{prefix}_minor"] += int(money.get("minor_units") or 0)
    rows = list(grouped.values())
    return [f"  持仓结算变化: {sum(row['instruments'] for row in rows)}", *table_from_mappings(rows, indent="    "),
            click.style("    逐合约持仓结算变化请使用 job step-field 查看。", dim=True)]
