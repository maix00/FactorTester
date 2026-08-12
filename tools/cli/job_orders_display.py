"""Human-readable tables for retained order audit artifacts."""

from __future__ import annotations

from typing import Any

import click


def print_group_rows(rows: list[dict[str, Any]]) -> None:
    print_table(rows, (
        "strategy_id", "order_group_id", "products", "status",
        "requested_quantity", "filled_quantity", "active_leaves",
        "terminal_unfilled", "child_count",
    ))


def print_group_detail(payload: dict[str, Any]) -> None:
    group = payload["group"]
    click.echo(
        f"group={group['order_group_id']} strategy={payload['strategy_id']} "
        f"status={group['status']} policy={group['execution_policy']} "
        f"supersedes={group.get('supersedes_group_id') or '-'}"
    )
    click.echo("orders:")
    print_table(payload["orders"], (
        "order_id", "product", "side", "offset", "status",
        "requested_quantity", "filled_quantity", "active_leaves",
        "terminal_unfilled", "next_attempt_at",
    ), indent="  ")
    for label, fields in (
        ("attempts", ("attempt_id", "order_id", "revision", "timestamp", "market_timestamp")),
        ("fills", ("fill_id", "order_id", "attempt_id", "timestamp", "quantity", "price", "fee")),
        ("settlements", (
            "fill_id", "realized_pnl", "fee", "cash_before", "cash_after",
            "margin_before", "margin_after",
        )),
        ("actions", ("request_id", "order_id", "action", "submitted_at", "revision", "reason")),
    ):
        click.echo(f"{label}:")
        print_table(payload[label], fields, indent="  ")


def print_table(
    rows: list[dict[str, Any]], fields: tuple[str, ...], *, indent: str = "",
) -> None:
    if not rows:
        click.echo(f"{indent}(none)")
        return
    click.echo(indent + "\t".join(fields))
    for row in rows:
        click.echo(indent + "\t".join(text_value(row.get(field)) for field in fields))


def text_value(value: Any) -> str:
    if isinstance(value, list):
        return ",".join(str(item) for item in value)
    if value is None or value == "":
        return "-"
    return str(value)
