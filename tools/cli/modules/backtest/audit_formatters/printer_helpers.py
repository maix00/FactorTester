"""Small printer helpers shared by step audit sections."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import click


DisplayValue = Callable[[str, Any], Any]
ValueIsEmpty = Callable[[Any], bool]


def combined_single_field_label(qualified_name: str) -> str:
    return click.style(f"{qualified_name.rsplit('.', 1)[-1]} [{qualified_name}]", bold=True)


def combined_field_label(records: list[dict[str, Any]]) -> str:
    return "；".join(combined_single_field_label(str(record.get("field") or "")) for record in records)


def combined_change_field_label(records: list[tuple[str, list[dict[str, Any]]]]) -> str:
    return "；".join(combined_single_field_label(field_name) for field_name, _ in records)


def combined_field_label_lines(prefix: str, records: list[dict[str, Any]]) -> list[str]:
    return [
        f"{prefix}{combined_single_field_label(str(record.get('field') or ''))}"
        for record in records
    ]


def combined_change_field_label_lines(prefix: str, records: list[tuple[str, list[dict[str, Any]]]]) -> list[str]:
    return [
        f"{prefix}{combined_single_field_label(field_name)}"
        for field_name, _ in records
    ]


def drop_empty_non_ledger_entries_when_ledger_values_exist(
    field_name: str,
    values: list[dict[str, Any]],
    *,
    display_value: DisplayValue,
    value_is_empty: ValueIsEmpty,
) -> list[dict[str, Any]]:
    """Prefer ledger/cash-pool total tables over repeated empty strategy defaults."""
    if not any(str(entry.get("scope") or "") in {"ledger", "ledger_config"} for entry in values):
        return values
    compacted: list[dict[str, Any]] = []
    for entry in values:
        scope = str(entry.get("scope") or "")
        if scope in {"ledger", "ledger_config"}:
            compacted.append(entry)
            continue
        display_item = display_value(field_name, entry.get("value"))
        if value_is_empty(display_item):
            continue
        compacted.append(entry)
    return compacted or values
