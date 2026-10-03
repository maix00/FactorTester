"""One CLI hierarchy for the Research module shown by Web and Swift."""

from __future__ import annotations

import json

import click

from tools.cli.commands.research_catalog import register_research_catalog_commands
from tools.cli.commands.research_evidence import research_evidence
from tools.cli.commands.research_report import report
from tools.cli.core.context import client_from_config
from tools.cli.core.errors import friendly_errors
from tools.cli.table import render_table


@click.command("list")
@click.option(
    "--scope",
    type=click.Choice(("all", "mine", "subordinates", "shared")),
    default="mine",
    show_default=True,
)
@click.option("--query", default="", help="筛选当前可见的研究报告。")
@click.option("--json", "as_json", is_flag=True, help="输出机器可读 JSON。")
@friendly_errors
def list_research_reports(scope: str, query: str, as_json: bool) -> None:
    """列出与 Web/Swift 相同权限范围内的研究报告。"""
    payload = client_from_config().research_report_catalog(scope=scope)
    needle = query.strip().casefold()
    raw = payload.get("reports") or payload.get("items") or []
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
        "object_type": "research_report",
        "scope": scope,
        "query": query,
        "count": len(items),
        "items": items,
    }
    if as_json:
        click.echo(json.dumps(value, ensure_ascii=False, indent=2))
        return
    if not items:
        click.echo("暂无符合条件的研究报告")
        return
    rows = [(
        item.get("title") or item.get("name") or "",
        item.get("owner_ref") or item.get("owner_username") or "",
        item.get("profile_ref") or item.get("profile_id") or "",
        item.get("build_source") or "",
        item.get("sharing_state") or item.get("visibility") or "",
    ) for item in items]
    for line in render_table(
        ("研究报告", "用户", "Profile", "构建来源", "共享状态"), rows,
        max_widths=(48, 36, 32, 18, 18),
    ):
        click.echo(line)


@click.group("profiles", invoke_without_command=True)
@click.pass_context
def research_profiles(ctx: click.Context) -> None:
    """浏览研究身份目录及其客户端/服务器运行来源。"""
    if ctx.invoked_subcommand is None:
        ctx.invoke(list_research_profiles)


@research_profiles.command("list")
@click.option(
    "--scope",
    type=click.Choice(("mine", "subordinates", "servers")),
    default="mine",
    show_default=True,
)
@click.option("--query", default="", help="由 Manager 搜索研究身份。")
@click.option("--page", type=click.IntRange(min=1), default=1, show_default=True)
@click.option(
    "--page-size",
    type=click.IntRange(min=1, max=100),
    default=20,
    show_default=True,
)
@click.option("--json", "as_json", is_flag=True, help="输出机器可读 JSON。")
@friendly_errors
def list_research_profiles(
    scope: str,
    query: str,
    page: int,
    page_size: int,
    as_json: bool,
) -> None:
    payload = client_from_config().profile_directory(
        scope=scope, query=query, page=page, page_size=page_size,
    )
    items = payload.get("items") or payload.get("profiles") or []
    value = {
        "schema_version": 1,
        "object_type": "research_profile",
        "scope": scope,
        "query": query,
        "page": page,
        "page_size": page_size,
        "items": items,
        "next_cursor": payload.get("next_cursor"),
        "total": payload.get("total", len(items)),
    }
    if as_json:
        click.echo(json.dumps(value, ensure_ascii=False, indent=2))
        return
    if not items:
        click.echo("暂无符合条件的研究身份")
        return
    rows = []
    for item in items:
        runtime = item.get("runtime") if isinstance(item, dict) else {}
        runtime = runtime if isinstance(runtime, dict) else {}
        rows.append((
            item.get("display_name") or item.get("profile_id") or "",
            item.get("owner_alias") or item.get("owner_ref") or "",
            runtime.get("runtime_kind") or "",
            item.get("agent_status") or item.get("binding_status") or "",
            item.get("visibility") or "",
        ))
    for line in render_table(
        ("研究身份", "用户", "运行来源", "状态", "可见性"), rows,
        max_widths=(36, 36, 16, 18, 16),
    ):
        click.echo(line)


def register_research_domain(
    research: click.Group,
) -> None:
    """Attach all Research children without duplicating their implementations."""
    if "list" not in report.commands:
        report.add_command(list_research_reports)
    research.add_command(report, name="reports")
    research.add_command(research_evidence, name="evidence")
    research.add_command(research_profiles)
    register_research_catalog_commands(research)
