"""Server-backed product catalog commands."""

from __future__ import annotations

import json
from typing import Any

import click

from tools.cli.core.context import client_from_config
from tools.cli.core.errors import friendly_errors
from tools.cli.table import render_table


def _matches(item: dict[str, Any], query: str) -> bool:
    needle = str(query or "").strip().casefold()
    return not needle or any(
        needle in str(value or "").casefold()
        for value in item.values()
        if isinstance(value, (str, int, float))
    )


@click.command("list")
@click.option("--query", default="", help="筛选当前可见的产品。")
@click.option("--json", "as_json", is_flag=True, help="输出机器可读 JSON。")
@friendly_errors
def product_catalog(query: str, as_json: bool) -> None:
    """列出与 Web/Swift 相同服务器目录中的产品。"""
    payload = client_from_config().product_catalog()
    raw = payload.get("products") or payload.get("items") or []
    items = [
        dict(item) for item in raw
        if isinstance(item, dict) and _matches(item, query)
    ]
    value = {
        "schema_version": 1,
        "object_type": "product",
        "query": query,
        "count": len(items),
        "items": items,
    }
    if as_json:
        click.echo(json.dumps(value, ensure_ascii=False, indent=2))
        return
    if not items:
        click.echo("暂无符合条件的产品")
        return
    rows = [(
        item.get("name") or item.get("product") or item.get("code") or "",
        item.get("description") or item.get("title_zh") or "",
        item.get("exchange") or "",
        item.get("source") or item.get("data_source") or "",
    ) for item in items]
    for line in render_table(
        ("产品", "名称", "交易所", "数据源"), rows,
        max_widths=(32, 36, 18, 36),
    ):
        click.echo(line)
