"""Research Decision Graph inspection, evidence, audit, and activation."""

from __future__ import annotations

import json
from pathlib import Path
import uuid

import click

from tools.cli.core.context import client_from_config
from tools.cli.capability_projection import server_capability_resolution
from tools.cli.client import FactorTesterClient
from tools.cli.http import HttpSession
from tools.cli.release.local_profile import LocalProfileStore
from tools.cli.release.profile import load_profile_root
from tools.cli.release.research_reporting.publisher import (
    publish_current_node_report_checkpoint,
    publish_research_checkpoint,
)
from tools.cli.release.research_reporting.continuation_narrative import (
    continuation_narrative,
)
from tools.cli.commands.research_graph_continuation_parent import (
    prepare_continuation_report_parent,
)
from tools.cli.commands.research_graph_continuation_plan import (
    with_agent_plan,
)
from tools.cli.commands.research_graph_navigation import (
    register_navigation_commands,
)


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)


def _client_for_profile(client_root: Path, profile_id: str) -> FactorTesterClient:
    profile = LocalProfileStore(client_root).load(profile_id)
    return FactorTesterClient(HttpSession(profile["server"]["base_url"]))


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


@research_graph.command("revise-unused-draft")
@click.argument(
    "graph_file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
def revise_unused_draft(graph_file: Path) -> None:
    """原子修订从未激活、实例化或进入治理的 Draft Graph。"""
    graph = json.loads(graph_file.read_text(encoding="utf-8"))
    if not isinstance(graph, dict):
        raise click.ClickException("graph must be a JSON object")
    click.echo(_json(
        client_from_config().revise_unused_research_graph_draft(graph)
    ))


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


@research_graph.command("activation-status")
@click.argument("graph_id")
@click.argument("version", type=int)
def activation_status(graph_id: str, version: int) -> None:
    """读取目标版本的紧凑激活门禁状态。"""
    click.echo(_json(
        client_from_config().get_research_graph_activation_preflight(
            graph_id,
            version,
        )
    ))


@research_graph.command("budget-profile")
def active_budget_profile() -> None:
    """读取当前运行时 Budget Profile；它不属于 Graph 内容。"""
    click.echo(_json(
        client_from_config().get_active_research_runtime_budget_profile()
    ))


@research_graph.command("budget-profile-configure")
@click.option(
    "--ceiling-bytes",
    required=True,
    type=click.IntRange(min=1, max=16 * 1024),
)
@click.option("--provider-id", default="")
@click.option("--model-id", default="")
@click.option("--tokenizer-id", default="")
@click.option("--tokenizer-revision", default="")
def configure_budget_profile(
    ceiling_bytes: int,
    provider_id: str,
    model_id: str,
    tokenizer_id: str,
    tokenizer_revision: str,
) -> None:
    """创建并切换独立运行时 Budget Profile；不升级 Active Graph。"""
    click.echo(_json(
        client_from_config().configure_research_runtime_budget_profile(
            ceiling_bytes=ceiling_bytes,
            provider_id=provider_id,
            model_id=model_id,
            tokenizer_id=tokenizer_id,
            tokenizer_revision=tokenizer_revision,
        )
    ))


@research_graph.command("validate")
@click.argument("graph_id")
@click.argument("version", type=int)
@click.option("--proposal-id", required=True)
@click.option("--routine-instance-id", required=True)
@click.option("--routine-branch-id", required=True)
@click.option("--baseline-run-id", required=True)
@click.option("--packet-calibration-provider-id")
@click.option("--packet-tokenizer-id")
@click.option("--packet-tokenizer-revision")
@click.option(
    "--packet-calibration-receipt-file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
def validate_graph(
    graph_id: str,
    version: int,
    proposal_id: str,
    routine_instance_id: str,
    routine_branch_id: str,
    baseline_run_id: str,
    packet_calibration_provider_id: str | None,
    packet_tokenizer_id: str | None,
    packet_tokenizer_revision: str | None,
    packet_calibration_receipt_file: Path | None,
) -> None:
    """让服务器从 canonical state 推导 replay、shadow 与 token 证据。"""
    evidence = {
        "shadow_comparison_refs": {
            "routine_instance_id": routine_instance_id,
            "routine_branch_id": routine_branch_id,
            "baseline_run_id": baseline_run_id,
        },
    }
    calibration_values = (
        packet_calibration_provider_id,
        packet_tokenizer_id,
        packet_tokenizer_revision,
        packet_calibration_receipt_file,
    )
    if any(value is not None for value in calibration_values):
        if not all(value is not None for value in calibration_values):
            raise click.UsageError(
                "packet calibration provider, tokenizer identity, revision, "
                "and receipt file must be supplied together"
            )
        evidence["packet_calibration_receipt"] = {
            "provider_id": packet_calibration_provider_id,
            "tokenizer_id": packet_tokenizer_id,
            "tokenizer_revision": packet_tokenizer_revision,
            "receipt": packet_calibration_receipt_file.read_text(
                encoding="utf-8"
            ),
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
@click.option("--human-authorization-id")
@click.option("--yes", is_flag=True, help="确认激活并跳过交互提示。")
@click.option("--approval-ref", hidden=True)
def activate_graph(
    graph_id: str,
    version: int,
    human_authorization_id: str | None,
    yes: bool,
    approval_ref: str | None,
) -> None:
    """预检、授权并原子移动 Active Graph 指针。"""
    client = client_from_config()
    if human_authorization_id:
        click.echo(_json(client.activate_research_graph(
            graph_id,
            version,
            human_authorization_id=human_authorization_id,
        )))
        return
    preflight = client.get_research_graph_activation_preflight(
        graph_id,
        version,
    )
    missing = list(preflight.get("missing_gates") or [])
    if missing:
        raise click.ClickException(
            "激活门禁尚未完成: " + ", ".join(missing)
        )
    if not preflight.get("already_active") and not yes:
        click.confirm(
            f"将全局 Active Graph 切换为 {graph_id}@v{version}？",
            abort=True,
        )
    approval = approval_ref or (
        f"auth-conversation-event:cli-{uuid.uuid4().hex}"
    )
    click.echo(_json(client.activate_reviewed_research_graph(
        graph_id,
        version,
        approval_ref=approval,
    )))


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
@click.option("--shadow-proposal-id", default="")
@click.option("--profile-ref", default="")
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
    shadow_proposal_id: str,
    profile_ref: str,
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
        shadow_proposal_id=shadow_proposal_id,
        profile_ref=profile_ref,
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


@research_graph.command("requirement-detail")
@click.argument("instance_id")
@click.argument("branch_id")
@click.argument("requirement_id")
def show_current_graph_requirement(
    instance_id: str,
    branch_id: str,
    requirement_id: str,
) -> None:
    """按需读取当前节点的一项义务要求合同。"""
    click.echo(_json(client_from_config().get_current_graph_requirement(
        instance_id,
        branch_id,
        requirement_id,
    )))


@research_graph.command("trial-checkpoint")
@click.argument("instance_id")
@click.argument("branch_id")
def show_trial_execution_checkpoint(
    instance_id: str,
    branch_id: str,
) -> None:
    """读取当前 Evidence Action、CAS 身份和服务器操作合同。"""
    click.echo(_json(
        client_from_config().get_trial_execution_checkpoint(
            instance_id,
            branch_id,
        )
    ))


@research_graph.command("trial-checkpoint-recover")
@click.argument("instance_id")
@click.argument("branch_id")
@click.option("--expected-latest-trace-id", required=True)
@click.option("--expected-execution-node", required=True)
def recover_trial_execution_checkpoint(
    instance_id: str,
    branch_id: str,
    expected_latest_trace_id: str,
    expected_execution_node: str,
) -> None:
    """确定性恢复历史 v5 plan 遗漏的空 execution checkpoint。"""
    click.echo(_json(
        client_from_config().recover_trial_execution_checkpoint(
            instance_id,
            branch_id,
            expected_latest_trace_id=expected_latest_trace_id,
            expected_execution_node=expected_execution_node,
        )
    ))


@research_graph.command("trial-action")
@click.argument("instance_id")
@click.argument("branch_id")
@click.argument(
    "operation",
    type=click.Choice([
        "release",
        "mark_running",
        "mark_evidence_ready",
        "mark_blocked",
        "mark_failed",
        "retry",
        "admit",
        "audit",
        "advance",
    ]),
)
@click.option("--expected-latest-trace-id", required=True)
@click.option("--expected-checkpoint-hash", required=True)
@click.option(
    "--payload-file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
def apply_trial_execution_action(
    instance_id: str,
    branch_id: str,
    operation: str,
    expected_latest_trace_id: str,
    expected_checkpoint_hash: str,
    payload_file: Path | None,
) -> None:
    """以 checkpoint 返回的精确合同执行一个 CAS 操作。"""
    payload = (
        json.loads(payload_file.read_text(encoding="utf-8"))
        if payload_file is not None
        else {}
    )
    if not isinstance(payload, dict):
        raise click.ClickException("operation payload must be a JSON object")
    click.echo(_json(
        client_from_config().operate_trial_execution_checkpoint(
            instance_id,
            branch_id,
            expected_latest_trace_id=expected_latest_trace_id,
            expected_checkpoint_hash=expected_checkpoint_hash,
            operation=operation,
            payload=payload,
        )
    ))


@research_graph.command("trial-plan-revise")
@click.argument("instance_id")
@click.argument("branch_id")
@click.option("--expected-latest-trace-id", required=True)
@click.option("--expected-checkpoint-hash", required=True)
@click.option("--expected-trial-plan-hash", required=True)
@click.option(
    "--trial-plan-file",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option("--acting-profile-ref", default="")
def revise_unused_trial_plan(
    instance_id: str,
    branch_id: str,
    expected_latest_trace_id: str,
    expected_checkpoint_hash: str,
    expected_trial_plan_hash: str,
    trial_plan_file: Path,
    acting_profile_ref: str,
) -> None:
    """无 Run、Job 或 Evidence 时以一个显式子 TrialPlan 重置 Action。"""
    plan = json.loads(trial_plan_file.read_text(encoding="utf-8"))
    if not isinstance(plan, dict):
        raise click.ClickException("TrialPlan must be a JSON object")
    click.echo(_json(client_from_config().revise_trial_plan(
        instance_id,
        branch_id,
        expected_latest_trace_id=expected_latest_trace_id,
        expected_checkpoint_hash=expected_checkpoint_hash,
        expected_trial_plan_hash=expected_trial_plan_hash,
        trial_plan=plan,
        acting_profile_ref=acting_profile_ref,
    )))


@research_graph.command("trial-binding")
@click.argument("instance_id")
@click.argument("branch_id")
@click.option("--run-spec-hash", required=True)
@click.option("--trial-role", required=True)
@click.option("--comparison-id", required=True)
@click.option(
    "--output",
    required=True,
    type=click.Path(dir_okay=False, path_type=Path),
)
def write_trial_execution_binding(
    instance_id: str,
    branch_id: str,
    run_spec_hash: str,
    trial_role: str,
    comparison_id: str,
    output: Path,
) -> None:
    """生成当前 released action 的 canonical ``run submit`` binding。"""
    binding = client_from_config().get_trial_execution_binding(
        instance_id,
        branch_id,
        run_spec_hash=run_spec_hash,
        trial_role=trial_role,
        comparison_id=comparison_id,
    )
    encoded = json.dumps(
        binding,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ) + "\n"
    output.write_text(encoded, encoding="utf-8")
    click.echo(_json({
        "output": str(output),
        "trial_plan_hash": binding.get("trial_plan_hash"),
        "evidence_action_id": binding.get("evidence_action_id"),
        "expected_checkpoint_hash": binding.get(
            "expected_checkpoint_hash"
        ),
    }))


@research_graph.command("checkpoint-report")
@click.argument("instance_id")
@click.argument("branch_id")
@click.option("--node-id", required=True)
@click.option(
    "--projection-file",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option("--work-package-id", required=True)
@click.option("--profile-id", required=True)
@click.option("--agent-id", required=True)
@click.option(
    "--release-profile",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
def checkpoint_current_report(
    instance_id: str,
    branch_id: str,
    node_id: str,
    projection_file: Path,
    work_package_id: str,
    profile_id: str,
    agent_id: str,
    release_profile: Path,
) -> None:
    """发布 entry-validate 正文并登记；不推进 Graph 节点。"""
    projection = json.loads(projection_file.read_text(encoding="utf-8"))
    if not isinstance(projection, dict):
        raise click.ClickException(
            "projection file must contain an entry projection"
        )
    client_root = load_profile_root(release_profile)
    client = _client_for_profile(client_root, profile_id)
    branch = client.get_profile_research_branch(
        f"work-package:{work_package_id}", branch_id,
    )
    carrier = branch.get("report_checkpoint")
    if not isinstance(carrier, dict):
        raise click.ClickException("current report Carrier is unavailable")
    if carrier.get("current_node") != node_id:
        raise click.ClickException("requested node is no longer current")
    try:
        published = publish_current_node_report_checkpoint(
            client_root=client_root,
            profile_id=profile_id,
            agent_id=agent_id,
            carrier=carrier,
            projection=projection,
        )
    except (OSError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    # Publication happens first. A failed receipt leaves a complete,
    # content-addressed local checkpoint that the same command can retry.
    receipt = client.append_current_report_checkpoint(
            instance_id,
            branch_id,
            node_id=node_id,
            report_submission=published["report_submission"],
            report_artifact_ref=published["report_artifact_ref"],
    )
    click.echo(_json({
        "checkpoint_ref": published["checkpoint_ref"],
        "artifact": published["artifact"],
        "receipt": receipt,
        "changed": published["changed"],
    }))


from tools.cli.commands.research_result_report import (
    register_research_result_report_commands,
)
register_research_result_report_commands(research_graph)
register_navigation_commands(research_graph)


@research_graph.command("fork")
@click.argument("instance_id")
@click.argument("branch_id")
@click.option("--label", required=True)
@click.option("--acting-profile-ref", default="")
def fork_graph_branch(
    instance_id: str,
    branch_id: str,
    label: str,
    acting_profile_ref: str,
) -> None:
    """仅在需要独立假设路径时分叉研究分支。"""
    click.echo(_json(client_from_config().fork_research_graph_branch(
        instance_id,
        branch_id,
        label=label,
        acting_profile_ref=acting_profile_ref,
    )))


@research_graph.command("handoff")
@click.argument("instance_id")
@click.argument("branch_id")
@click.option("--source-profile-ref", required=True)
@click.option("--destination-profile-ref", required=True)
@click.option("--expected-checkpoint-ref", required=True)
@click.option("--expected-checkpoint-hash", required=True)
@click.option("--authorization-ref", required=True)
@click.option("--source-display-name", default="")
@click.option("--destination-display-name", default="")
def handoff_graph_branch(
    instance_id: str,
    branch_id: str,
    source_profile_ref: str,
    destination_profile_ref: str,
    expected_checkpoint_ref: str,
    expected_checkpoint_hash: str,
    authorization_ref: str,
    source_display_name: str,
    destination_display_name: str,
) -> None:
    """在已验证 checkpoint 处把分支交给另一个 Profile。"""
    click.echo(_json(client_from_config().handoff_research_graph_branch(
        instance_id,
        branch_id,
        source_profile_ref=source_profile_ref,
        destination_profile_ref=destination_profile_ref,
        expected_checkpoint_ref=expected_checkpoint_ref,
        expected_checkpoint_hash=expected_checkpoint_hash,
        authorization_ref=authorization_ref,
        source_display_name=source_display_name,
        destination_display_name=destination_display_name,
    )))


@research_graph.command("continuation-preview")
@click.argument("instance_id")
@click.argument("branch_id")
@click.option("--target-version", required=True, type=click.IntRange(min=1))
@click.option(
    "--job-id",
    default="",
    help="已绑定 Job；暂停于 TrialPlan 前的分支可省略。",
)
@click.option(
    "--mode",
    "execution_mode",
    type=click.Choice(["live", "shadow"]),
    default="live",
    show_default=True,
)
def preview_graph_continuation(
    instance_id: str,
    branch_id: str,
    target_version: int,
    job_id: str,
    execution_mode: str,
) -> None:
    """计算跨版本 continuation 的精确授权哈希；不修改服务器状态。"""
    click.echo(_json(with_agent_plan(
        client_from_config().preview_research_graph_continuation(
            instance_id,
            branch_id,
            target_graph_version=target_version,
            job_id=job_id,
            execution_mode=execution_mode,
        )
    )))


@research_graph.command("continue")
@click.argument("instance_id")
@click.argument("branch_id")
@click.option("--target-version", required=True, type=click.IntRange(min=1))
@click.option(
    "--job-id",
    default="",
    help="已绑定 Job；暂停于 TrialPlan 前的分支可省略。",
)
@click.option(
    "--mode",
    "execution_mode",
    type=click.Choice(["live", "shadow"]),
    default="live",
    show_default=True,
)
@click.option("--expected-target-hash")
@click.option("--yes", is_flag=True, help="预检后确认继续并跳过交互提示。")
@click.option("--profile-id")
@click.option("--agent-id")
@click.option(
    "--release-profile",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
def continue_graph_branch(
    instance_id: str,
    branch_id: str,
    target_version: int,
    job_id: str,
    execution_mode: str,
    expected_target_hash: str | None,
    yes: bool,
    profile_id: str | None,
    agent_id: str | None,
    release_profile: Path | None,
) -> None:
    """消费精确审批，在同一 Work Package 内创建新物理版本。"""
    if bool(profile_id) != bool(agent_id):
        raise click.ClickException(
            "--profile-id and --agent-id must be provided together"
        )
    client_root = load_profile_root(release_profile) if profile_id else None
    client = (
        _client_for_profile(client_root, profile_id)
        if client_root is not None and profile_id is not None
        else client_from_config()
    )
    preview_with_plan = None
    if expected_target_hash is None:
        preview_with_plan = with_agent_plan(
            client.preview_research_graph_continuation(
                instance_id,
                branch_id,
                target_graph_version=target_version,
                job_id=job_id,
                execution_mode=execution_mode,
            )
        )
        preview = preview_with_plan
        expected_target_hash = str(preview.get("target_hash") or "")
        if len(expected_target_hash) != 64:
            raise click.ClickException(
                "continuation preview did not return an exact target hash"
            )
        if not yes:
            lineage = (
                (preview.get("descriptor") or {}).get("lineage_versions")
                or []
            )
            path = " → ".join(f"v{item}" for item in lineage)
            suffix = f"（{path}）" if path else ""
            click.confirm(
                f"将当前研究续接到 Graph v{target_version}{suffix}？",
                abort=True,
            )
    continuation = client.continue_research_graph_branch(
            instance_id,
            branch_id,
            target_graph_version=target_version,
            job_id=job_id,
            expected_target_hash=expected_target_hash,
            execution_mode=execution_mode,
        )
    if preview_with_plan is not None:
        continuation = {
            **continuation,
            "agent_plan": preview_with_plan["agent_plan"],
        }
    if profile_id and agent_id:
        assert client_root is not None
        branches = continuation.get("branches") or []
        work_package_id = str(continuation.get("work_package_id") or "")
        target_instance_id = str(continuation.get("instance_id") or "")
        target_branch_id = (
            str(branches[0].get("branch_id") or "")
            if len(branches) == 1 and isinstance(branches[0], dict)
            else ""
        )
        try:
            if not all(
                (work_package_id, target_instance_id, target_branch_id)
            ):
                raise ValueError(
                    "continuation response lacks stable logical identity"
                )
            LocalProfileStore(client_root).retarget_research_incarnation(
                profile_id,
                agent_id=agent_id,
                work_package_id=work_package_id,
                source_instance_id=instance_id,
                source_branch_id=branch_id,
                target_instance_id=target_instance_id,
                target_branch_id=target_branch_id,
            )
        except (OSError, ValueError) as exc:
            continuation = {
                **continuation,
                "local_profile_sync": {
                    "status": "required",
                    "error_code": (
                        "local_profile_io_error"
                        if isinstance(exc, OSError)
                        else "local_profile_validation_error"
                    ),
                    "message": (
                        "Server continuation completed; local Profile "
                        "retargeting is required."
                    ),
                },
            }
        else:
            report_publish = _publish_continuation_report(
                client=client,
                client_root=client_root,
                profile_id=profile_id,
                agent_id=agent_id,
                work_package_id=work_package_id,
                source_branch_id=branch_id,
                target_instance_id=target_instance_id,
                target_branch_id=target_branch_id,
            )
            continuation = {
                **continuation,
                "local_profile_sync": {
                    "status": "retargeted",
                    "work_package_id": work_package_id,
                    "target_instance_id": target_instance_id,
                    "target_branch_id": target_branch_id,
                },
                "local_report_publish": report_publish,
            }
    click.echo(_json(continuation))


def _publish_continuation_report(
    *,
    client: FactorTesterClient,
    client_root: Path,
    profile_id: str,
    agent_id: str,
    work_package_id: str,
    source_branch_id: str,
    target_instance_id: str,
    target_branch_id: str,
) -> dict[str, object]:
    try:
        parent = prepare_continuation_report_parent(
            client=client, client_root=client_root,
            profile_id=profile_id, agent_id=agent_id,
            work_package_id=work_package_id,
            source_branch_id=source_branch_id,
            target_instance_id=target_instance_id,
            target_branch_id=target_branch_id,
        )
        branch = client.get_profile_research_branch(
            f"work-package:{work_package_id}", target_branch_id,
        )
        carrier = branch.get("report_checkpoint")
        if not isinstance(carrier, dict):
            raise ValueError("continuation report Carrier is unavailable")
        published = publish_research_checkpoint(
            client_root=client_root,
            profile_id=profile_id,
            agent_id=agent_id,
            carrier=carrier,
            narrative=continuation_narrative(carrier),
            report_parent_id=str(parent["component_id"]),
        )
    except (OSError, RuntimeError, ValueError) as exc:
        return {
            "status": "required",
            "error_code": (
                "local_report_io_error"
                if isinstance(exc, OSError)
                else "local_report_validation_error"
            ),
            "message": str(exc),
        }
    artifact = published["artifact"]
    return {
        "status": "published",
        "changed": published["changed"],
        "checkpoint_ref": published["checkpoint_ref"],
        "artifact_ref": artifact["artifact_ref"],
        "report_parent_id": parent["component_id"],
    }
