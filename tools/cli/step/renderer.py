"""Top-level human projection for a serialized step event."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

import click

from tools.cli.table import render_key_value_rows

from .changes import render_changes
from . import dmtm, market_data, orders, portfolio, positions, products, run_window
from .values import is_scalar, render_value, route_label, scalar, scope, table_from_mappings


def render_step_event(data: Mapping[str, Any]) -> list[str]:
    lines = [click.style(
        f"STEP {data.get('timestamp') or '-'}  {str(data.get('flow_phase') or '').upper()}  "
        f"{data.get('flow_id') or data.get('flow_name') or '-'}",
        fg="bright_red", bold=True,
    )]
    description = str(data.get("description") or "").strip()
    if description:
        lines.append(f"  说明: {description}")
    lines.extend(_render_current_event(data.get("current_event")))
    lines.extend(_render_strategies(data.get("strategies")))
    lines.extend(_render_field_values("输入", data.get("inputs"), combine_scalars=True))
    changed_fields = {
        str(item.get("field") or "")
        for item in data.get("output_changes") or []
        if isinstance(item, Mapping)
    }
    lines.extend(_render_field_values(
        "未变化输出", data.get("outputs"),
        omit_represented=True, omit_fields=changed_fields,
    ))
    lines.extend(render_changes("输出变化", data.get("output_changes")))
    lines.extend(render_changes("账本旁路变化", data.get("ledger_changes")))
    lines.extend(render_changes("事件载荷变化", data.get("event_payload_changes"), field_optional=True))
    lines.extend(dmtm.render(data.get("dmtm")))
    violations = [item for item in data.get("input_contract_violations") or [] if isinstance(item, Mapping)]
    if violations:
        lines.extend([click.style("合约违规", fg="bright_red", bold=True), *table_from_mappings(violations, indent="  ")])
    return lines


def _section(title: str, body: list[str]) -> list[str]:
    return [click.style(title, bold=True), *body] if body else []


def _render_current_event(value: Any) -> list[str]:
    if not isinstance(value, Mapping):
        return []
    rows = [item for item in value.get("subjects") or [] if isinstance(item, Mapping)]
    body = render_key_value_rows([
        ("event_kind", value.get("event_kind") or "-"),
        ("batch_count", value.get("batch_count", len(rows))),
    ], indent="  ")
    return _section("当前事件", [*body, *table_from_mappings(rows, indent="  ")])


def _render_strategies(value: Any) -> list[str]:
    rows = [row for row in value or [] if isinstance(row, Mapping)]
    return _section("策略作用域", table_from_mappings(rows, indent="  "))


def _render_field_values(
    title: str,
    records: Any,
    *,
    omit_represented: bool = False,
    omit_fields: set[str] | None = None,
    combine_scalars: bool = False,
) -> list[str]:
    body: list[str] = []
    materialized = [record for record in records or [] if isinstance(record, Mapping)]
    if combine_scalars:
        combined, consumed = _combined_scalar_fields(materialized)
        body.extend(combined)
    else:
        consumed = set()
    for index, record in enumerate(materialized):
        if index in consumed:
            continue
        if not isinstance(record, Mapping) or (omit_represented and record.get("represented_by")):
            continue
        field = str(record.get("field") or "")
        if field in (omit_fields or set()):
            continue
        values = list(record.get("values") or [])
        if not values:
            continue
        body.extend([click.style(field, bold=True), *_render_scoped_values(field, values)])
    return _section(title, body)


def _render_scoped_values(field: str, values: list[Any]) -> list[str]:
    values, omitted_empty = _drop_shadowed_empty_values(values)
    mapped = [item for item in values if isinstance(item, Mapping)]
    position_lines = positions.render_values(mapped, indent="  ") if field.endswith(".positions") else None
    portfolio_lines = portfolio.render_rows(field, mapped, indent="  ")
    order_lines = orders.render_rows(field, mapped, indent="  ")
    if position_lines is not None or portfolio_lines is not None or order_lines is not None:
        return [*(position_lines or portfolio_lines or order_lines or []), *_omitted_empty_note(omitted_empty)]
    product_lines = products.render_values(field, values, indent="  ")
    if product_lines is not None:
        return [*product_lines, *_omitted_empty_note(omitted_empty)]
    scalar_rows: list[dict[str, Any]] = []
    details: list[str] = []
    for entry in _group_identical_complex_values(values):
        if not isinstance(entry, Mapping):
            details.extend(render_value(entry, indent="  "))
            continue
        value = entry.get("value")
        if is_scalar(value):
            scalar_rows.append({**scope(entry), "value": scalar(value)})
        else:
            special = (
                products.render(field, value, indent="    ")
                or market_data.render_input(field, value, indent="    ")
                or run_window.render(field, value, indent="    ")
            )
            details.extend([f"  {route_label(entry)}", *(special or render_value(value, indent="    "))])
    return [*table_from_mappings(scalar_rows, indent="  "), *details, *_omitted_empty_note(omitted_empty)]


def _drop_shadowed_empty_values(values: list[Any]) -> tuple[list[Any], int]:
    mappings = [entry for entry in values if isinstance(entry, Mapping)]
    if not any(entry.get("value") is not None for entry in mappings):
        return values, 0
    retained = [
        entry for entry in values
        if not isinstance(entry, Mapping) or entry.get("value") is not None
    ]
    return retained, len(values) - len(retained)


def _omitted_empty_note(count: int) -> list[str]:
    if not count:
        return []
    return [click.style(f"  已省略 {count} 条同字段空默认；step-field 可查看原记录。", dim=True)]


def _group_identical_complex_values(values: list[Any]) -> list[Any]:
    groups: dict[str, list[Mapping[str, Any]]] = {}
    passthrough: list[Any] = []
    for entry in values:
        if not isinstance(entry, Mapping) or is_scalar(entry.get("value")):
            passthrough.append(entry)
            continue
        key = json.dumps(entry.get("value"), ensure_ascii=False, sort_keys=True)
        groups.setdefault(key, []).append(entry)
    for entries in groups.values():
        if len(entries) == 1:
            passthrough.append(entries[0])
            continue
        merged = dict(entries[0])
        owners = [str(item.get("strategy") or route_label(item)) for item in entries]
        merged.pop("strategy", None)
        merged["strategies"] = owners
        passthrough.append(merged)
    return passthrough


def _combined_scalar_fields(records: list[Mapping[str, Any]]) -> tuple[list[str], set[int]]:
    rows: list[dict[str, Any]] = []
    consumed: set[int] = set()
    for index, record in enumerate(records):
        values = [item for item in record.get("values") or [] if isinstance(item, Mapping)]
        qualified = str(record.get("field") or "")
        if qualified.endswith(".products"):
            continue
        if not values or not all(is_scalar(item.get("value")) for item in values):
            continue
        grouped: dict[str, list[str]] = {}
        for item in values:
            grouped.setdefault(scalar(item.get("value")), []).append(
                _owner_summary(item)
            )
        short = qualified.rsplit(".", 1)[-1]
        field = f"{short} [{qualified}]"
        all_strategy_scoped = len(values) > 1 and all(_owner_summary(item) != "shared" for item in values)
        for value, owners in grouped.items():
            owner = "all strategies" if all_strategy_scoped and len(owners) == len(values) else ", ".join(owners)
            rows.append({"field": field, "owners": owner, "value": value})
        consumed.add(index)
    return (table_from_mappings(rows, indent="  ") if rows else []), consumed


def _owner_summary(item: Mapping[str, Any]) -> str:
    if item.get("strategy"):
        return str(item["strategy"])
    strategies = item.get("strategies")
    if isinstance(strategies, list) and strategies:
        return ", ".join(str(value) for value in strategies)
    return route_label(item)
