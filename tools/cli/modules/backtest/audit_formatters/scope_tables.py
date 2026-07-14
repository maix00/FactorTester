"""Shared helpers for strategy/ledger/cash-pool audit scope tables."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


Route = tuple[str, ...]
ValueMap = Mapping[Route, str]
NamedValueMap = tuple[str, ValueMap]
ScopeDimension = str

SCOPE_DIMENSIONS: tuple[ScopeDimension, ...] = ("strategy", "ledger", "cash_pool", "product")


def scoped_dimensions(entry: Mapping[str, Any]) -> tuple[ScopeDimension, ...]:
    """Return owner dimensions present on a scoped audit entry.

    This separates the table owner dimensions (strategy/ledger/cash_pool/product)
    from the legacy ``scope`` string (strategy_config/ledger_config/context).
    """
    return tuple(dimension for dimension in SCOPE_DIMENSIONS if entry.get(dimension) not in (None, ""))


def scope_route(entry: Mapping[str, Any], dimensions: Sequence[ScopeDimension]) -> Route:
    """Build a route tuple for the requested owner dimensions."""
    return tuple(str(entry.get(dimension) or "?") for dimension in dimensions)


def is_scoped_entries(
    entries: Sequence[Mapping[str, Any]],
    *,
    required_dimensions: Sequence[ScopeDimension] = (),
    allowed_record_scopes: set[str] | frozenset[str] | None = None,
    forbid_record_scopes: set[str] | frozenset[str] | None = None,
    require_all_required_dimensions: bool = True,
) -> bool:
    """Return whether records can be rendered as a scoped table.

    ``required_dimensions`` describes owner/index dimensions, for example
    ``("strategy",)`` or ``("ledger", "cash_pool")``.  ``allowed_record_scopes``
    checks the legacy backend record scope values while the renderer is migrated.
    """
    if not entries:
        return False
    record_scopes = {str(entry.get("scope") or "") for entry in entries}
    if allowed_record_scopes is not None and not (bool(record_scopes) and record_scopes <= set(allowed_record_scopes)):
        return False
    if forbid_record_scopes is not None and any(scope in forbid_record_scopes for scope in record_scopes):
        return False
    if require_all_required_dimensions:
        return all(
            all(entry.get(dimension) not in (None, "") for dimension in required_dimensions)
            for entry in entries
        )
    return any(
        all(entry.get(dimension) not in (None, "") for dimension in required_dimensions)
        for entry in entries
    )


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


def mapping_sequence_subfield_columns(
    base_column: str,
    values: Sequence[Any],
    *,
    normalize,
) -> list[str] | None:
    """Return stable child columns for a single-item mapping sequence.

    This is scope-agnostic: callers decide whether a field is allowed to use
    this expansion.  The helper only verifies that every present value has the
    same scalar child-key layout.
    """
    columns: list[str] | None = None
    for value in values:
        if value is None:
            continue
        child_keys = single_mapping_sequence_keys(value, normalize=normalize)
        if child_keys is None:
            return None
        candidate = [f"{base_column}.{child_key}" for child_key in child_keys]
        if columns is None:
            columns = candidate
        elif columns != candidate:
            return None
    return columns


def mapping_sequence_subfield_values(
    value: Any,
    expected_count: int,
    *,
    normalize,
    scalar_cell,
) -> list[str]:
    item = single_mapping_sequence_item(value, normalize=normalize)
    if item is None:
        return [""] * expected_count
    return [scalar_cell(item.get(child_key)) for child_key in list(item)[:expected_count]]


def single_mapping_sequence_keys(value: Any, *, normalize) -> list[str] | None:
    item = single_mapping_sequence_item(value, normalize=normalize)
    if item is None:
        return None
    return [str(key) for key in item]


def single_mapping_sequence_item(value: Any, *, normalize) -> dict[str, Any] | None:
    normalized = normalize(value)
    if not isinstance(normalized, (list, tuple)) or len(normalized) != 1:
        return None
    item = normalized[0]
    if not isinstance(item, dict) or not item:
        return None
    if any(isinstance(child_value, (dict, list, tuple)) for child_value in item.values()):
        return None
    return item
