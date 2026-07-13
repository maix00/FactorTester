"""Shared helpers for strategy/ledger/cash-pool audit scope tables."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


Route = tuple[str, ...]
ValueMap = Mapping[Route, str]
NamedValueMap = tuple[str, ValueMap]


def combine_route_value_maps(
    tables: Sequence[NamedValueMap],
) -> tuple[list[str], list[tuple[Any, ...]]] | None:
    """Combine same-route scalar field maps into one table.

    ``tables`` are ``(field_column, {route_tuple: value_text})`` pairs.  The
    routes must match exactly so the resulting table can put each field in its
    own value column without losing scope identity.
    """
    if not tables:
        return None
    route_keys = [tuple(sorted(table[1])) for table in tables]
    if not route_keys or any(keys != route_keys[0] for keys in route_keys[1:]):
        return None
    field_columns = [table[0] for table in tables]
    value_maps = [table[1] for table in tables]
    rows = [
        tuple([*route, *[value_map[route] for value_map in value_maps]])
        for route in route_keys[0]
    ]
    return field_columns, sorted(rows)


def group_rows_by_value_tuple(
    rows: Mapping[str, tuple[str, ...]],
    *,
    joined_key_header: str,
) -> tuple[tuple[str, ...], list[tuple[Any, ...]]]:
    """Group same value tuples across strategy-like row keys.

    This is used when multiple strategies share the exact same field values;
    the caller keeps only one row with a comma-joined strategy cell.
    """
    grouped: dict[tuple[str, ...], list[str]] = {}
    for key, values in rows.items():
        grouped.setdefault(values, []).append(key)
    return (
        (joined_key_header,),
        [tuple([", ".join(keys), *values]) for values, keys in grouped.items()],
    )
