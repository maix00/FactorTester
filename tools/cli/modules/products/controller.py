"""Products home-module CLI controller."""

from __future__ import annotations

import json
from typing import Any

import click

from tools.cli.core.context import client_from_config, ensure_child_available
from tools.cli.core.display import module_lines
from tools.cli.core.errors import friendly_errors
from tools.cli.table import render_table


@click.group("products", invoke_without_command=True)
@click.pass_context
@friendly_errors
def products(ctx: click.Context) -> None:
    """Enter products module."""
    if ctx.invoked_subcommand is None:
        ensure_child_available(None, "products")
        click.echo("产品管理")
        click.echo("下一层: factortester products list")
        click.echo("可用功能: factortester products info <产品>；factortester products product-groups list|add")


@products.command("list")
@friendly_errors
def list_products_children() -> None:
    """List product module children."""
    click.echo("当前位置: products")
    for line in module_lines(client_from_config().list_modules(parent="products")):
        click.echo(line)


@products.command("info")
@click.argument("name")
@click.option("--field", "fields", multiple=True, help="只显示指定字段，可重复传入。")
@click.option("--notes/--no-notes", default=True, help="是否显示后端注册的字段注释。")
@friendly_errors
def product_info(name: str, fields: tuple[str, ...], notes: bool) -> None:
    """查看产品的后端信息、交易规格与清算/交易规则注释。"""
    data = client_from_config().product_fields(name)
    field_map = data.get("fields") or {}
    if not isinstance(field_map, dict):
        raise ValueError("服务器 product fields 响应格式错误")
    selected = {str(item) for item in fields if str(item).strip()}
    rows = []
    for key in sorted(field_map, key=_product_field_sort_key):
        if selected and key not in selected:
            continue
        entry = field_map.get(key) or {}
        if not isinstance(entry, dict):
            continue
        label = str(entry.get("label") or key)
        value = _format_field_value(entry.get("value"))
        type_name = str(entry.get("type") or "")
        source = str(entry.get("source") or "")
        note_parts = []
        if source:
            note_parts.append(source)
        if notes:
            note = str(entry.get("note") or "")
            source_note = str(entry.get("source_note") or "")
            if note:
                note_parts.append(note)
            if source_note:
                note_parts.append(source_note)
        rows.append((label, key, value, type_name, "；".join(note_parts)))
    if selected and not rows:
        raise ValueError(f"未找到字段: {', '.join(sorted(selected))}")
    click.echo(f"产品后端信息: {data.get('name') or name}")
    for line in render_table(
        ("字段", "key", "值", "类型", "注释"),
        rows,
        max_widths=(18, 28, 36, 12, None),
    ):
        click.echo(line)


@products.command("availability")
@click.option(
    "--product",
    "product_names",
    multiple=True,
    required=True,
    help="用户已确认研究范围内的产品，可重复传入。",
)
@click.option(
    "--source",
    "source_names",
    multiple=True,
    default=("Local",),
    show_default=True,
    help="要检查的数据源，可重复传入。",
)
@click.option(
    "--probe",
    is_flag=True,
    help="允许执行显式网络/实时探针；默认只做低成本静态检查。",
)
@click.option(
    "--expanded",
    is_flag=True,
    help="返回逐产品详细信息；默认输出紧凑结果。",
)
@click.option("--json", "json_output", is_flag=True, help="输出机器可读 JSON。")
@friendly_errors
def product_availability(
    product_names: tuple[str, ...],
    source_names: tuple[str, ...],
    probe: bool,
    expanded: bool,
    json_output: bool,
) -> None:
    """检查明确产品范围内的历史、延迟、仿真或实时数据可用性。"""
    profile = client_from_config().data_availability(
        products=product_names,
        sources=source_names,
        probe=probe,
        expanded=expanded,
    )
    if json_output:
        click.echo(json.dumps(profile, ensure_ascii=False, sort_keys=True))
        return
    click.echo(f"数据可用性: {profile.get('profile_hash', '')}")
    rows = []
    for entry in profile.get("entries") or []:
        coverage = entry.get("coverage") or {}
        rows.append((
            entry.get("product", ""),
            entry.get("source", ""),
            entry.get("mode", ""),
            entry.get("frequency", ""),
            entry.get("status", ""),
            coverage.get("start", ""),
            coverage.get("end", ""),
            entry.get("latency_class", ""),
        ))
    for line in render_table(
        ("产品", "数据源", "模式", "频率", "状态", "起始", "结束", "延迟"),
        rows,
        max_widths=(20, 28, 20, 10, 14, 22, 22, 18),
    ):
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


def _product_field_sort_key(key: str) -> tuple[int, str]:
    order = {
        "class": 0,
        "name": 1,
        "alias": 2,
        "desc": 3,
        "timezone": 4,
        "is_margin_traded": 5,
        "MoneyCalculationPolicy": 20,
        "trading_spec_source": 30,
        "point_value": 31,
        "min_tick": 32,
        "min_trade_quantity": 33,
        "max_trade_quantity": 34,
        "open_fee_ratio": 40,
        "open_fee_fixed": 41,
        "close_fee_ratio": 42,
        "close_fee_fixed": 43,
        "close_today_fee_ratio": 44,
        "close_today_fee_fixed": 45,
        "long_margin_ratio": 50,
        "short_margin_ratio": 51,
    }
    return (order.get(key, 100), key)


def _format_field_value(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, (str, int, float, bool)):
        return str(value)
    try:
        import json

        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    except Exception:
        return str(value)
