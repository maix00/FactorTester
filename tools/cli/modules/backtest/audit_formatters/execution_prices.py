"""Execution-price audit table helpers."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any


DisplayValue = Callable[[str, Any], Any]
Normalize = Callable[[Any], Any]
ScalarCell = Callable[[Any], str]
ChangeCell = Callable[[Any, Any], str]


def value_table(
    field_name: str,
    values: Sequence[Mapping[str, Any]],
    *,
    display_field_value: DisplayValue,
    normalize: Normalize,
    scalar_cell: ScalarCell,
) -> tuple[tuple[str, ...], list[tuple[Any, ...]]] | None:
    rows = price_rows_from_entries(
        field_name,
        values,
        value_key="value",
        display_field_value=display_field_value,
        normalize=normalize,
        scalar_cell=scalar_cell,
    )
    if not rows:
        return None
    return ("strategy", "product", "execution_price"), rows


def change_table(
    field_name: str,
    changes: Sequence[Mapping[str, Any]],
    *,
    display_field_value: DisplayValue,
    normalize: Normalize,
    scalar_cell: ScalarCell,
    change_cell: ChangeCell,
) -> tuple[tuple[str, ...], list[tuple[Any, ...]]] | None:
    before_rows = price_row_map_from_entries(
        field_name,
        changes,
        value_key="before",
        display_field_value=display_field_value,
        normalize=normalize,
        scalar_cell=scalar_cell,
    )
    after_rows = price_row_map_from_entries(
        field_name,
        changes,
        value_key="after",
        display_field_value=display_field_value,
        normalize=normalize,
        scalar_cell=scalar_cell,
    )
    keys = sorted(set(before_rows) | set(after_rows))
    if not keys:
        return None
    rows = [
        (
            strategy,
            product,
            change_cell(before_rows.get((strategy, product), "null"), after_rows.get((strategy, product), "null")),
        )
        for strategy, product in keys
    ]
    return ("strategy", "product", "execution_price"), rows


def price_rows_from_entries(
    field_name: str,
    entries: Sequence[Mapping[str, Any]],
    *,
    value_key: str,
    display_field_value: DisplayValue,
    normalize: Normalize,
    scalar_cell: ScalarCell,
) -> list[tuple[Any, ...]]:
    row_map = price_row_map_from_entries(
        field_name,
        entries,
        value_key=value_key,
        display_field_value=display_field_value,
        normalize=normalize,
        scalar_cell=scalar_cell,
    )
    return [(*key, value) for key, value in sorted(row_map.items())]


def price_row_map_from_entries(
    field_name: str,
    entries: Sequence[Mapping[str, Any]],
    *,
    value_key: str,
    display_field_value: DisplayValue,
    normalize: Normalize,
    scalar_cell: ScalarCell,
) -> dict[tuple[str, str], str]:
    strategy_rows: dict[tuple[str, str], str] = {}
    context_rows: dict[tuple[str, str], str] = {}
    for entry in entries:
        value = display_field_value(field_name, entry.get(value_key))
        strategy = str(entry.get("strategy") or "").strip()
        if strategy:
            strategy_rows.update(flat_price_rows(strategy, value, normalize=normalize, scalar_cell=scalar_cell))
        else:
            context_rows.update(nested_price_rows(value, normalize=normalize, scalar_cell=scalar_cell))
    return strategy_rows or context_rows


def nested_price_rows(value: Any, *, normalize: Normalize, scalar_cell: ScalarCell) -> dict[tuple[str, str], str]:
    normalized = normalize(value)
    if not isinstance(normalized, Mapping):
        return {}
    rows: dict[tuple[str, str], str] = {}
    for strategy, prices in normalized.items():
        rows.update(flat_price_rows(str(strategy), prices, normalize=normalize, scalar_cell=scalar_cell))
    return rows


def flat_price_rows(
    strategy: str,
    value: Any,
    *,
    normalize: Normalize,
    scalar_cell: ScalarCell,
) -> dict[tuple[str, str], str]:
    normalized = normalize(value)
    if not isinstance(normalized, Mapping):
        return {}
    rows: dict[tuple[str, str], str] = {}
    for product, price in normalized.items():
        if isinstance(price, Mapping):
            continue
        rows[(strategy, str(product))] = scalar_cell(price)
    return rows
