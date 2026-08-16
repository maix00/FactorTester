"""CLI management for account-owned product categories."""

from __future__ import annotations

import json
from collections import OrderedDict
from typing import Any

import click

from tools.cli.core.context import client_from_config
from tools.cli.core.errors import friendly_errors
from tools.cli.core.json_output import echo_json
from tools.cli.table import render_table


@click.group("categories", invoke_without_command=True)
@click.pass_context
@friendly_errors
def product_categories(ctx: click.Context) -> None:
    """Manage user-owned product categories on the connected Manager."""
    if ctx.invoked_subcommand is None:
        ctx.invoke(list_product_categories)


@product_categories.command("list")
@click.option("--json", "json_output", is_flag=True, help="输出机器可读 JSON。")
@friendly_errors
def list_product_categories(json_output: bool = False) -> None:
    """List source and current-user product categories."""
    value = client_from_config().list_product_categories()
    if json_output:
        echo_json(value)
        return
    categories = value.get("categories") or []
    if not categories:
        click.echo("暂无产品分类")
        return
    rows = []
    for category in categories:
        rows.append((
            str(category.get("id") or ""),
            str(category.get("title_zh") or category.get("alias") or ""),
            "系统" if category.get("source_managed") else "用户",
            "乘积分类" if category.get("is_composite") else "普通分类",
            sum(len(item.get("paths") or []) for item in category.get("items") or []),
        ))
    for line in render_table(
        ("ID", "名称", "所有者", "类型", "路径数"),
        rows,
        max_widths=(40, 32, 10, 12, 10),
    ):
        click.echo(line)


@product_categories.command("add")
@click.option("--name", required=True, help="产品分类名称。")
@click.option(
    "--item",
    "item_specs",
    multiple=True,
    help="分类条目，格式为 LABEL=PATH；同一 LABEL 可重复传入多个路径。",
)
@click.option(
    "--items-json",
    default="",
    help="条目 JSON 数组，例如 [{\"label\":\"日盘\",\"paths\":[\"...\"]}]。",
)
@click.option("--json", "json_output", is_flag=True, help="输出机器可读 JSON。")
@friendly_errors
def add_product_category(
    name: str,
    item_specs: tuple[str, ...],
    items_json: str,
    json_output: bool,
) -> None:
    """Create a user-owned category from canonical product paths."""
    items = _parse_items(item_specs, items_json)
    value = client_from_config().create_product_category(name=name, items=items)
    if json_output:
        echo_json(value)
        return
    category = value.get("category") or {}
    click.echo(
        "已新增产品分类: "
        f"{category.get('title_zh') or name} ({category.get('id') or '—'})"
    )


@product_categories.command("add-composite")
@click.option(
    "--category-id",
    "category_ids",
    multiple=True,
    required=True,
    help="参与乘积的分类 ID；当前要求正好两个，可重复传入。",
)
@click.option("--json", "json_output", is_flag=True, help="输出机器可读 JSON。")
@friendly_errors
def add_composite_product_category(
    category_ids: tuple[str, ...],
    json_output: bool,
) -> None:
    """Create a registered product-category composition."""
    value = client_from_config().create_product_category_composite(
        category_ids=list(category_ids),
    )
    if json_output:
        echo_json(value)
        return
    category = value.get("category") or {}
    click.echo(
        "已新增乘积分类: "
        f"{category.get('title_zh') or category.get('id') or '—'}"
    )


@product_categories.command("delete")
@click.argument("category_id")
@click.option("--yes", is_flag=True, help="确认删除；避免误删时必须显式提供。")
@click.option("--json", "json_output", is_flag=True, help="输出机器可读 JSON。")
@friendly_errors
def delete_product_category(
    category_id: str,
    yes: bool,
    json_output: bool,
) -> None:
    """Delete one user-owned category by ID."""
    if not yes:
        raise click.UsageError("删除产品分类需要显式传入 --yes")
    value = client_from_config().delete_product_category(category_id)
    if json_output:
        echo_json(value)
        return
    click.echo(f"已删除产品分类: {category_id}")


def _parse_items(
    item_specs: tuple[str, ...],
    items_json: str,
) -> list[dict[str, Any]]:
    if item_specs and items_json.strip():
        raise click.UsageError("--item 与 --items-json 不能同时使用")
    if items_json.strip():
        try:
            value = json.loads(items_json)
        except json.JSONDecodeError as exc:
            raise click.UsageError(f"--items-json 不是有效 JSON: {exc}") from exc
        if not isinstance(value, list):
            raise click.UsageError("--items-json 必须是 JSON 数组")
        return value
    if not item_specs:
        raise click.UsageError("至少提供一个 --item 或 --items-json")

    grouped: OrderedDict[str, list[str]] = OrderedDict()
    for spec in item_specs:
        label, separator, path = spec.partition("=")
        label, path = label.strip(), path.strip()
        if not separator or not label or not path:
            raise click.UsageError("--item 格式必须是 LABEL=PATH")
        grouped.setdefault(label, []).append(path)
    return [
        {"label": label, "paths": paths}
        for label, paths in grouped.items()
    ]
