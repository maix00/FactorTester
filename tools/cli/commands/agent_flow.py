"""Research Agent resume commands."""

from __future__ import annotations

import json

import click

from tools.cli.commands.agent_resume import resume_local_agent
from tools.cli.core.context import client_from_config


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)


@click.group("flow")
def agent_flow() -> None:
    """获取研究 Agent 的恢复包。"""


agent_flow.add_command(resume_local_agent)


@agent_flow.command("resume")
@click.argument("agent_id")
@click.option(
    "--role",
    type=click.Choice([
        "planning",
        "research",
    ]),
    required=True,
)
@click.option("--workspace-id", default="")
def resume_agent(
    agent_id: str,
    role: str,
    workspace_id: str,
) -> None:
    """获取一个无需模型组装的角色化小型启动/恢复包。"""
    if not workspace_id:
        raise click.ClickException(f"{role} 需要 --workspace-id")
    click.echo(_json(client_from_config().resume_agent(
        agent_id,
        role=role,
        workspace_id=workspace_id,
    )))
