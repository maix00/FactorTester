"""Daily-mark-to-market audit projection."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import click

from .values import scalar, table_from_mappings


def render(value: Any) -> list[str]:
    if not isinstance(value, Mapping):
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
    rows = []
    for record in records or []:
        value = record.get("value") if isinstance(record, Mapping) else None
        if not isinstance(value, Mapping):
            continue
        for ledger, instruments in value.items():
            if not isinstance(instruments, Mapping):
                continue
            for instrument, item in instruments.items():
                if isinstance(item, Mapping):
                    rows.append({"ledger": ledger, "instrument": instrument, **item})
    return [f"  DMTM 解析: {len(rows)} instruments", *table_from_mappings(rows, indent="    ")]


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
    rows = []
    for record in records or []:
        if not isinstance(record, Mapping):
            continue
        for change in record.get("changes") or []:
            if not isinstance(change, Mapping):
                continue
            before = change.get("before") if isinstance(change.get("before"), Mapping) else {}
            after = change.get("after") if isinstance(change.get("after"), Mapping) else {}
            rows.append({
                "ledger": record.get("ledger"), "instrument": change.get("instrument"),
                "quantity": after.get("quantity"), "settlement_before": before.get("settlement_price"),
                "settlement_after": after.get("settlement_price"),
                **_money_parts(before.get("margin_reserved"), "margin_before"),
                **_money_parts(after.get("margin_reserved"), "margin_after"),
            })
    return [f"  持仓结算变化: {len(rows)}", *table_from_mappings(rows, indent="    ")]
