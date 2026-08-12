"""Batch product-liquidity CLI command."""

from __future__ import annotations

import click

from tools.cli.core.context import client_from_config
from tools.cli.core.errors import friendly_errors
from tools.cli.core.json_output import echo_json
from tools.cli.table import render_table


@click.command("liquidity")
@click.option(
    "--product",
    "product_names",
    multiple=True,
    required=True,
    help="要独立筛选的产品，可重复传入；服务器一次批量处理。",
)
@click.option(
    "--source",
    default="LocalCNFuturesDAY1",
    show_default=True,
    help="提供 DAY1 VOLUME 的精确数据源 key。",
)
@click.option(
    "--as-of",
    required=True,
    help="统计截止日 YYYY-MM-DD；必须显式给出以避免使用未来数据。",
)
@click.option(
    "--window-days",
    type=click.IntRange(min=1),
    default=365,
    show_default=True,
    help="截止日前（含截止日）的日历日窗口。",
)
@click.option("--json", "json_output", is_flag=True, help="输出可记录为证据的 JSON。")
@click.option(
    "--compact-json",
    is_flag=True,
    help="输出单行紧凑 JSON；默认 --json 使用换行和两空格缩进。",
)
@friendly_errors
def product_liquidity(
    product_names: tuple[str, ...],
    source: str,
    as_of: str,
    window_days: int,
    json_output: bool,
    compact_json: bool,
) -> None:
    """基于显式截止日之前的 DAY1 VOLUME 批量计算流动性证据。"""
    evidence = client_from_config().product_liquidity(
        products=product_names,
        source=source,
        as_of=as_of,
        window_days=window_days,
    )
    if json_output or compact_json:
        echo_json(evidence, compact=compact_json)
        return
    click.echo(
        f"产品流动性证据: {evidence.get('evidence_hash', '')} "
        f"(as-of {evidence.get('as_of', as_of)})"
    )
    rows = []
    for entry in evidence.get("entries") or []:
        coverage = entry.get("coverage") or {}
        rows.append((
            entry.get("product", ""),
            entry.get("status", ""),
            entry.get("statistics_as_of", ""),
            entry.get("latest_daily_volume", ""),
            entry.get("average_daily_volume", ""),
            entry.get("zero_volume_days", ""),
            coverage.get("start", ""),
            coverage.get("end", ""),
            coverage.get("observed_days", ""),
            entry.get("gap_reason", ""),
        ))
    for line in render_table(
        (
            "产品",
            "状态",
            "数据截至",
            "最新日成交量",
            "日均成交量",
            "零成交日",
            "覆盖起始",
            "覆盖结束",
            "观测日",
            "缺口",
        ),
        rows,
        max_widths=(18, 16, 12, 16, 16, 10, 12, 12, 10, None),
    ):
        click.echo(line)
