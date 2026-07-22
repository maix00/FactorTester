"""Portfolio weight and quantity-map projections."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import click

from .values import route_label, scalar, table_from_mappings


MAP_FIELDS = (".target_weights", ".raw_deltas", ".sized_deltas", ".deltas", ".signal_value")


def render_rows(field: str, rows: list[Mapping[str, Any]], *, indent: str) -> list[str] | None:
    if not field.endswith(MAP_FIELDS):
        return None
    result = []
    omitted_zero = 0
    omit_zero = field.endswith((".raw_deltas", ".sized_deltas", ".deltas"))
    for row in rows:
        value = row.get("after", row.get("value"))
        if not isinstance(value, Mapping) or not all(not isinstance(item, Mapping) for item in value.values()):
            return None
        owner = str(row.get("strategy") or route_label(row))
        for instrument, item in value.items():
            if omit_zero and item == 0:
                omitted_zero += 1
                continue
            result.append({"owner": owner, "instrument": instrument, "value": scalar(item)})
    lines = table_from_mappings(result, indent=indent)
    if omitted_zero:
        lines.append(click.style(
            f"{indent}已省略 {omitted_zero} 个零 delta；job step-field 可查看完整映射。",
            dim=True,
        ))
    return lines
