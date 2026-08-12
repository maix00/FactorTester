"""Order-list projections for construction and constraint steps."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import click

from .values import route_label, scalar, table_from_mappings


def render_rows(field: str, rows: list[Mapping[str, Any]], *, indent: str) -> list[str] | None:
    if not field.endswith(".orders"):
        return None
    summaries: dict[str, dict[str, Any]] = {}
    exceptions = []
    for row in rows:
        value = row.get("after", row.get("value"))
        if not isinstance(value, list) or not all(isinstance(order, Mapping) for order in value):
            return None
        owner = str(row.get("strategy") or route_label(row))
        for order in value:
            quantity = order.get("quantity")
            status = str(order.get("status") or "-")
            summary = summaries.setdefault(owner, {
                "owner": owner, "groups": set(), "orders": 0,
                "buy": 0, "sell": 0, "gross_quantity": 0.0,
                "filled_quantity": 0.0, "active_leaves": 0.0,
                "rejected": 0, "adjusted": 0, "statuses": set(),
            })
            group_id = str(order.get("order_group_id") or "")
            if group_id:
                summary["groups"].add(group_id)
            summary["orders"] += 1
            summary["buy"] += isinstance(quantity, (int, float)) and quantity > 0
            summary["sell"] += isinstance(quantity, (int, float)) and quantity < 0
            summary["gross_quantity"] += abs(float(quantity)) if isinstance(quantity, (int, float)) else 0
            filled = order.get("filled_quantity")
            requested = order.get("accepted_quantity", order.get("requested_quantity"))
            if isinstance(filled, (int, float)):
                summary["filled_quantity"] += abs(float(filled))
            if isinstance(requested, (int, float)) and isinstance(filled, (int, float)):
                summary["active_leaves"] += max(abs(float(requested)) - abs(float(filled)), 0.0)
            summary["rejected"] += status == "rejected"
            summary["adjusted"] += quantity != order.get("intent_quantity")
            summary["statuses"].add(status)
            if status in {"rejected", "blocked", "partially_filled"} or quantity != order.get("intent_quantity") or order.get("reject_reason"):
                exceptions.append({
                "owner": owner, "instrument": order.get("instrument"),
                "group": group_id or "-",
                "offset": order.get("offset"),
                "quantity": scalar(order.get("quantity")),
                "intent": scalar(order.get("intent_quantity")),
                "filled": scalar(order.get("filled_quantity")),
                "status": order.get("status"), "reject_reason": order.get("reject_reason"),
                "order_id": order.get("order_id"),
                })
    rows = [{
        **row,
        "groups": len(row["groups"]),
        "statuses": sorted(row["statuses"]),
    } for row in summaries.values()]
    lines = table_from_mappings(rows, indent=indent)
    if exceptions:
        lines.extend([f"{indent}异常或调整订单:", *table_from_mappings(exceptions, indent=indent + "  ")])
    lines.append(click.style(
        f"{indent}完整订单链请使用 job orders/order（需 retain-full）；"
        "当前 step 原始值可用 job step-field。",
        dim=True,
    ))
    return lines
