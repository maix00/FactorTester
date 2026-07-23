"""Inspect retained exchange-order lifecycle artifacts."""

from __future__ import annotations

import json

import click

from tools.cli.core.context import client_from_config
from tools.cli.core.errors import friendly_errors
from tools.cli.http import HttpClientError
from tools.cli.job_orders_display import print_group_detail, print_group_rows


@click.command("orders")
@click.argument("job_id")
@click.option("--strategy", default="", help="只显示指定策略。")
@click.option("--json", "as_json", is_flag=True, help="输出机器可读 JSON。")
@friendly_errors
def job_orders(job_id: str, strategy: str, as_json: bool) -> None:
    """List compact OrderGroup lifecycle summaries."""
    artifact = load_order_audit(job_id)
    rows = group_rows(artifact, strategy)
    if as_json:
        click.echo(json_text({"job_id": job_id, "groups": rows}))
        return
    print_group_rows(rows)


@click.command("order")
@click.argument("job_id")
@click.argument("order_group_id")
@click.option("--order-id", default="", help="只展开一个原子 Order。")
@click.option("--json", "as_json", is_flag=True, help="输出机器可读 JSON。")
@friendly_errors
def job_order(
    job_id: str, order_group_id: str, order_id: str, as_json: bool,
) -> None:
    """Expand Orders, attempts, Fills, settlements, and actions."""
    artifact = load_order_audit(job_id)
    payload = group_detail(artifact, order_group_id, order_id)
    if as_json:
        click.echo(json_text({"job_id": job_id, **payload}))
        return
    print_group_detail(payload)


def register_job_order_commands(job_group) -> None:
    job_group.add_command(job_orders)
    job_group.add_command(job_order)


def load_order_audit(job_id: str) -> dict:
    try:
        return client_from_config().job_order_audit(job_id)
    except HttpClientError as exc:
        if exc.status == 404:
            raise click.ClickException(
                "任务没有保留 order_audit；请用 --retain-full 重新提交回测。"
            ) from exc
        raise


def group_rows(artifact: dict, strategy_filter: str = "") -> list[dict]:
    rows = []
    for strategy_id, audit in sorted((artifact.get("strategies") or {}).items()):
        if strategy_filter and strategy_id != strategy_filter:
            continue
        for group in audit.get("groups") or []:
            rows.append({"strategy_id": strategy_id, **group})
    return rows


def group_detail(artifact: dict, group_id: str, order_id: str = "") -> dict:
    matches = []
    for strategy_id, audit in (artifact.get("strategies") or {}).items():
        group = next((
            row for row in audit.get("groups") or []
            if row.get("order_group_id") == group_id
        ), None)
        if group is not None:
            matches.append((strategy_id, audit, group))
    if len(matches) != 1:
        raise click.ClickException(
            f"order_group_id {group_id!r} {'不存在' if not matches else '不唯一'}"
        )
    strategy_id, audit, group = matches[0]
    order_ids = set(group.get("child_order_ids") or [])
    if order_id:
        if order_id not in order_ids:
            raise click.ClickException(f"Order {order_id!r} 不属于该 OrderGroup")
        order_ids = {order_id}
    fills = [
        row for row in audit.get("fills") or []
        if row.get("order_id") in order_ids
    ]
    fill_ids = {row.get("fill_id") for row in fills}
    return {
        "strategy_id": strategy_id,
        "group": group,
        "orders": filter_rows(audit, "orders", order_ids),
        "attempts": filter_rows(audit, "attempts", order_ids),
        "fills": fills,
        "settlements": [
            row for row in audit.get("settlements") or []
            if row.get("fill_id") in fill_ids
        ],
        "actions": filter_rows(audit, "actions", order_ids),
    }


def filter_rows(audit: dict, key: str, order_ids: set[str]) -> list[dict]:
    return [
        row for row in audit.get(key) or []
        if row.get("order_id") in order_ids
    ]


def json_text(value) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)
