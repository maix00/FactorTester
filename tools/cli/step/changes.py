"""Change and PositionBook projections for step events."""

from __future__ import annotations

from collections.abc import Mapping
import json
from typing import Any

import click

from . import events, market_data, orders, portfolio, positions, products, run_window
from .values import highlighted, is_scalar, render_value, route_label, scalar, scope, table_from_mappings


def render_changes(
    title: str, changes: Any, *, field_optional: bool = False,
    omit_fields: set[str] | None = None,
) -> list[str]:
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for change in changes or []:
        if not isinstance(change, Mapping):
            continue
        field = str(change.get("field") or ("payload" if field_optional else ""))
        if field in (omit_fields or set()):
            continue
        grouped.setdefault(field, []).append(change)
    body: list[str] = []
    for field, rows in grouped.items():
        body.append(click.style(field, bold=True))
        if field.endswith(".positions"):
            body.extend(
                positions.render_initialization(rows, indent="  ")
                or render_position_changes(rows, indent="  ")
            )
        else:
            rows = _group_identical_changes(rows)
            body.extend(
                orders.render_rows(field, rows, indent="  ")
                or portfolio.render_rows(field, rows, indent="  ")
                or products.render_products_change(field, rows, indent="  ")
                or render_change_rows(rows, indent="  ")
            )
    return [click.style(title, bold=True), *body] if body else []


def render_change_rows(rows: list[Mapping[str, Any]], *, indent: str) -> list[str]:
    table_rows: list[dict[str, Any]] = []
    details: list[str] = []
    for row in rows:
        before, after = row.get("before"), row.get("after")
        if is_scalar(before) and is_scalar(after):
            table_rows.append({**scope(row), "before": scalar(before), "after": highlighted(after)})
            continue
        field = str(row.get("field") or "")
        special_after = (
            events.render(field, after, indent=indent + "    ")
            or market_data.render_change(field, after, indent=indent + "    ")
            or run_window.render(field, after, indent=indent + "    ")
        )
        if before is None and special_after is not None:
            details.extend([
                f"{indent}{route_label(row)}",
                f"{indent}  added:",
                *special_after,
            ])
            continue
        details.extend([
            f"{indent}{route_label(row)}",
            f"{indent}  before:",
            *render_value(before, indent=indent + "    "),
            click.style(f"{indent}  after:", fg="bright_yellow", bold=True),
            *render_value(after, indent=indent + "    ", highlight=True),
        ])
    return [*table_from_mappings(table_rows, indent=indent), *details]


def render_position_changes(rows: list[Mapping[str, Any]], *, indent: str) -> list[str]:
    table_rows: list[dict[str, Any]] = []
    for row in rows:
        for item in row.get("changes") or []:
            if not isinstance(item, Mapping):
                continue
            before, after = item.get("before"), item.get("after")
            keys = _mapping_union_keys(before, after)
            if not keys:
                table_rows.append({
                    **scope(row), "instrument": item.get("instrument"), "field": "value",
                    "before": scalar(before), "after": highlighted(after),
                })
                continue
            for key in keys:
                old = before.get(key) if isinstance(before, Mapping) else None
                new = after.get(key) if isinstance(after, Mapping) else None
                if old != new:
                    table_rows.append({
                        **scope(row), "instrument": item.get("instrument"), "field": key,
                        "before": scalar(old), "after": highlighted(new),
                    })
    return table_from_mappings(table_rows, indent=indent)


def _mapping_union_keys(before: Any, after: Any) -> list[str]:
    mappings = (value for value in (before, after) if isinstance(value, Mapping))
    return sorted({str(key) for mapping in mappings for key in mapping})


def _group_identical_changes(rows: list[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        key = json.dumps([row.get("before"), row.get("after"), row.get("changes")], ensure_ascii=False, sort_keys=True)
        grouped.setdefault(key, []).append(row)
    result: list[Mapping[str, Any]] = []
    for matches in grouped.values():
        if len(matches) == 1:
            result.append(matches[0])
            continue
        merged = dict(matches[0])
        owners = [str(item.get("strategy") or route_label(item)) for item in matches]
        merged.pop("strategy", None)
        merged["strategies"] = owners
        result.append(merged)
    return result
