"""Canonical Agent Flow budget-period and invocation commands."""

from __future__ import annotations

import json
from pathlib import Path

import click

from tools.cli.commands.agent_resume import resume_local_agent
from tools.cli.core.context import client_from_config


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)


def _read_json_object(path: Path, *, label: str) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise click.ClickException(f"{label} must be a JSON object")
    return value


@click.group("agent-flow")
def agent_flow() -> None:
    """管理 Agent Budget Period 与 Agent Invocation 生命周期。"""


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
@click.option("--instance-id", default="")
@click.option("--branch-id", default="")
@click.option("--workspace-id", default="")
def resume_agent(
    agent_id: str,
    role: str,
    instance_id: str,
    branch_id: str,
    workspace_id: str,
) -> None:
    """获取一个无需模型组装的角色化小型启动/恢复包。"""
    if role == "research" and (not instance_id or not branch_id):
        raise click.ClickException(
            "research 需要 --instance-id 和 --branch-id"
        )
    if role == "planning" and not workspace_id:
        raise click.ClickException("planning 需要 --workspace-id")
    click.echo(_json(client_from_config().resume_agent(
        agent_id,
        role=role,
        instance_id=instance_id,
        branch_id=branch_id,
        workspace_id=workspace_id,
    )))


@agent_flow.group("budget")
def agent_budget() -> None:
    """读取、配置或重置一个 Agent 的当前预算周期。"""


@agent_budget.command("load")
@click.argument("agent_id")
def load_agent_budget(agent_id: str) -> None:
    """读取 AGENT_ID 的当前 AgentBudgetPeriod。"""
    click.echo(_json(
        client_from_config().load_agent_budget_period(agent_id)
    ))


@agent_budget.command("configure")
@click.argument("agent_id")
@click.option("--token-limit", type=click.IntRange(min=1), required=True)
def configure_agent_budget(agent_id: str, token_limit: int) -> None:
    """配置 AGENT_ID 当前预算周期的 token 上限。"""
    click.echo(_json(
        client_from_config().configure_agent_budget_period(
            agent_id,
            token_limit=token_limit,
        )
    ))


@agent_budget.command("reset")
@click.argument("agent_id")
@click.option("--token-limit", type=click.IntRange(min=1))
def reset_agent_budget(
    agent_id: str,
    token_limit: int | None,
) -> None:
    """保留历史并请求开启 AGENT_ID 的新预算周期。"""
    click.echo(_json(
        client_from_config().reset_agent_budget_period(
            agent_id,
            token_limit=token_limit,
        )
    ))


@agent_flow.group("invocation")
def agent_invocation() -> None:
    """预留、结算或释放一次真实 Agent 调用。"""


@agent_invocation.command("reserve")
@click.argument("agent_id")
@click.option("--sponsor-agent-id", default="")
@click.option(
    "--role",
    "actor_role",
    type=click.Choice([
        "researcher",
        "proposer",
        "reviewer",
        "audit_presenter",
        "skill",
    ]),
    required=True,
)
@click.option(
    "--authority-scope",
    type=click.Choice([
        "local_research",
        "server_research",
    ]),
    required=True,
)
@click.option("--task-ref", default="")
@click.option("--purpose", required=True)
@click.option("--runtime-id", required=True)
@click.option("--model-id", required=True)
@click.option("--max-input-tokens", type=click.IntRange(min=0), required=True)
@click.option("--max-output-tokens", type=click.IntRange(min=0), required=True)
@click.option("--agent-principal-hash", required=True)
@click.option("--lineage-hash", required=True)
@click.option("--input-hash", default="")
@click.option(
    "--context-cost-file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option("--idempotency-key", default="")
def reserve_agent_invocation(
    agent_id: str,
    sponsor_agent_id: str,
    actor_role: str,
    authority_scope: str,
    task_ref: str,
    purpose: str,
    runtime_id: str,
    model_id: str,
    max_input_tokens: int,
    max_output_tokens: int,
    agent_principal_hash: str,
    lineage_hash: str,
    input_hash: str,
    context_cost_file: Path | None,
    idempotency_key: str,
) -> None:
    """在 provider 调用前原子创建 reserved AgentInvocation。"""
    context_cost = (
        _read_json_object(context_cost_file, label="context cost")
        if context_cost_file is not None
        else {}
    )
    click.echo(_json(
        client_from_config().reserve_agent_invocation(
            agent_id=agent_id,
            sponsor_agent_id=sponsor_agent_id,
            actor_role=actor_role,
            authority_scope=authority_scope,
            task_ref=task_ref,
            purpose=purpose,
            runtime_id=runtime_id,
            model_id=model_id,
            max_input_tokens=max_input_tokens,
            max_output_tokens=max_output_tokens,
            agent_principal_hash=agent_principal_hash,
            lineage_hash=lineage_hash,
            input_hash=input_hash,
            context_cost=context_cost,
            idempotency_key=idempotency_key,
        )
    ))


@agent_invocation.command("settle")
@click.argument("invocation_id")
@click.option("--input-tokens", type=click.IntRange(min=0))
@click.option("--output-tokens", type=click.IntRange(min=0))
@click.option("--cache-read-tokens", type=click.IntRange(min=0), default=0)
@click.option("--provider-request-id", default="")
@click.option("--provider-attestation", default="")
@click.option(
    "--reserved-fallback",
    is_flag=True,
    help="Provider 未返回可信 token 用量时，按完整预留量结算。",
)
def settle_agent_invocation(
    invocation_id: str,
    input_tokens: int | None,
    output_tokens: int | None,
    cache_read_tokens: int,
    provider_request_id: str,
    provider_attestation: str,
    reserved_fallback: bool,
) -> None:
    """使用 provider-neutral usage 结算同一个 AgentInvocation。"""
    supplied_usage = input_tokens is not None or output_tokens is not None
    if reserved_fallback and supplied_usage:
        raise click.ClickException(
            "--reserved-fallback 不能与 --input-tokens/--output-tokens 同时使用"
        )
    if not reserved_fallback and (
        input_tokens is None or output_tokens is None
    ):
        raise click.ClickException(
            "必须同时提供 --input-tokens/--output-tokens；"
            "无可信 provider 用量时使用 --reserved-fallback"
        )
    if reserved_fallback and cache_read_tokens:
        raise click.ClickException(
            "--reserved-fallback 不接受 --cache-read-tokens"
        )
    click.echo(_json(
        client_from_config().settle_agent_invocation(
            invocation_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cache_read_tokens,
            provider_request_id=provider_request_id,
            provider_attestation=provider_attestation,
        )
    ))


@agent_invocation.command("release")
@click.argument("invocation_id")
def release_agent_invocation(invocation_id: str) -> None:
    """仅在 provider 调用未发生时释放完整预留。"""
    click.echo(_json(
        client_from_config().release_agent_invocation(invocation_id)
    ))
