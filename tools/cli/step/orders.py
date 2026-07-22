"""Order-list projections for construction and constraint steps."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .values import route_label, scalar, table_from_mappings


def render_rows(field: str, rows: list[Mapping[str, Any]], *, indent: str) -> list[str] | None:
    if not field.endswith(".orders"):
        return None
    rendered = []
    for row in rows:
        value = row.get("after", row.get("value"))
        if not isinstance(value, list) or not all(isinstance(order, Mapping) for order in value):
            return None
        owner = str(row.get("strategy") or route_label(row))
        for order in value:
            rendered.append({
                "owner": owner, "instrument": order.get("instrument"),
                "quantity": scalar(order.get("quantity")),
                "intent": scalar(order.get("intent_quantity")),
                "status": order.get("status"), "reject_reason": order.get("reject_reason"),
                "order_id": order.get("order_id"), "fields": scalar(order.get("fields")),
            })
    return table_from_mappings(rendered, indent=indent)
