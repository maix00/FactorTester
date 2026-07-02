"""Products home-module CLI controller."""

from __future__ import annotations

from typing import Any

import click

from tools.cli.core.context import client_from_config, ensure_child_available
from tools.cli.core.display import module_lines
from tools.cli.core.errors import friendly_errors


@click.group("products", invoke_without_command=True)
@click.pass_context
@friendly_errors
def products(ctx: click.Context) -> None:
    """Enter products module."""
    if ctx.invoked_subcommand is None:
        ensure_child_available(None, "products")
        click.echo("产品管理")
        click.echo("下一层: factortester products list")
        click.echo("可用功能: factortester products product-groups list|add")


@products.command("list")
@friendly_errors
def list_products_children() -> None:
    """List product module children."""
    click.echo("当前位置: products")
    for line in module_lines(client_from_config().list_modules(parent="products")):
        click.echo(line)


@products.group("product-groups", invoke_without_command=True)
@click.pass_context
@friendly_errors
def product_groups(ctx: click.Context) -> None:
    """Manage saved product groups."""
    if ctx.invoked_subcommand is None:
        ctx.invoke(list_product_groups)


@product_groups.command("list")
@friendly_errors
def list_product_groups() -> None:
    """List saved product groups from the existing SQL store."""
    groups = client_from_config().list_candidates("product_path_candidates")
    if not groups:
        click.echo("暂无产品组")
        return
    for group in groups:
        click.echo(product_group_line(group))


@product_groups.command("add")
@click.option("--name", required=True, help="产品组名称。")
@click.option("--path", "paths", multiple=True, required=True, help="产品路径，可重复传入。")
@friendly_errors
def add_product_group(name: str, paths: tuple[str, ...]) -> None:
    """Create a saved product group in the existing SQL store."""
    group = (client_from_config().create_product_group(name=name, paths=list(paths)).get("group") or {})
    click.echo("已新增产品组")
    click.echo(product_group_line(group))


def product_group_line(group: dict[str, Any]) -> str:
    name = group.get("name") or group.get("label") or group.get("id")
    group_id = group.get("id") or group.get("product_path_selection_id") or ""
    path_count = group.get("path_count")
    product_count = group.get("product_count")
    parts = [str(name)]
    if group_id:
        parts.append(str(group_id))
    if path_count is not None:
        parts.append(f"{path_count} 路径")
    if product_count is not None:
        parts.append(f"{product_count} 产品")
    return " · ".join(parts)


def product_group_selection(group: dict[str, Any]) -> dict[str, Any]:
    group_id = str(group.get("id") or group.get("product_path_selection_id") or group.get("name") or "")
    selection = {
        "product_path_selection_id": group_id,
        "id": group_id,
        "label": group.get("name") or group.get("label") or group_id,
        "product_group": group.get("name") or group.get("product_group") or "",
        "product_group_template_id": group_id,
        "source_type": "user_product_group_template",
    }
    paths = group.get("paths") or group.get("selected_paths")
    if isinstance(paths, list):
        selection["paths"] = list(paths)
        selection["selected_paths"] = list(paths)
    return selection
