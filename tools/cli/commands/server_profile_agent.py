"""Operate one Manager-owned server Profile Agent."""

from __future__ import annotations

import json
from dataclasses import dataclass

import click

from tools.cli.agent_auth import load_capability
from tools.cli.core.context import client_from_config
from tools.cli.core.errors import friendly_errors


@dataclass(frozen=True, slots=True)
class _ProfileAgentTarget:
    profile_id: str


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)


def _target(profile_id: str) -> _ProfileAgentTarget:
    requested = str(profile_id or "").strip()
    capability = load_capability()
    if capability is not None:
        if requested and requested != capability.profile_id:
            raise click.ClickException(
                "the active capability is signed for another Profile"
            )
        return _ProfileAgentTarget(capability.profile_id)
    if not requested:
        raise click.ClickException(
            "--profile-id is required outside a server Profile Agent runtime"
        )
    return _ProfileAgentTarget(requested)


@click.group("profile")
@click.option(
    "--profile-id",
    default="",
    help="当前 Manager 托管的服务器研究身份；Agent 内部可由能力文件确定。",
)
@click.pass_context
def profile_agent(context: click.Context, profile_id: str) -> None:
    """Inspect and control one Profile Agent hosted by this Manager."""
    context.obj = _target(profile_id)


@profile_agent.command("status")
@click.option("--json", "as_json", is_flag=True)
@click.pass_obj
@friendly_errors
def profile_agent_status(target: _ProfileAgentTarget, as_json: bool) -> None:
    value = client_from_config().profile_agent_status(target.profile_id)
    if as_json:
        click.echo(_json(value))
        return
    status = value.get("status") or {}
    click.echo(
        f"Profile {target.profile_id}: "
        f"running={bool(status.get('running'))} "
        f"ready={bool(status.get('ready'))}"
    )


@profile_agent.command("models")
@click.option("--refresh", is_flag=True, help="跳过短期模型目录缓存。")
@click.option("--json", "as_json", is_flag=True)
@click.pass_obj
@friendly_errors
def profile_agent_models(
    target: _ProfileAgentTarget,
    refresh: bool,
    as_json: bool,
) -> None:
    value = client_from_config().list_profile_agent_models(
        target.profile_id, refresh=refresh,
    )
    if as_json:
        click.echo(_json(value))
        return
    for item in value.get("models") or []:
        click.echo(str(item.get("id") or ""))


@profile_agent.command("start")
@click.option("--json", "as_json", is_flag=True)
@click.pass_obj
@friendly_errors
def profile_agent_start(target: _ProfileAgentTarget, as_json: bool) -> None:
    value = client_from_config().start_profile_agent(target.profile_id)
    click.echo(_json(value) if as_json else f"Profile {target.profile_id}: started")


@profile_agent.command("stop")
@click.option("--json", "as_json", is_flag=True)
@click.pass_obj
@friendly_errors
def profile_agent_stop(target: _ProfileAgentTarget, as_json: bool) -> None:
    value = client_from_config().stop_profile_agent(target.profile_id)
    click.echo(_json(value) if as_json else f"Profile {target.profile_id}: stopped")


@profile_agent.group("conversation")
def profile_agent_conversation() -> None:
    """List conversations and update one conversation's runtime settings."""


@profile_agent_conversation.command("list")
@click.option("--json", "as_json", is_flag=True)
@click.pass_obj
@friendly_errors
def profile_agent_conversation_list(
    target: _ProfileAgentTarget,
    as_json: bool,
) -> None:
    value = client_from_config().list_profile_agent_conversations(
        target.profile_id,
    )
    if as_json:
        click.echo(_json(value))
        return
    for item in value.get("conversations") or []:
        click.echo(
            f"{item.get('conversation_id') or ''}\t"
            f"{item.get('title') or item.get('preview') or ''}"
        )


@profile_agent_conversation.command("settings")
@click.argument("conversation_id")
@click.option("--model", "model_id", required=True)
@click.option("--effort", "reasoning_effort", default="")
@click.option("--service-tier", default="")
@click.option("--json", "as_json", is_flag=True)
@click.pass_obj
@friendly_errors
def profile_agent_conversation_settings(
    target: _ProfileAgentTarget,
    conversation_id: str,
    model_id: str,
    reasoning_effort: str,
    service_tier: str,
    as_json: bool,
) -> None:
    value = client_from_config().update_profile_agent_conversation_settings(
        target.profile_id,
        conversation_id,
        model_id=model_id,
        reasoning_effort=reasoning_effort,
        service_tier=service_tier,
    )
    click.echo(
        _json(value)
        if as_json
        else f"Conversation {conversation_id}: settings updated"
    )
