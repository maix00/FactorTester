"""Small printer helpers shared by step audit sections."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import click


DisplayValue = Callable[[str, Any], Any]
DisplayKey = Callable[[Any], str]
ValueIsEmpty = Callable[[Any], bool]
ScalarRecordCandidate = tuple[tuple[Any, ...] | None, Any, bool]
ItemKey = Callable[[Any], Any]
FieldSortKey = Callable[[str], tuple[Any, ...]]
ItemPredicate = Callable[[Any], bool]
CombinedPrinter = Callable[[str, list[Any]], bool]
CombinedBuilder = Callable[[Any, list[Any]], list[Any]]


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


def combined_scalar_routes(table: tuple[Any, ...]) -> tuple[Any, ...]:
    return tuple(sorted(table[1]))


def scalar_record_group(candidates: list[ScalarRecordCandidate]) -> tuple[tuple[Any, ...] | None, Any, tuple[Any, ...] | None]:
    for table, printer, _is_strategy in candidates:
        if table is not None:
            return table, printer, combined_scalar_routes(table)
    return None, None, None


def collect_following_by_key(
    items: list[Any],
    *,
    start: int,
    consumed_indexes: set[int],
    current_key: Any,
    key_fn: ItemKey,
) -> tuple[list[Any], list[int]]:
    matches: list[Any] = []
    indexes: list[int] = []
    lookahead = start + 1
    while lookahead < len(items):
        if lookahead in consumed_indexes:
            lookahead += 1
            continue
        item = items[lookahead]
        if key_fn(item) == current_key:
            matches.append(item)
            indexes.append(lookahead)
        lookahead += 1
    return matches, indexes


def try_print_combined_group(
    items: list[Any],
    *,
    start: int,
    consumed_indexes: set[int],
    current_key: Any,
    key_fn: ItemKey,
    printer: CombinedPrinter,
    prefix: str,
    combine: CombinedBuilder,
) -> tuple[bool, int]:
    matches, combined_indexes = collect_following_by_key(
        items,
        start=start,
        consumed_indexes=consumed_indexes,
        current_key=current_key,
        key_fn=key_fn,
    )
    combined = combine(items[start], matches)
    if printer(prefix, combined):
        consumed_indexes.update(combined_indexes)
        return True, start + 1
    return False, start


def sorted_field_records(records: list[dict[str, Any]], *, sort_key: FieldSortKey) -> list[dict[str, Any]]:
    return sorted(records, key=lambda item: sort_key(str(item.get("field") or "")))


def sorted_field_change_items(
    changes: list[dict[str, Any]],
    *,
    sort_key: FieldSortKey,
) -> list[tuple[str, list[dict[str, Any]]]]:
    by_field: dict[str, list[dict[str, Any]]] = {}
    for change in changes:
        by_field.setdefault(str(change.get("field") or ""), []).append(change)
    return sorted(by_field.items(), key=lambda item: sort_key(item[0]))


def collect_contiguous(
    items: list[Any],
    *,
    start: int,
    predicate: ItemPredicate,
) -> tuple[list[Any], int]:
    collected: list[Any] = []
    index = start
    while index < len(items) and predicate(items[index]):
        collected.append(items[index])
        index += 1
    return collected, index


def field_change_buckets(
    field_name: str,
    changes: list[dict[str, Any]],
    *,
    display_value: DisplayValue,
    display_key: DisplayKey,
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for change in changes:
        before = display_value(field_name, change.get("before"))
        after = display_value(field_name, change.get("after"))
        key = (display_key(before), display_key(after))
        bucket = grouped.setdefault(key, {"before": before, "after": after, "entries": []})
        bucket["entries"].append(change)
    return list(grouped.values())
