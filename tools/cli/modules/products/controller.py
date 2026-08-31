"""Products home-module CLI controller."""

from __future__ import annotations

from typing import Any

import click

from tools.cli.core.context import client_from_config, ensure_child_available
from tools.cli.core.errors import friendly_errors
from tools.cli.core.json_output import echo_json, json_text
from tools.cli.table import render_table

from .liquidity import product_liquidity


@click.group("product-library", invoke_without_command=True)
@click.pass_context
@friendly_errors
def product_library(ctx: click.Context) -> None:
    """Enter products module."""
    if ctx.invoked_subcommand is None:
        ensure_child_available(None, "products")
        click.echo("产品库")
        click.echo("下一层: factortester product-library list")
        click.echo(
            "可用功能: factortester product-library info <产品>；"
            "factortester product-library groups list|add|subjects"
        )


@product_library.command("info")
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
        max_widths=(24, 32, 56, 24, 96),
        wraps=(True, True, True, True, True),
    ):
        click.echo(line)


@product_library.command("availability")
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
    "--frequency",
    "frequencies",
    multiple=True,
    default=("MIN1",),
    show_default=True,
    help="实际读取的底层行情频率，可重复传入；DAY1 信号通常使用 MIN1。",
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
@click.option("--field", "fields", multiple=True, help="因子或 TrialPlan 依赖的数据字段，可重复传入。")
@click.option("--field-catalog", is_flag=True, help="列出数据源实际提供和可派生的全部行情字段。")
@click.option("--historical-fields", is_flag=True, help="汇总保证金、手续费、乘数等历史字段覆盖。")
@click.option("--json", "json_output", is_flag=True, help="输出机器可读 JSON。")
@click.option(
    "--compact-json",
    is_flag=True,
    help="输出单行紧凑 JSON；默认 --json 使用换行和两空格缩进。",
)
@friendly_errors
def product_availability(
    product_names: tuple[str, ...],
    source_names: tuple[str, ...],
    frequencies: tuple[str, ...],
    probe: bool,
    expanded: bool,
    fields: tuple[str, ...],
    field_catalog: bool,
    historical_fields: bool,
    json_output: bool,
    compact_json: bool,
) -> None:
    """检查明确产品范围内的历史、延迟、仿真或实时数据可用性。"""
    profile = client_from_config().data_availability(
        products=product_names,
        sources=source_names,
        frequencies=frequencies,
        probe=probe,
        expanded=expanded,
        fields=fields,
        include_field_catalog=field_catalog,
        include_historical_fields=historical_fields,
    )
    if json_output or compact_json:
        echo_json(profile, compact=compact_json)
        return
    click.echo(
        f"数据可用性 ({profile.get('inspection_runtime', 'server')}): "
        f"{profile.get('profile_hash', '')}"
    )
    rows = []
    for entry in profile.get("entries") or []:
        coverage = entry.get("coverage") or {}
        rows.append((
            entry.get("product", ""),
            entry.get("source", ""),
            entry.get("delivery_mode", ""),
            entry.get("sampling_mode", ""),
            entry.get("frequency") or "",
            entry.get("data_kind", ""),
            entry.get("market_depth", ""),
            entry.get("status", ""),
            coverage.get("start", ""),
            coverage.get("end", ""),
            entry.get("latency_class", ""),
        ))
    for line in render_table(
        (
            "产品",
            "数据源",
            "交付",
            "采样",
            "时间频率",
            "内容",
            "深度",
            "状态",
            "起始",
            "结束",
            "延迟",
        ),
        rows,
        max_widths=(18, 24, 18, 10, 10, 14, 14, 14, 22, 22, 18),
    ):
        click.echo(line)
    required_rows = []
    for entry in profile.get("entries") or []:
        for field in entry.get("required_fields") or []:
            required_rows.append((
                entry.get("product", ""), entry.get("source", ""),
                field.get("field", ""), field.get("status", ""),
                ", ".join(field.get("physical_fields") or []),
                field.get("limitation", ""),
            ))
    if required_rows:
        click.echo("\n依赖字段")
        for line in render_table(
            ("产品", "数据源", "逻辑字段", "状态", "物理字段", "限制"),
            required_rows,
            max_widths=(18, 24, 22, 20, 42, None),
        ):
            click.echo(line)
    catalog_rows = []
    for entry in profile.get("entries") or []:
        for field in entry.get("field_catalog") or []:
            catalog_rows.append((
                entry.get("product", ""), entry.get("source", ""),
                field.get("field", ""), field.get("status", ""),
                ", ".join(field.get("physical_fields") or []),
                field.get("data_type", ""),
            ))
    if catalog_rows:
        click.echo("\n行情字段目录")
        for line in render_table(
            ("产品", "数据源", "逻辑字段", "状态", "物理字段", "类型"),
            catalog_rows,
            max_widths=(18, 24, 22, 20, 42, 18),
        ):
            click.echo(line)
    history_rows = [
        (
            item.get("product", ""), item.get("field", ""),
            item.get("coverage_start", ""), item.get("coverage_end", ""),
            item.get("record_count", 0),
            f"{', '.join(item.get('providers') or [])} ({item.get('source_count', 0)} sources)",
        )
        for item in profile.get("historical_fields") or []
    ]
    if history_rows:
        click.echo("\n历史交易规则字段")
        for line in render_table(
            ("产品", "字段", "最早", "最晚", "记录数", "提供者"),
            history_rows,
            max_widths=(18, 30, 12, 12, 8, None),
        ):
            click.echo(line)


@product_library.command("capabilities")
@click.option("--json", "json_output", is_flag=True)
@click.option(
    "--compact-json",
    is_flag=True,
    help="输出单行紧凑 JSON；默认 --json 使用换行和两空格缩进。",
)
@friendly_errors
def product_capabilities(json_output: bool, compact_json: bool) -> None:
    """读取服务器已声明的数据源与已冻结覆盖，不触发数据扫描。"""
    catalog = client_from_config().data_capabilities()
    if json_output or compact_json:
        echo_json(catalog, compact=compact_json)
        return
    click.echo("数据源")
    rows = [
        (
            item.get("source", ""), item.get("frequency") or "",
            ", ".join(item.get("fields") or []),
            item.get("inspection_runtime", ""),
        )
        for item in catalog.get("sources") or []
    ]
    for line in render_table(
        ("数据源", "频率", "字段", "检查位置"), rows,
        max_widths=(30, 10, 60, 12),
    ):
        click.echo(line)
    snapshots = catalog.get("snapshots") or []
    if snapshots:
        click.echo("\n已冻结覆盖快照")
        for line in render_table(
            ("快照", "时间", "条目", "范围"),
            [
                (
                    item.get("profile_ref", ""), item.get("as_of", ""),
                    item.get("entry_count", 0),
                    ", ".join((item.get("request") or {}).get("products") or []),
                )
                for item in snapshots
            ],
            max_widths=(76, 28, 8, None),
        ):
            click.echo(line)


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
        return json_text(value, compact=True)
    except Exception:
        return str(value)


product_library.add_command(product_liquidity)
