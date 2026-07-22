"""Portfolio weight and quantity-map projections."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .values import route_label, scalar, table_from_mappings


MAP_FIELDS = (".target_weights", ".raw_deltas", ".sized_deltas", ".deltas", ".signal_value")


def render_rows(field: str, rows: list[Mapping[str, Any]], *, indent: str) -> list[str] | None:
    if not field.endswith(MAP_FIELDS):
        return None
    result = []
    for row in rows:
        value = row.get("after", row.get("value"))
        if not isinstance(value, Mapping) or not all(not isinstance(item, Mapping) for item in value.values()):
            return None
        owner = str(row.get("strategy") or route_label(row))
        result.extend(
            {"owner": owner, "instrument": instrument, "value": scalar(item)}
            for instrument, item in value.items()
        )
    return table_from_mappings(result, indent=indent)
