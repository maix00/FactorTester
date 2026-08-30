"""Client-side Research Graph commands.

The local graph evaluator and report/session state are the active research
path. The older server-backed commands in this module remain only while the
Manager service-proxy migration is completed; new local research must not use
them as an authority.
"""

from __future__ import annotations

import json
from pathlib import Path

import click

from tools.cli.capability_projection import server_capability_resolution
from tools.cli.client import FactorTesterClient
from tools.cli.commands.research_graph_chapter_reconciliation import (
    reconcile_current_container,
)
from tools.cli.commands.research_graph_continuation_plan import (
    with_agent_plan,
)
from tools.cli.commands.research_graph_continuation_report import (
    publish_continuation_report,
)
from tools.cli.commands.research_graph_local_report import (
    resolve_local_graph_report,
)
from tools.cli.commands.research_graph_navigation import (
    register_navigation_commands,
)
from tools.cli.commands.research_graph_obligations import (
    register_obligation_commands,
)
from tools.cli.commands.research_graph_report_policy import report_container
from tools.cli.commands.research_graph_transition_report import (
    register_transition_report_commands,
)
from tools.cli.core.context import client_from_config
from tools.cli.local_graph_navigation import evaluate_next, load_graph_document
from tools.cli.release.local_profile import LocalProfileStore
from tools.cli.release.profile import load_profile_root
from tools.cli.release.research_reporting.publisher import (
    publish_current_node_report_checkpoint,
)


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)


def _client_for_profile(client_root: Path, profile_id: str) -> FactorTesterClient:
    LocalProfileStore(client_root).load(profile_id)
    return client_from_config()


@click.group("graphs")
def research_graph() -> None:
    """下载研究图并在本地检查或推进研究状态。"""


@research_graph.command("publish")
@click.argument(
    "graph_file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
def publish_graph(graph_file: Path) -> None:
    """将 Observed 或 Draft Graph 发布为不可变服务器版本。"""
    graph = load_graph_document(graph_file)
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


@research_graph.command("fetch")
@click.argument("graph_id")
@click.option(
    "--version",
    type=int,
    help="下载指定版本；省略时下载服务器当前 Active 版本。",
)
@click.option("--locale", default="", help="可选的已发布图展示语言。")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["json", "yaml"]),
    default="json",
    show_default=True,
)
@click.option(
    "--output",
    type=click.Path(dir_okay=False, path_type=Path),
    help="写入本地文件；省略时输出到 stdout。",
)
def fetch_graph(
    graph_id: str,
    version: int | None,
    locale: str,
    output_format: str,
    output: Path | None,
) -> None:
    """把用户选择的 Graph 下载到本地，供 Agent 离线导航。"""
    client = client_from_config()
    if output_format == "yaml":
        if version is None:
            active = client.get_active_research_graph(graph_id)
            version = int(active.get("version") or 0)
        if version < 1:
            raise click.ClickException("无法确定研究图版本")
        content = client.download_research_graph_yaml(
            graph_id, version, locale=locale,
        )
        if output is not None:
            output.write_bytes(content)
            click.echo(_json({"output": str(output), "version": version}))
        else:
            click.echo(content.decode("utf-8"), nl=False)
        return
    if version is not None:
        versions = client.list_research_graph_versions(graph_id)
        graph = next(
            (item for item in versions
             if int(item.get("version") or 0) == version),
            None,
        )
        if graph is None:
            raise click.ClickException(f"研究图版本不存在: {graph_id}@v{version}")
        # The version list is metadata only; retrieve the full graph through
        # the active endpoint only when it is active.  Non-active JSON graphs
        # should be downloaded as YAML and parsed by the local runner.
        if str(graph.get("lifecycle") or "") != "active":
            raise click.ClickException(
                "非 Active 版本请使用 --format yaml 下载后由本地解析器读取"
            )
    value = client.get_active_research_graph(graph_id)
    encoded = _json(value) + "\n"
    if output is not None:
        output.write_text(encoded, encoding="utf-8")
        click.echo(_json({"output": str(output), "version": value.get("version")}))
    else:
        click.echo(encoded, nl=False)


@research_graph.command("next-local")
@click.option(
    "--graph-file",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option("--current-node", required=True)
@click.option("--capability", "capabilities", multiple=True)
@click.option("--evidence", "evidence", multiple=True)
@click.option(
    "--facts-file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
def next_local(
    graph_file: Path,
    current_node: str,
    capabilities: tuple[str, ...],
    evidence: tuple[str, ...],
    facts_file: Path | None,
) -> None:
    """只在本地根据 Graph 与已收集事实计算下一步。"""
    try:
        graph = load_graph_document(graph_file)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    facts = {}
    if facts_file is not None:
        facts = json.loads(facts_file.read_text(encoding="utf-8"))
        if not isinstance(facts, dict):
            raise click.ClickException("facts file must contain a JSON object")
    click.echo(_json(evaluate_next(
        graph,
        current_node=current_node,
        capabilities=capabilities,
        evidence=evidence,
        facts=facts,
    )))


@research_graph.command("activate")
@click.argument("graph_id")
@click.argument("version", type=int)
def activate_graph(
    graph_id: str,
    version: int,
) -> None:
    """将已登记的 Graph 版本直接设为服务器当前版本。"""
    click.echo(_json(client_from_config().activate_research_graph(
        graph_id,
        version,
    )))


@research_graph.command("start")
@click.argument("graph_id")
@click.option("--product-group", required=True)
@click.option("--workspace-id", required=True)
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
@click.argument(
    "object_type",
    type=click.Choice([
        "claim", "obligation", "task", "trial_plan",
        "run", "run_spec", "delta", "evidence",
    ]),
)
@click.argument("object_id")
@click.option("--trace-id")
def show_research_cycle_object(
    instance_id: str,
    branch_id: str,
    object_type: str,
    object_id: str,
    trace_id: str | None,
) -> None:
    """按稳定 ID 读取一个当前或历史研究对象。"""
    click.echo(_json(client_from_config().get_research_cycle_object(
        instance_id,
        branch_id,
        object_type,
        object_id,
        trace_id=trace_id,
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
    """发布当前节点正文并登记；不推进 Graph 节点。"""
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
        packet = client.get_research_graph_node_info(
            instance_id, branch_id,
        )
        scope = resolve_local_graph_report(
            client_root=client_root,
            profile_id=profile_id,
            agent_id=agent_id,
            instance_id=instance_id,
            branch_id=branch_id,
        )
        parent = reconcile_current_container(
            scope, container=report_container(packet),
        )
        published = publish_current_node_report_checkpoint(
            client_root=client_root,
            profile_id=profile_id,
            agent_id=agent_id,
            carrier=carrier,
            projection=projection,
            report_parent_id=str(parent["component_id"]),
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
        "local_checkpoint_ref": published["checkpoint_ref"],
        "artifact": published["artifact"],
        "server_receipt": receipt,
        "changed": published["changed"],
    }))


from tools.cli.commands.research_result_report import (
    register_research_result_report_commands,
)

register_research_result_report_commands(research_graph)
register_navigation_commands(research_graph)
register_obligation_commands(research_graph)
register_transition_report_commands(research_graph)


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
def preview_graph_continuation(
    instance_id: str,
    branch_id: str,
    target_version: int,
    job_id: str,
) -> None:
    """计算跨版本 continuation 的精确授权哈希；不修改服务器状态。"""
    click.echo(_json(with_agent_plan(
        client_from_config().preview_research_graph_continuation(
            instance_id,
            branch_id,
            target_graph_version=target_version,
            job_id=job_id,
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
    expected_target_hash: str | None,
    yes: bool,
    profile_id: str | None,
    agent_id: str | None,
    release_profile: Path | None,
) -> None:
    """消费精确审批并将同一研究续接到 Active Graph。"""
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
            LocalProfileStore(
                client_root
            ).retarget_research_incarnation(
                profile_id,
                agent_id=agent_id,
                work_package_id=work_package_id,
                source_instance_id=instance_id,
                source_branch_id=branch_id,
                target_instance_id=target_instance_id,
                target_branch_id=target_branch_id,
            )
            source_work_package_id = work_package_id
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
            report_publish = publish_continuation_report(
                client=client,
                client_root=client_root,
                profile_id=profile_id,
                agent_id=agent_id,
                work_package_id=work_package_id,
                source_work_package_id=source_work_package_id,
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
