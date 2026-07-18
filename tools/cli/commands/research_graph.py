"""Research Decision Graph inspection, evidence, audit, and activation."""

from __future__ import annotations

import json
from pathlib import Path

import click

from tools.cli.core.context import client_from_config


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)


@click.group("research-graph")
def research_graph() -> None:
    """管理产品无关、不可变且经审计激活的研究决策图。"""


_LEGACY_AGENT_FLOW_COMMANDS = frozenset({
    "agent-start",
    "budget-create",
    "token-reserve",
    "token-commit",
    "token-release",
})


def _legacy_agent_flow_command(name: str):
    if name not in _LEGACY_AGENT_FLOW_COMMANDS:
        raise ValueError(f"{name!r} is not a registered legacy Agent Flow command")
    return research_graph.command(name, deprecated=True)


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
@click.option("--replay-passed", is_flag=True, required=True)
@click.option("--shadow-passed", is_flag=True, required=True)
@click.option("--capability-resolution-complete", is_flag=True, required=True)
@click.option("--unaffected-jobs-preserved", is_flag=True, required=True)
@click.option("--token-efficiency-passed", is_flag=True, required=True)
@click.option("--routine-instance-id", required=True)
@click.option("--routine-branch-id", required=True)
@click.option("--baseline-run-id", required=True)
def validate_graph(
    graph_id: str,
    version: int,
    replay_passed: bool,
    shadow_passed: bool,
    capability_resolution_complete: bool,
    unaffected_jobs_preserved: bool,
    token_efficiency_passed: bool,
    routine_instance_id: str,
    routine_branch_id: str,
    baseline_run_id: str,
) -> None:
    """记录 Agent 生成的 replay、shadow、能力与任务隔离证据。"""
    evidence = {
        "replay_passed": replay_passed,
        "shadow_passed": shadow_passed,
        "capability_resolution_complete": capability_resolution_complete,
        "unaffected_jobs_preserved": unaffected_jobs_preserved,
        "token_efficiency_passed": token_efficiency_passed,
        "token_measurement_refs": {
            "routine_instance_id": routine_instance_id,
            "routine_branch_id": routine_branch_id,
            "baseline_run_id": baseline_run_id,
        },
    }
    click.echo(_json(client_from_config().validate_research_graph(
        graph_id,
        version,
        evidence,
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
def propose_graph(
    graph_id: str,
    version: int,
    risk_level: str,
    change_diff_file: Path,
    evidence_refs: tuple[str, ...],
    token_estimate: int,
    agent_execution_id: str,
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


@_legacy_agent_flow_command("agent-start")
@click.option(
    "--role",
    "actor_role",
    type=click.Choice([
        "proposer",
        "reviewer",
        "audit_presenter",
        "implementation_agent",
        "backend_verifier",
    ]),
    required=True,
)
@click.option("--model-id", default="")
@click.option("--codex-version", default="")
@click.option("--reservation-id", required=True)
@click.option(
    "--authority-scope",
    type=click.Choice([
        "local_research",
        "server_research",
        "server_backend_code",
    ]),
    required=True,
)
@click.option("--agent-principal-hash", required=True)
@click.option("--lineage-hash", required=True)
@click.option("--launcher-attestation", required=True)
def start_agent_execution(
    actor_role: str,
    model_id: str,
    codex_version: str,
    reservation_id: str,
    authority_scope: str,
    agent_principal_hash: str,
    lineage_hash: str,
    launcher_attestation: str,
) -> None:
    """由服务器为同一用户签发一个有角色的独立 Agent execution。"""
    click.echo(_json(
        client_from_config().create_research_agent_execution(
            actor_role=actor_role,
            model_id=model_id,
            codex_version=codex_version,
            reservation_id=reservation_id,
            authority_scope=authority_scope,
            agent_principal_hash=agent_principal_hash,
            lineage_hash=lineage_hash,
            launcher_attestation=launcher_attestation,
        )
    ))


@_legacy_agent_flow_command("budget-create")
@click.argument("scope_id")
@click.option("--token-limit", type=click.IntRange(min=1), required=True)
def create_token_budget(scope_id: str, token_limit: int) -> None:
    """创建执行前硬预算 scope。"""
    click.echo(_json(
        client_from_config().create_research_token_budget(
            scope_id=scope_id,
            token_limit=token_limit,
        )
    ))


@_legacy_agent_flow_command("token-reserve")
@click.argument("scope_id")
@click.option(
    "--work-kind",
    type=click.Choice([
        "researcher", "proposer", "reviewer", "audit_presenter", "skill",
        "implementation_agent", "backend_verifier",
    ]),
    required=True,
)
@click.option("--max-input-tokens", type=click.IntRange(min=0), required=True)
@click.option("--max-output-tokens", type=click.IntRange(min=0), required=True)
@click.option("--ttl-seconds", type=click.IntRange(min=1, max=3600), default=900)
def reserve_token_budget(
    scope_id: str,
    work_kind: str,
    max_input_tokens: int,
    max_output_tokens: int,
    ttl_seconds: int,
) -> None:
    """在启动任何 LLM/Reviewer/Skill 工作前原子预留 token。"""
    click.echo(_json(client_from_config().reserve_research_tokens(
        scope_id,
        work_kind=work_kind,
        max_input_tokens=max_input_tokens,
        max_output_tokens=max_output_tokens,
        ttl_seconds=ttl_seconds,
    )))


@_legacy_agent_flow_command("token-commit")
@click.argument("reservation_id")
@click.option("--provider-receipt-id", required=True)
def commit_token_budget(
    reservation_id: str,
    provider_receipt_id: str,
) -> None:
    """只用可信 provider usage receipt 对账预留。"""
    click.echo(_json(client_from_config().commit_research_tokens(
        reservation_id,
        provider_receipt_id=provider_receipt_id,
    )))


@_legacy_agent_flow_command("token-release")
@click.argument("reservation_id")
def release_token_budget(reservation_id: str) -> None:
    """模型调用未发生时释放完整预留。"""
    click.echo(_json(
        client_from_config().release_research_tokens(reservation_id)
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
def audit_graph(
    graph_id: str,
    version: int,
    disposition: str,
    grill_evidence_file: Path,
) -> None:
    """记录审计员的 grill-me 问答；不直接编辑图。"""
    evidence = json.loads(grill_evidence_file.read_text(encoding="utf-8"))
    if not isinstance(evidence, list):
        raise click.ClickException("grill evidence must be a JSON array")
    click.echo(_json(client_from_config().audit_research_graph(
        graph_id,
        version,
        disposition=disposition,
        grill_evidence=evidence,
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
    """消费独立人工授权并生成新的 Active 版本。"""
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
@click.option("--nonce", required=True)
@click.option("--authorized-by", required=True)
@click.option("--expires-at", required=True, type=float)
@click.option("--human-attestation", required=True)
def authorize_activation(
    graph_id: str,
    version: int,
    proposal_id: str,
    graph_hash: str,
    diff_hash: str,
    nonce: str,
    authorized_by: str,
    expires_at: float,
    human_attestation: str,
) -> None:
    """供独立 human-presence adapter 提交一次性授权。"""
    click.echo(_json(
        client_from_config().authorize_research_graph_activation(
            graph_id=graph_id,
            graph_version=version,
            proposal_id=proposal_id,
            graph_hash=graph_hash,
            diff_hash=diff_hash,
            nonce=nonce,
            authorized_by=authorized_by,
            expires_at=expires_at,
            human_attestation=human_attestation,
        )
    ))


@research_graph.command("backend-assure")
@click.argument("job_id")
@click.option("--instance-id", required=True)
@click.option("--branch-id", required=True)
@click.option("--node-id", required=True)
@click.option("--policy-hash", default="")
@click.option("--implementation-execution-id", default="")
def assure_backend(
    job_id: str,
    instance_id: str,
    branch_id: str,
    node_id: str,
    policy_hash: str,
    implementation_execution_id: str,
) -> None:
    """零 Agent 检查终态 job；仅异常时返回 verifier 请求。"""
    click.echo(_json(client_from_config().evaluate_backend_assurance(
        job_id=job_id,
        instance_id=instance_id,
        branch_id=branch_id,
        node_id=node_id,
        policy_hash=policy_hash,
        implementation_execution_id=implementation_execution_id,
    )))


@research_graph.command("backend-verify")
@click.argument("receipt_id")
@click.option("--verifier-execution-id", required=True)
@click.option(
    "--disposition",
    type=click.Choice([
        "confirmed_reliable",
        "backend_change_proposed",
        "research_input_issue",
    ]),
    required=True,
)
@click.option("--evidence-ref", "evidence_refs", multiple=True, required=True)
def verify_backend(
    receipt_id: str,
    verifier_execution_id: str,
    disposition: str,
    evidence_refs: tuple[str, ...],
) -> None:
    """记录唯一异常 verifier 的有界结论。"""
    click.echo(_json(client_from_config().verify_backend_assurance(
        receipt_id,
        verifier_execution_id=verifier_execution_id,
        disposition=disposition,
        evidence_refs=list(evidence_refs),
    )))


@research_graph.command("rollback")
@click.argument("graph_id")
@click.option("--target-version", type=int, required=True)
@click.option("--reason", required=True)
@click.option(
    "--grill-evidence-file",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
def rollback_graph(
    graph_id: str,
    target_version: int,
    reason: str,
    grill_evidence_file: Path,
) -> None:
    """由审计员将 Active 指针回滚到既有已审计 Active 版本。"""
    evidence = json.loads(
        grill_evidence_file.read_text(encoding="utf-8")
    )
    if not isinstance(evidence, list):
        raise click.ClickException("grill evidence must be a JSON array")
    click.echo(_json(client_from_config().rollback_research_graph(
        graph_id,
        target_version=target_version,
        reason=reason,
        grill_evidence=evidence,
    )))


@research_graph.command("start")
@click.argument("graph_id")
@click.option("--product-group", required=True)
@click.option("--workspace-id", required=True)
@click.option("--token-budget", type=click.IntRange(min=1))
@click.option("--shadow-graph-version", type=click.IntRange(min=1))
@click.option("--shadow-run-id", default="")
@click.option(
    "--capability-receipt-file",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
def start_graph_instance(
    graph_id: str,
    product_group: str,
    workspace_id: str,
    token_budget: int | None,
    shadow_graph_version: int | None,
    shadow_run_id: str,
    capability_receipt_file: Path,
) -> None:
    """按当前 Active Graph 和产品实现解析启动研究实例。"""
    payload = json.loads(
        capability_receipt_file.read_text(encoding="utf-8")
    )
    receipt = payload.get("receipt") if isinstance(payload, dict) else None
    if not isinstance(receipt, dict):
        receipt = payload
    if not isinstance(receipt, dict):
        raise click.ClickException(
            "capability receipt must be a JSON object"
        )
    click.echo(_json(client_from_config().create_research_graph_instance(
        graph_id=graph_id,
        product_group=product_group,
        workspace_id=workspace_id,
        capability_receipt=receipt,
        token_budget=token_budget,
        shadow_graph_version=shadow_graph_version,
        shadow_run_id=shadow_run_id,
    )))


@research_graph.command("approve-capability")
@click.argument("capability_id")
@click.option("--descriptor-hash", required=True)
@click.option("--product-group", required=True)
@click.option("--evidence-ref", "evidence_refs", multiple=True, required=True)
def approve_capability(
    capability_id: str,
    descriptor_hash: str,
    product_group: str,
    evidence_refs: tuple[str, ...],
) -> None:
    """审计员按 capability 描述批准执行范围，不登记具体 Skill。"""
    click.echo(_json(
        client_from_config().approve_research_capability(
            capability_id=capability_id,
            descriptor_hash=descriptor_hash,
            product_group=product_group,
            evidence_refs=list(evidence_refs),
        )
    ))


@research_graph.command("attest")
@click.argument("graph_id")
@click.argument("graph_version", type=int)
@click.option("--node", "node_id", required=True)
@click.option("--product-group", required=True)
@click.option(
    "--resolution-file",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option(
    "--approval-refs-file",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option("--product-profile-hash", required=True)
@click.option("--resolver-version", required=True)
@click.option("--shadow-mode", is_flag=True)
def attest_capabilities(
    graph_id: str,
    graph_version: int,
    node_id: str,
    product_group: str,
    resolution_file: Path,
    approval_refs_file: Path,
    product_profile_hash: str,
    resolver_version: str,
    shadow_mode: bool,
) -> None:
    """把本地语义解析换成服务器签发、不可伪造的 receipt。"""
    payload = json.loads(resolution_file.read_text(encoding="utf-8"))
    resolution = (
        payload.get("resolution") if isinstance(payload, dict) else None
    )
    if not isinstance(resolution, dict):
        resolution = payload
    approvals = json.loads(
        approval_refs_file.read_text(encoding="utf-8")
    )
    if not isinstance(resolution, dict) or not isinstance(approvals, dict):
        raise click.ClickException(
            "resolution and approval refs must be JSON objects"
        )
    request_payload = {
        "graph_id": graph_id,
        "graph_version": graph_version,
        "node_id": node_id,
        "product_group": product_group,
        "catalog_hash": str(resolution.get("catalog_hash") or ""),
        "product_profile_hash": product_profile_hash,
        "resolver_version": resolver_version,
        "semantic_resolution": resolution,
        "approval_refs": approvals,
        "provider_conformance_hash": str(
            resolution.get("provider_conformance_hash") or ""
        ),
        "shadow_mode": shadow_mode,
    }
    click.echo(_json(
        client_from_config().attest_research_capabilities(request_payload)
    ))


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
    "--target-capability-receipt-file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
def advance_graph_branch(
    instance_id: str,
    branch_id: str,
    edge_id: str,
    evidence_file: Path,
    target_capability_receipt_file: Path | None,
) -> None:
    """提交证据并沿 Active Graph 的一条已声明边前进。"""
    evidence = json.loads(evidence_file.read_text(encoding="utf-8"))
    if not isinstance(evidence, dict):
        raise click.ClickException("transition evidence must be a JSON object")
    if target_capability_receipt_file is not None:
        payload = json.loads(
            target_capability_receipt_file.read_text(encoding="utf-8")
        )
        receipt = (
            payload.get("receipt") if isinstance(payload, dict) else None
        )
        if not isinstance(receipt, dict):
            receipt = payload
        if not isinstance(receipt, dict):
            raise click.ClickException(
                "target capability receipt must be a JSON object"
            )
        evidence["target_capability_receipt"] = receipt
    click.echo(_json(client_from_config().advance_research_graph_branch(
        instance_id,
        branch_id,
        edge_id=edge_id,
        evidence=evidence,
    )))
