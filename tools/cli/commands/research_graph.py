"""Research Decision Graph inspection, evidence, audit, and activation."""

from __future__ import annotations

import json
from pathlib import Path

import click

from tools.cli.core.context import client_from_config
from tools.cli.capability_projection import server_capability_resolution


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)


@click.group("research-graph")
def research_graph() -> None:
    """管理产品无关、不可变且经审计激活的研究决策图。"""


@research_graph.command("publish")
@click.argument(
    "graph_file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
def publish_graph(graph_file: Path) -> None:
    """将 Observed 或 Draft Graph 发布为不可变服务器版本。"""
    graph = json.loads(graph_file.read_text(encoding="utf-8"))
    click.echo(_json(client_from_config().publish_research_graph(graph)))


@research_graph.command("versions")
@click.argument("graph_id")
def graph_versions(graph_id: str) -> None:
    """列出服务器端不可变图版本。"""
    click.echo(_json(
        client_from_config().list_research_graph_versions(graph_id)
    ))


@research_graph.command("active")
@click.argument("graph_id")
def active_graph(graph_id: str) -> None:
    """读取当前 Active Graph。"""
    click.echo(_json(client_from_config().get_active_research_graph(graph_id)))


@research_graph.command("validate")
@click.argument("graph_id")
@click.argument("version", type=int)
@click.option("--proposal-id", required=True)
@click.option("--routine-instance-id", required=True)
@click.option("--routine-branch-id", required=True)
@click.option("--baseline-run-id", required=True)
def validate_graph(
    graph_id: str,
    version: int,
    proposal_id: str,
    routine_instance_id: str,
    routine_branch_id: str,
    baseline_run_id: str,
) -> None:
    """让服务器从 canonical state 推导 replay、shadow 与 token 证据。"""
    evidence = {
        "shadow_comparison_refs": {
            "routine_instance_id": routine_instance_id,
            "routine_branch_id": routine_branch_id,
            "baseline_run_id": baseline_run_id,
        },
    }
    click.echo(_json(client_from_config().validate_research_graph(
        graph_id,
        version,
        evidence,
        proposal_id=proposal_id,
    )))


@research_graph.command("propose")
@click.argument("graph_id")
@click.argument("version", type=int)
@click.option("--risk-level", type=click.Choice(["L1", "L2", "L3", "L4"]), required=True)
@click.option(
    "--change-diff-file",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option("--evidence-ref", "evidence_refs", multiple=True)
@click.option("--token-estimate", type=click.IntRange(min=0), required=True)
@click.option("--agent-execution-id", required=True)
@click.option("--conversation-ref", required=True)
@click.option(
    "--pointer-action",
    type=click.Choice(["activate_graph", "rollback_graph_pointer"]),
    default="activate_graph",
)
@click.option("--pointer-from-version", type=click.IntRange(min=0), default=0)
@click.option("--pointer-reason", default="")
def propose_graph(
    graph_id: str,
    version: int,
    risk_level: str,
    change_diff_file: Path,
    evidence_refs: tuple[str, ...],
    token_estimate: int,
    agent_execution_id: str,
    conversation_ref: str,
    pointer_action: str,
    pointer_from_version: int,
    pointer_reason: str,
) -> None:
    """提交紧凑图变更 diff；不提交整张图或具体 Skill 身份。"""
    change_diff = json.loads(
        change_diff_file.read_text(encoding="utf-8")
    )
    if not isinstance(change_diff, dict):
        raise click.ClickException("change diff must be a JSON object")
    click.echo(_json(client_from_config().propose_research_graph(
        graph_id,
        version,
        risk_level=risk_level,
        change_diff=change_diff,
        evidence_refs=list(evidence_refs),
        token_estimate=token_estimate,
        agent_execution_id=agent_execution_id,
        conversation_ref=conversation_ref,
        pointer_action=pointer_action,
        pointer_from_version=pointer_from_version,
        pointer_reason=pointer_reason,
    )))


@research_graph.command("review")
@click.argument("proposal_id")
@click.option(
    "--disposition",
    type=click.Choice(["approved", "rejected", "disagreed"]),
    required=True,
)
@click.option("--scope-drift", is_flag=True)
@click.option("--semantic-uncertainty", is_flag=True)
@click.option("--evidence-ref", "evidence_refs", multiple=True)
@click.option("--agent-execution-id", required=True)
def review_graph_proposal(
    proposal_id: str,
    disposition: str,
    scope_drift: bool,
    semantic_uncertainty: bool,
    evidence_refs: tuple[str, ...],
    agent_execution_id: str,
) -> None:
    """记录最小数量的独立 reviewer 结论。"""
    click.echo(_json(
        client_from_config().review_research_graph_proposal(
            proposal_id,
            disposition=disposition,
            scope_drift=scope_drift,
            semantic_uncertainty=semantic_uncertainty,
            evidence_refs=list(evidence_refs),
            agent_execution_id=agent_execution_id,
        )
    ))


@research_graph.command("audit")
@click.argument("graph_id")
@click.argument("version", type=int)
@click.option(
    "--disposition",
    required=True,
    type=click.Choice(["approved", "rejected", "quarantined", "frozen"]),
)
@click.option(
    "--grill-evidence-file",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option("--proposal-id", required=True)
@click.option("--grill-ref", required=True)
def audit_graph(
    graph_id: str,
    version: int,
    disposition: str,
    grill_evidence_file: Path,
    proposal_id: str,
    grill_ref: str,
) -> None:
    """记录审计员的 grill-me 问答；不直接编辑图。"""
    evidence = json.loads(grill_evidence_file.read_text(encoding="utf-8"))
    if not isinstance(evidence, list):
        raise click.ClickException("grill evidence must be a JSON array")
    click.echo(_json(client_from_config().audit_research_graph(
        graph_id,
        version,
        proposal_id=proposal_id,
        disposition=disposition,
        grill_evidence=evidence,
        grill_ref=grill_ref,
    )))


@research_graph.command("activate")
@click.argument("graph_id")
@click.argument("version", type=int)
@click.option("--human-authorization-id", required=True)
def activate_graph(
    graph_id: str,
    version: int,
    human_authorization_id: str,
) -> None:
    """消费独立人工授权并原子移动 Active 指针。"""
    click.echo(_json(
        client_from_config().activate_research_graph(
            graph_id,
            version,
            human_authorization_id=human_authorization_id,
        )
    ))


@research_graph.command("human-authorize")
@click.argument("graph_id")
@click.argument("version", type=int)
@click.option("--proposal-id", required=True)
@click.option("--graph-hash", required=True)
@click.option("--diff-hash", required=True)
@click.option("--conversation-ref", required=True)
@click.option("--approval-ref", required=True)
@click.option(
    "--pointer-action",
    type=click.Choice(["activate_graph", "rollback_graph_pointer"]),
    default="activate_graph",
)
@click.option("--pointer-from-version", type=click.IntRange(min=0), default=0)
@click.option("--pointer-reason", default="")
def authorize_activation(
    graph_id: str,
    version: int,
    proposal_id: str,
    graph_hash: str,
    diff_hash: str,
    conversation_ref: str,
    approval_ref: str,
    pointer_action: str,
    pointer_from_version: int,
    pointer_reason: str,
) -> None:
    """记录当前认证会话对精确图变更的一次性授权。"""
    click.echo(_json(
        client_from_config().authorize_research_graph_activation(
            graph_id=graph_id,
            graph_version=version,
            proposal_id=proposal_id,
            graph_hash=graph_hash,
            diff_hash=diff_hash,
            conversation_ref=conversation_ref,
            approval_ref=approval_ref,
            pointer_action=pointer_action,
            pointer_from_version=pointer_from_version,
            pointer_reason=pointer_reason,
        )
    ))


@research_graph.command("rollback")
@click.argument("graph_id")
@click.option("--target-version", type=int, required=True)
@click.option("--reason", required=True)
@click.option("--human-authorization-id", required=True)
def rollback_graph(
    graph_id: str,
    target_version: int,
    reason: str,
    human_authorization_id: str,
) -> None:
    """消费 exact-hash 授权，将 Active 指针回滚到既有版本。"""
    click.echo(_json(client_from_config().rollback_research_graph(
        graph_id,
        target_version=target_version,
        reason=reason,
        human_authorization_id=human_authorization_id,
    )))


@research_graph.command("start")
@click.argument("graph_id")
@click.option("--product-group", required=True)
@click.option("--workspace-id", required=True)
@click.option("--shadow-graph-version", type=click.IntRange(min=1))
@click.option("--shadow-run-id", default="")
@click.option(
    "--capability-resolution-file",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
def start_graph_instance(
    graph_id: str,
    product_group: str,
    workspace_id: str,
    shadow_graph_version: int | None,
    shadow_run_id: str,
    capability_resolution_file: Path,
) -> None:
    """按当前 Active Graph 和产品实现解析启动研究实例。"""
    payload = json.loads(
        capability_resolution_file.read_text(encoding="utf-8")
    )
    resolution = (
        payload.get("resolution") if isinstance(payload, dict) else None
    )
    if not isinstance(resolution, dict):
        resolution = payload
    if not isinstance(resolution, dict):
        raise click.ClickException(
            "capability resolution must be a JSON object"
        )
    resolution = server_capability_resolution(resolution)
    click.echo(_json(client_from_config().create_research_graph_instance(
        graph_id=graph_id,
        product_group=product_group,
        workspace_id=workspace_id,
        capability_resolution=resolution,
        shadow_graph_version=shadow_graph_version,
        shadow_run_id=shadow_run_id,
    )))


@research_graph.command("branch")
@click.argument("instance_id")
@click.argument("branch_id")
def show_graph_branch(instance_id: str, branch_id: str) -> None:
    """读取一个研究分支的当前状态。"""
    click.echo(_json(client_from_config().get_research_graph_branch(
        instance_id,
        branch_id,
    )))


@research_graph.command("context")
@click.argument("instance_id")
@click.argument("branch_id")
def graph_branch_context(instance_id: str, branch_id: str) -> None:
    """只返回当前节点的最小状态包，避免装载完整图和目录。"""
    click.echo(_json(
        client_from_config().get_research_graph_branch_context(
            instance_id,
            branch_id,
        )
    ))


@research_graph.command("next")
@click.argument("instance_id")
@click.argument("branch_id")
def next_graph_step(instance_id: str, branch_id: str) -> None:
    """确定性计算候选边 readiness、缺失证据与 Agent 判断需求。"""
    click.echo(_json(
        client_from_config().get_research_graph_branch_next(
            instance_id,
            branch_id,
        )
    ))


@research_graph.command("cycle-object")
@click.argument("instance_id")
@click.argument("branch_id")
@click.argument("object_type", type=click.Choice(["claim", "obligation"]))
@click.argument("object_id")
def show_research_cycle_object(
    instance_id: str,
    branch_id: str,
    object_type: str,
    object_id: str,
) -> None:
    """按 ID 读取一个当前 Claim 或义务正文。"""
    click.echo(_json(client_from_config().get_research_cycle_object(
        instance_id,
        branch_id,
        object_type,
        object_id,
    )))


@research_graph.command("fork")
@click.argument("instance_id")
@click.argument("branch_id")
@click.option("--label", required=True)
def fork_graph_branch(
    instance_id: str,
    branch_id: str,
    label: str,
) -> None:
    """仅在需要独立假设路径时分叉研究分支。"""
    click.echo(_json(client_from_config().fork_research_graph_branch(
        instance_id,
        branch_id,
        label=label,
    )))


@research_graph.command("continuation-preview")
@click.argument("instance_id")
@click.argument("branch_id")
@click.option("--target-version", required=True, type=click.IntRange(min=1))
@click.option("--job-id", required=True)
def preview_graph_continuation(
    instance_id: str,
    branch_id: str,
    target_version: int,
    job_id: str,
) -> None:
    """计算跨版本 continuation 的精确授权哈希；不修改服务器状态。"""
    click.echo(_json(
        client_from_config().preview_research_graph_continuation(
            instance_id,
            branch_id,
            target_graph_version=target_version,
            job_id=job_id,
        )
    ))


@research_graph.command("continue")
@click.argument("instance_id")
@click.argument("branch_id")
@click.option("--target-version", required=True, type=click.IntRange(min=1))
@click.option("--job-id", required=True)
@click.option("--expected-target-hash", required=True)
@click.option("--human-authorization-id", required=True)
def continue_graph_branch(
    instance_id: str,
    branch_id: str,
    target_version: int,
    job_id: str,
    expected_target_hash: str,
    human_authorization_id: str,
) -> None:
    """消费精确审批并创建不可变的新版本 continuation。"""
    click.echo(_json(
        client_from_config().continue_research_graph_branch(
            instance_id,
            branch_id,
            target_graph_version=target_version,
            job_id=job_id,
            expected_target_hash=expected_target_hash,
            human_authorization_id=human_authorization_id,
        )
    ))


@research_graph.command("advance")
@click.argument("instance_id")
@click.argument("branch_id")
@click.option("--edge-id", required=True)
@click.option(
    "--evidence-file",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option(
    "--target-capability-resolution-file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
def advance_graph_branch(
    instance_id: str,
    branch_id: str,
    edge_id: str,
    evidence_file: Path,
    target_capability_resolution_file: Path | None,
) -> None:
    """提交证据并沿 Active Graph 的一条已声明边前进。"""
    evidence = json.loads(evidence_file.read_text(encoding="utf-8"))
    if not isinstance(evidence, dict):
        raise click.ClickException("transition evidence must be a JSON object")
    if target_capability_resolution_file is not None:
        payload = json.loads(
            target_capability_resolution_file.read_text(encoding="utf-8")
        )
        resolution = (
            payload.get("resolution") if isinstance(payload, dict) else None
        )
        if not isinstance(resolution, dict):
            resolution = payload
        if not isinstance(resolution, dict):
            raise click.ClickException(
                "target capability resolution must be a JSON object"
            )
        evidence["target_capability_resolution"] = (
            server_capability_resolution(resolution)
        )
    click.echo(_json(client_from_config().advance_research_graph_branch(
        instance_id,
        branch_id,
        edge_id=edge_id,
        evidence=evidence,
    )))
