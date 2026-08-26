"""One CLI hierarchy for Agent models, flows, and Profile runtimes."""

from __future__ import annotations

import json
from pathlib import Path

import click

from tools.cli.commands.agent_flow import agent_flow
from tools.cli.commands.server_profile_agent import profile_agent
from tools.cli.core.context import client_from_config
from tools.cli.core.errors import friendly_errors
from tools.cli.table import render_table


@click.group("agents", invoke_without_command=True)
@click.pass_context
def agents(ctx: click.Context) -> None:
    """管理与 Web/Swift 相同的智能体模型、会话和 Profile 运行时。"""
    if ctx.invoked_subcommand is None:
        click.echo("智能体")
        click.echo("  models   模型提供者")
        click.echo("  profile  Profile Agent 运行时与会话")
        click.echo("  flow     研究 Agent 恢复包")


@agents.group("models", invoke_without_command=True)
@click.pass_context
def agent_models(ctx: click.Context) -> None:
    """管理当前用户的智能体模型提供者。"""
    if ctx.invoked_subcommand is None:
        ctx.invoke(list_agent_models)


@agent_models.command("list")
@click.option("--runtime-kind", type=click.Choice(("client", "server")))
@click.option("--json", "as_json", is_flag=True, help="输出机器可读 JSON。")
@friendly_errors
def list_agent_models(runtime_kind: str | None, as_json: bool) -> None:
    items = client_from_config().list_agent_models(runtime_kind=runtime_kind)
    value = {
        "schema_version": 1,
        "object_type": "agent_model",
        "runtime_kind": runtime_kind or "all",
        "count": len(items),
        "items": items,
    }
    if as_json:
        click.echo(json.dumps(value, ensure_ascii=False, indent=2))
        return
    if not items:
        click.echo("暂无智能体模型")
        return
    rows = [(
        item.get("display_name") or item.get("provider_id") or "",
        item.get("provider_kind") or "",
        item.get("runtime_kind") or "",
        item.get("model") or item.get("default_model") or "",
        "是" if item.get("enabled", True) else "否",
    ) for item in items]
    for line in render_table(
        ("模型配置", "提供者", "运行位置", "默认模型", "启用"), rows,
        max_widths=(36, 24, 16, 36, 8),
    ):
        click.echo(line)


@agent_models.command("save")
@click.option(
    "--file", "source", required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Web/Swift 使用的 provider JSON 对象。",
)
@click.option("--json", "as_json", is_flag=True, help="输出机器可读 JSON。")
@friendly_errors
def save_agent_model(source: Path, as_json: bool) -> None:
    value = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise click.UsageError("--file 必须包含一个 JSON 对象")
    saved = client_from_config().save_agent_model(value)
    if as_json:
        click.echo(json.dumps(saved, ensure_ascii=False, indent=2))
        return
    label = saved.get("display_name") or saved.get("provider_id") or ""
    click.echo(f"已保存智能体模型: {label}")


@agent_models.command("delete")
@click.argument("provider_id")
@click.option("--yes", is_flag=True, help="确认删除。")
@click.option("--json", "as_json", is_flag=True, help="输出机器可读 JSON。")
@friendly_errors
def delete_agent_model(provider_id: str, yes: bool, as_json: bool) -> None:
    if not yes:
        raise click.UsageError("删除智能体模型需要显式传入 --yes")
    deleted = client_from_config().delete_agent_model(provider_id)
    value = {"success": True, "provider_id": provider_id, "deleted": deleted}
    click.echo(
        json.dumps(value, ensure_ascii=False, indent=2)
        if as_json else f"已删除智能体模型: {provider_id}"
    )


agents.add_command(profile_agent, name="profile")
agents.add_command(agent_flow, name="flow")
