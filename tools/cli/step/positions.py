"""PositionBook initialization and delta projections."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import click

from .values import route_label, table_from_mappings


def render_initialization(rows: list[Mapping[str, Any]], *, indent: str) -> list[str] | None:
    if not rows or not all(row.get("before") is None and isinstance(row.get("after"), Mapping) for row in rows):
        return None
    summaries = []
    for row in rows:
        book = row["after"]
        nonzero = [
            instrument for instrument, position in book.items()
            if isinstance(position, Mapping) and float(position.get("quantity") or 0) != 0
        ]
        summaries.append({
            "owner": route_label(row), "instruments": len(book),
            "nonzero": len(nonzero), "state": "empty" if not nonzero else "active",
        })
    return [
        *table_from_mappings(summaries, indent=indent),
        click.style(f"{indent}空仓初始化未展开逐品种零值；可用 job step-field 查看完整 PositionBook。", dim=True),
    ]


def render_values(values: list[Mapping[str, Any]], *, indent: str) -> list[str] | None:
    books = [row for row in values if isinstance(row.get("value"), Mapping)]
    if not books:
        return None
    summaries = []
    for row in books:
        book = row["value"]
        nonzero = sum(
            1 for position in book.values()
            if isinstance(position, Mapping) and float(position.get("quantity") or 0) != 0
        )
        summaries.append({"owner": route_label(row), "instruments": len(book), "nonzero": nonzero})
    return table_from_mappings(summaries, indent=indent)


def render_margin_changes(rows: list[Mapping[str, Any]], *, indent: str) -> list[str] | None:
    summaries = []
    for row in rows:
        changes = [item for item in row.get("changes") or [] if isinstance(item, Mapping)]
        if not changes:
            return None
        pairs = []
        for change in changes:
            before = change.get("before") if isinstance(change.get("before"), Mapping) else {}
            after = change.get("after") if isinstance(change.get("after"), Mapping) else {}
            if set(before) != set(after) or any(
                before.get(key) != after.get(key) for key in before if key != "margin_reserved"
            ):
                return None
            pairs.append((before.get("margin_reserved"), after.get("margin_reserved")))
        summaries.append({
            "owner": route_label(row), "instruments": len(changes),
            "before_major": sum(_money_major(before) for before, _ in pairs),
            "after_major": sum(_money_major(after) for _, after in pairs),
        })
    return [
        *table_from_mappings(summaries, indent=indent),
        click.style(f"{indent}逐合约保证金变化请使用 job step-field 查看。", dim=True),
    ]


def _money_major(value: Any) -> float:
    if isinstance(value, Mapping) and value.get("type") == "DataMoney":
        return float(value.get("major_units") or 0)
    return float(value or 0)
