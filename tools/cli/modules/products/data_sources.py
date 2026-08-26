"""Server-backed data-source catalog commands."""

from __future__ import annotations

import json

import click

from tools.cli.core.context import client_from_config
from tools.cli.core.errors import friendly_errors
from tools.cli.table import render_table


@click.group("sources", invoke_without_command=True)
@click.pass_context
def product_sources(ctx: click.Context) -> None:
    """浏览与 Web/Swift 相同的服务器数据源目录。"""
    if ctx.invoked_subcommand is None:
        ctx.invoke(list_product_sources)


@product_sources.command("list")
@click.option("--query", default="", help="筛选当前可见的数据源。")
@click.option("--json", "as_json", is_flag=True, help="输出机器可读 JSON。")
@friendly_errors
def list_product_sources(query: str, as_json: bool) -> None:
    payload = client_from_config().product_source_catalog()
    needle = query.strip().casefold()
    raw = payload.get("sources") or payload.get("items") or []
    items = [
        dict(item) for item in raw
        if isinstance(item, dict)
        and (
            not needle
            or any(
                needle in str(value or "").casefold()
                for value in item.values()
                if isinstance(value, (str, int, float))
            )
        )
    ]
    value = {
        "schema_version": 1,
        "object_type": "data_source",
        "query": query,
        "count": len(items),
        "items": items,
    }
    if as_json:
        click.echo(json.dumps(value, ensure_ascii=False, indent=2))
        return
    if not items:
        click.echo("暂无符合条件的数据源")
        return
    rows = [(
        item.get("display_name") or item.get("name")
        or item.get("source") or item.get("source_id") or item.get("id") or "",
        item.get("frequency") or item.get("data_frequency") or "",
        item.get("delivery_mode") or item.get("runtime_kind") or "",
        item.get("description") or "",
    ) for item in items]
    for line in render_table(
        ("数据源", "频率", "交付方式", "说明"), rows,
        max_widths=(36, 16, 20, 56),
    ):
        click.echo(line)
