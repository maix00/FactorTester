"""Small Agent-facing commands for navigating a Research Graph instance."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import click

from tools.cli.client import FactorTesterClient
from tools.cli.commands.research_graph_bypass_remediation import (
    bypass_remediation,
)
from tools.cli.commands.research_graph_chapter_reconciliation import (
    ChapterReconciliationRequired,
    reconcile_current_container,
    synchronize_transition_container,
)
from tools.cli.commands.research_graph_factor_subjects import (
    attach_transition_factor_subjects,
)
from tools.cli.commands.research_graph_local_report import (
    LocalGraphReport,
    profile_id_from_ref,
    resolve_local_graph_report,
)
from tools.cli.commands.research_graph_local_report_projection import (
    project_local_report,
)
from tools.cli.commands.research_graph_node_advance import (
    doctor,
    prepare_evidence,
    read_object,
)
from tools.cli.commands.research_graph_obligation_advance import (
    finalize_accepted_advance,
    load_accepted_reconciliation,
    prepare_obligation_advance,
    record_rejected_advance,
    require_complete_coverage,
    require_scope_consistency,
    write_accepted_reconciliation,
)
from tools.cli.commands.research_graph_obligations import (
    record_edge_selection,
)
from tools.cli.commands.research_graph_report_policy import report_container
from tools.cli.commands.research_report_common import rich_body
from tools.cli.commands.research_report_scope import (
    load_authoring,
    resolve_branch_report_scope,
)
from tools.cli.core.context import client_from_config
from tools.cli.release.local_profile import LocalProfileStore
from tools.cli.release.profile import load_profile_root
from tools.cli.release.research_branch_bindings import owns_branch
from tools.cli.release.research_obligations import ledger_path
from tools.cli.release.research_reporting.authoring.structure_gate import (
    current_chapter_structure,
)
from tools.cli.release.research_reporting.authoring.submission import (
    build_report_submission,
    empty_report_submission,
    select_report_submission,
)
from tools.cli.release.research_reporting.publisher import (
    publish_research_checkpoint,
)
from tools.cli.research_graph_entry_assessment import (
    prepare_entry_assessment,
)
from tools.cli.research_graph_submission_contract import (
    validate_public_transition,
)
from tools.cli.research_graph_target_capabilities import (
    prepare_target_capabilities,
)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)


def _with_next_action(value: dict[str, Any]) -> dict[str, Any]:
    # Server responses contain state and validation contracts only.  The local
    # ``research graphs next-local`` command is the sole source of navigation
    # advice; never re-promote a legacy server action into the CLI response.
    value.pop("next_actions", None)
    value.pop("next_action", None)
    return value


def _client_for_profile(
    client_root: Path,
    profile_id: str,
) -> FactorTesterClient:
    LocalProfileStore(client_root).load(profile_id)
    return client_from_config()


def _publish_transition_report(
    *,
    branch: dict[str, Any],
    client_root: Path,
    profile_id: str,
    agent_id: str,
    instance_id: str,
    branch_id: str,
    narrative_file: Path | None,
    chapter_sync: dict[str, Any],
) -> dict[str, Any]:
    carrier = branch.get("report_checkpoint")
    if not isinstance(carrier, dict):
        return {
            "status": "not_available",
            "reason": "checkpoint_carrier_not_available",
            "chapter_sync": chapter_sync,
        }
    system_event = (
        carrier.get("latest_transition") or {}
    ).get("entry_resolution_event")
    if narrative_file is None and not isinstance(system_event, dict):
        return {
            "status": "required",
            "error_code": "local_narrative_required",
            "message": (
                "Server transition completed; a local research narrative "
                "is required to update the report."
            ),
            "checkpoint_ref": carrier.get("checkpoint_ref"),
            "chapter_sync": chapter_sync,
        }
    try:
        narrative = (
            read_object(narrative_file)
            if narrative_file is not None else None
        )
        published = publish_research_checkpoint(
            client_root=client_root,
            profile_id=profile_id,
            agent_id=agent_id,
            carrier=carrier,
            narrative=narrative,
            report_parent_id=str(chapter_sync["component_id"]),
        )
    except (OSError, ValueError) as exc:
        return {
            "status": "required",
            "error_code": (
                "local_report_io_error"
                if isinstance(exc, OSError)
                else "local_report_validation_error"
            ),
            "message": str(exc),
            "checkpoint_ref": carrier.get("checkpoint_ref"),
            "chapter_sync": chapter_sync,
        }
    artifact = published["artifact"]
    return {
        "status": "published",
        "changed": published["changed"],
        "report_changed": published["report_changed"],
        "profile_changed": published["profile_changed"],
        "checkpoint_ref": published["checkpoint_ref"],
        "artifact_ref": artifact["artifact_ref"],
        "chapter_sync": chapter_sync,
    }
def _current_branch_report_submission(
    *, client_root: Path, profile_id: str, agent_id: str,
    instance_id: str, branch_id: str,
    requirement_ids: set[str],
    allow_incomplete: bool = False,
) -> dict[str, Any]:
    """Build the only admissible report submission from the local package.

    The agent never points graph navigation at an arbitrary ``report.json``.
    It first declares the report requirement while adding a component/chip to
    its branch Work Package, then ``node advance`` reads that exact source.
    """
    store = LocalProfileStore(client_root)
    profile = store.load(profile_id)
    branch_ref = f"graph-branch:{instance_id}:{branch_id}"
    records = [
        item for item in profile["research_records"]
        if item["agent_id"] == agent_id
        and owns_branch(item, branch_ref)
    ]
    if len(records) != 1:
        raise click.ClickException(
            "local research record for the selected Graph branch was not found"
        )
    record = records[0]
    try:
        scope = resolve_branch_report_scope(
            client_root=client_root,
            profile_id=profile_id,
            work_package_id=str(record["record_id"]),
            branch_id=branch_id,
        )
        authoring = load_authoring(scope)
        try:
            cumulative = build_report_submission(authoring)
        except ValueError as exc:
            if not allow_incomplete or str(exc) != (
                "report has no report_requirement bindings"
            ):
                raise
            cumulative = empty_report_submission()
        return select_report_submission(
            cumulative,
            requirement_ids=requirement_ids,
            allow_empty=allow_incomplete,
        )
    except (OSError, ValueError) as exc:
        raise click.ClickException(
            "branch Work Package report is unavailable; migrate or initialize "
            "the report before advancing this node: " + str(exc)
            ) from exc


def _transition_report_requirement_ids(
    node_packet: dict[str, Any],
    edge_packet: dict[str, Any],
) -> set[str]:
    contract = node_packet.get("report_requirements") or {}
    current = contract.get("current_node") or {}
    rows = [
        *[
            item for item in current.get("on_entry") or []
            if isinstance(item, dict) and item.get("status") == "missing"
        ],
        *[
            item for item in current.get("on_exit") or []
            if isinstance(item, dict)
        ],
        *[
            item for item in edge_packet.get("report_requirements") or []
            if isinstance(item, dict)
        ],
    ]
    return {
        str(item.get("report_requirement_id") or "")
        for item in rows
        if item.get("report_requirement_id")
    }


def register_navigation_commands(parent: click.Group) -> None:
    """Register the short ``node`` and ``edge`` surfaces beside legacy names."""
    node = click.Group("node", help="查看当前节点并沿已选边推进")
    edge = click.Group("edge", help="查看并选择当前节点的候选边")
    parent.add_command(node)
    parent.add_command(edge)
    @node.command("info")
    @click.argument("instance_id")
    @click.argument("branch_id")
    def node_info(instance_id: str, branch_id: str) -> None:
        """显示当前节点、报告要求和候选边约束。"""
        value = client_from_config().get_research_graph_node_info(
            instance_id, branch_id,
        )
        try:
            value = project_local_report(
                value, client_root=load_profile_root(None),
            )
        except (OSError, ValueError):
            # Server-only and unbound branches remain readable.  A Profile-
            # bound advance performs the strict local report check before it
            # can write any Graph state.
            pass
        click.echo(_json(_with_next_action(value)))

    @node.command("advance")
    @click.argument("instance_id")
    @click.argument("branch_id")
    @click.option("--edge-id", required=True)
    @click.option(
        "--evidence-file",
        required=True,
        type=click.Path(exists=True, dir_okay=False, path_type=Path),
    )
    @click.option(
        "--entry-assessment-file",
        type=click.Path(dir_okay=False, path_type=Path),
        help="当前节点检查编辑文档；node advance 负责生成与校验",
    )
    @click.option(
        "--factor-family",
        default="",
        help="首次生成 Entry Requirement 编辑文档时使用的因子家族",
    )
    @click.option(
        "--factor-source",
        type=click.Choice(["auto", "custom", "public"]),
        default="auto",
        show_default=True,
    )
    @click.option(
        "--target-capability-resolution-file",
        type=click.Path(exists=True, dir_okay=False, path_type=Path),
        help="目标节点能力解析投影",
    )
    @click.option("--acting-profile-ref", default="")
    @click.option("--profile-id")
    @click.option("--agent-id")
    @click.option(
        "--narrative-file",
        type=click.Path(exists=True, dir_okay=False, path_type=Path),
        help="本地报告叙事 JSON；有报告 checkpoint 时必须提供",
    )
    @click.option(
        "--release-profile",
        type=click.Path(exists=True, dir_okay=False, path_type=Path),
    )
    @click.option(
        "--submission-sequence",
        type=click.IntRange(min=1),
        default=None,
    )
    def node_advance(
        instance_id: str,
        branch_id: str,
        edge_id: str,
        evidence_file: Path,
        entry_assessment_file: Path | None,
        factor_family: str,
        factor_source: str,
        target_capability_resolution_file: Path | None,
        acting_profile_ref: str,
        profile_id: str | None,
        agent_id: str | None,
        narrative_file: Path | None,
        release_profile: Path | None,
        submission_sequence: int | None,
    ) -> None:
        """提交证据推进节点，自动同步目标报告章，并返回下一步动作。"""
        if agent_id and not profile_id:
            raise click.ClickException(
                "--agent-id requires --profile-id"
            )
        inferred_profile = profile_id_from_ref(acting_profile_ref)
        if profile_id and inferred_profile and profile_id != inferred_profile:
            raise click.ClickException(
                "--profile-id does not match --acting-profile-ref"
            )
        effective_profile = profile_id or inferred_profile
        bootstrap_client = None
        node_packet = None
        if not effective_profile:
            bootstrap_client = client_from_config()
            node_packet = bootstrap_client.get_research_graph_node_info(
                instance_id, branch_id,
            )
            owner_ref = str(
                (node_packet.get("branch") or {}).get(
                    "current_owner_profile_ref",
                ) or ""
            )
            effective_profile = profile_id_from_ref(owner_ref)
            if effective_profile:
                acting_profile_ref = owner_ref
        local_report: LocalGraphReport | None = None
        client_root = None
        if effective_profile:
            client_root = load_profile_root(release_profile)
            try:
                local_report = resolve_local_graph_report(
                    client_root=client_root,
                    profile_id=effective_profile,
                    agent_id=agent_id or "",
                    instance_id=instance_id,
                    branch_id=branch_id,
                )
            except (OSError, ValueError) as exc:
                raise click.ClickException(
                    f"Graph branch owner profile:{effective_profile} has no "
                    "usable local report binding; synchronize that Profile "
                    "or pass matching --profile-id/--agent-id: " + str(exc)
                ) from exc
            if not acting_profile_ref:
                acting_profile_ref = f"profile:{effective_profile}"
        if narrative_file is not None and local_report is None:
            raise click.ClickException(
                "--narrative-file requires a local Profile Graph binding"
            )
        client = (
            _client_for_profile(client_root, local_report.profile_id)
            if client_root is not None and local_report is not None
            else bootstrap_client or client_from_config()
        )
        if node_packet is None:
            node_packet = client.get_research_graph_node_info(
                instance_id, branch_id,
            )
        local_package_root = (
            getattr(local_report, "package_root", None)
            if local_report is not None else None
        )
        if local_report is not None and local_package_root is not None:
            reconciliation = load_accepted_reconciliation(
                local_package_root, branch_id,
            )
            if reconciliation is not None:
                finalized = finalize_accepted_advance(
                    scope=local_report,
                    next_packet=node_packet,
                    reconciliation=reconciliation,
                    submission_sequence=submission_sequence,
                )
                chapter_sync = synchronize_transition_container(
                    local_report,
                    container=report_container(node_packet),
                )
                click.echo(_json({
                    "status": "accepted_advance_reconciled",
                    "state_changed": False,
                    "advance_receipt": finalized,
                    "chapter_sync": chapter_sync,
                    "next": _with_next_action(node_packet),
                }))
                return
        edge_packet = client.get_research_graph_edge_info(
            instance_id, branch_id, edge_id,
        )
        entry_requirements = [
            item
            for item in node_packet.get("entry_requirements") or []
            if isinstance(item, dict)
        ]
        inline_entry_assessments = isinstance(
            read_object(evidence_file).get(
                "entry_requirement_assessments"
            ),
            list,
        )
        if entry_requirements:
            if (
                entry_assessment_file is None
                and not inline_entry_assessments
            ):
                raise click.ClickException(
                    "current node has unresolved node checks; rerun "
                    "node advance with --entry-assessment-file <path> and "
                    "--factor-family <factor-family>. The first run writes "
                    "the editable document without advancing."
                )
            if (
                entry_assessment_file is not None
                and not entry_assessment_file.exists()
            ):
                if not factor_family:
                    raise click.ClickException(
                        "--factor-family is required when node advance creates "
                        "a new node-check assessment document"
                    )
                try:
                    document = prepare_entry_assessment(
                        next_packet=node_packet,
                        factor_family=factor_family,
                        factor_source=factor_source,
                        output=entry_assessment_file,
                    )
                except (OSError, ValueError) as exc:
                    raise click.ClickException(str(exc)) from exc
                click.echo(_json({
                    "status": "entry_assessment_edit_required",
                    "state_changed": False,
                    "output": str(entry_assessment_file),
                    "selected_requirement_ids": document[
                        "selected_requirement_ids"
                    ],
                    "next_action": {
                        "command": "rerun this node advance command",
                        "instruction": (
                            "complete every __EDIT__ field in the generated "
                            "node-check document; node advance will validate "
                            "it before submitting"
                        ),
                    },
                }))
                return
        elif (
            entry_assessment_file is not None
            and not entry_assessment_file.exists()
        ):
            raise click.ClickException(
                f"Entry Requirement assessment file does not exist: "
                f"{entry_assessment_file}"
            )
        automatic_target_plan = None
        automatic_target_resolution = None
        if target_capability_resolution_file is None:
            try:
                (
                    automatic_target_plan,
                    automatic_target_resolution,
                ) = prepare_target_capabilities(
                    edge_packet.get("target_capabilities") or {},
                    product_group=str(
                        (edge_packet.get("branch") or {}).get(
                            "product_group"
                        ) or ""
                    ),
                )
            except ValueError as exc:
                raise click.ClickException(
                    "target capability preparation failed before submit: "
                    + str(exc)
                ) from exc
        requirement_ids = _transition_report_requirement_ids(
            node_packet, edge_packet,
        )
        human_gate_override = (
            node_packet.get("human_gate_override") or {}
        )
        allow_incomplete_coverage = bool(
            human_gate_override.get("enabled")
        )
        report_submission = (
            _current_branch_report_submission(
                client_root=client_root,
                profile_id=local_report.profile_id,
                agent_id=local_report.agent_id,
                instance_id=instance_id,
                branch_id=branch_id,
                requirement_ids=requirement_ids,
                allow_incomplete=allow_incomplete_coverage,
            )
            if client_root is not None and local_report is not None
            else None
        )
        evidence = prepare_evidence(
            evidence_file=evidence_file,
            entry_assessment_file=entry_assessment_file,
            target_capability_resolution_file=(
                target_capability_resolution_file
            ),
            report_submission=report_submission,
        )
        if automatic_target_resolution is not None:
            evidence["target_capability_resolution"] = (
                automatic_target_resolution
            )
        current_chapter_sync = None
        prepared_advance = None
        if local_report is not None:
            try:
                current_chapter_sync = reconcile_current_container(
                    local_report,
                    container=report_container(node_packet),
                )
                if local_package_root is None:
                    raise ValueError(
                        "Profile-bound research has no local Work Package"
                    )
                if not ledger_path(local_package_root, branch_id).is_file():
                    raise ValueError(
                        "Profile-bound node advance requires the branch-local "
                        "obligation ledger; run research-graph edge choose "
                        "with --profile-id, --agent-id and --reason-file first"
                    )
                current_snapshot = load_authoring(
                    resolve_branch_report_scope(
                        client_root=local_report.client_root,
                        profile_id=local_report.profile_id,
                        work_package_id=str(
                            local_report.record["record_id"]
                        ),
                        branch_id=branch_id,
                    )
                )
                evidence["report_structure"] = current_chapter_structure(
                    current_snapshot,
                    chapter_component_id=str(
                        current_chapter_sync["component_id"]
                    ),
                )
                attach_transition_factor_subjects(
                    evidence,
                    action_contract=(
                        (edge_packet.get("edge") or {})
                        .get("action_contract") or {}
                    ),
                    snapshot=current_snapshot,
                    chapter_component_id=str(
                        current_chapter_sync["component_id"]
                    ),
                    requirement_ids=requirement_ids,
                )
                prepared_advance = prepare_obligation_advance(
                    package_root=local_package_root,
                    branch_id=branch_id,
                    node_packet=node_packet,
                    edge_packet=edge_packet,
                    edge_id=edge_id,
                    evidence=evidence,
                    source_report_parent_id=str(
                        current_chapter_sync["component_id"]
                    ),
                )
                evidence = prepared_advance.evidence
                require_scope_consistency(prepared_advance)
                if not allow_incomplete_coverage:
                    require_complete_coverage(prepared_advance)
            except (OSError, RuntimeError, ValueError) as exc:
                if prepared_advance is not None:
                    record_rejected_advance(
                        package_root=local_package_root,
                        branch_id=branch_id,
                        prepared=prepared_advance,
                        status="local_rejected",
                        error_code="obligation_coverage",
                        message=str(exc),
                    )
                raise click.ClickException(
                    "obligation-ledger advance preparation failed: " + str(exc)
                ) from exc
        elif entry_requirements:
            raise click.ClickException(
                "current node requires a Profile-bound local obligation ledger"
            )
        try:
            submission_contract, local_validation = (
                validate_public_transition(
                    node_packet=node_packet,
                    edge_packet=edge_packet,
                    edge_id=edge_id,
                    evidence=evidence,
                    target_capability_plan=automatic_target_plan,
                )
            )
        except ValueError as exc:
            if prepared_advance is not None and local_report is not None:
                record_rejected_advance(
                    package_root=local_package_root,
                    branch_id=branch_id,
                    prepared=prepared_advance,
                    status="local_rejected",
                    error_code="transition_contract",
                    message=str(exc),
                )
            raise click.ClickException(
                "node advance local contract rejected the submission: "
                + str(exc)
            ) from exc
        try:
            diagnostics = doctor(
                client,
                instance_id,
                branch_id,
                edge_id,
                report_submission=evidence.get("report_submission"),
                entry_assessment_supplied=(
                    "entry_requirement_assessments" in evidence
                ),
                node_packet=node_packet,
                edge_packet=edge_packet,
            )
        except click.ClickException as exc:
            if prepared_advance is not None and local_report is not None:
                record_rejected_advance(
                    package_root=local_package_root,
                    branch_id=branch_id,
                    prepared=prepared_advance,
                    status="local_rejected",
                    error_code="doctor_gate",
                    message=str(exc),
                )
            raise
        diagnostics["submission_contract"] = {
            "contract_hash": submission_contract["contract_hash"],
            "context_ref": submission_contract["context_ref"],
            "local_validation": local_validation,
        }
        if automatic_target_resolution is not None:
            diagnostics["target_capability_resolution"] = {
                "mode": "automatic",
                "node_id": automatic_target_plan["node_id"],
                "capability_ids": list(
                    automatic_target_plan["required_capability_ids"]
                ),
                "agent_guidance": list(
                    automatic_target_plan["agent_guidance"]
                ),
            }
        elif target_capability_resolution_file is not None:
            diagnostics["target_capability_resolution"] = {
                "mode": "explicit_file",
                "path": str(target_capability_resolution_file),
            }
        kwargs: dict[str, Any] = {"edge_id": edge_id, "evidence": evidence}
        if acting_profile_ref:
            kwargs["acting_profile_ref"] = acting_profile_ref
        try:
            branch = client.advance_research_graph_node(
                instance_id, branch_id, **kwargs,
            )
        except Exception as exc:
            if prepared_advance is not None and local_report is not None:
                record_rejected_advance(
                    package_root=local_package_root,
                    branch_id=branch_id,
                    prepared=prepared_advance,
                    status="server_rejected",
                    error_code="server_transition_rejected",
                    message=str(exc),
                )
            raise click.ClickException(
                "node advance server rejected the submission: " + str(exc)
            ) from exc
        if prepared_advance is not None and local_report is not None:
            write_accepted_reconciliation(
                package_root=local_package_root,
                branch_id=branch_id,
                prepared=prepared_advance,
                branch_result=branch,
            )
        try:
            next_packet = client.get_research_graph_node_info(
                instance_id, branch_id,
            )
        except Exception as exc:  # accepted transition remains recoverable
            next_packet = {
                "next_actions": [],
                "next_read_error": str(exc),
            }
        report_publish = None
        if local_report is not None:
            assert client_root is not None
            accepted_receipt = None
            if prepared_advance is not None:
                if next_packet.get("next_read_error"):
                    raise click.ClickException(
                        "server transition completed, but the target node "
                        "packet is pending reconciliation: "
                        + str(next_packet["next_read_error"])
                    )
                try:
                    accepted_receipt = finalize_accepted_advance(
                        scope=local_report,
                        next_packet=next_packet,
                        reconciliation=load_accepted_reconciliation(
                            local_package_root, branch_id,
                        ) or {},
                        submission_sequence=submission_sequence,
                    )
                except (OSError, RuntimeError, ValueError) as exc:
                    raise click.ClickException(
                        "server transition completed, but the local obligation "
                        "receipt is pending reconciliation: " + str(exc)
                    ) from exc
            try:
                chapter_sync = synchronize_transition_container(
                    local_report,
                    # The transition response is a receipt for the edge that
                    # just completed.  The authoritative report container
                    # after acceptance belongs to the current node packet.
                    # This matters for ordinary multi-node obligation work and
                    # for returning to an existing source chapter.
                    container=report_container(next_packet),
                )
            except (ChapterReconciliationRequired, ValueError) as exc:
                raise click.ClickException(str(exc)) from exc
            report_publish = _publish_transition_report(
                branch=branch,
                client_root=client_root,
                profile_id=local_report.profile_id,
                agent_id=local_report.agent_id,
                instance_id=instance_id,
                branch_id=branch_id,
                narrative_file=narrative_file,
                chapter_sync=chapter_sync,
            )
            carrier = branch.get("report_checkpoint")
            if isinstance(carrier, dict) and report_publish["status"] == "published":
                branch = {
                    **{
                        key: value
                        for key, value in branch.items()
                        if key != "report_checkpoint"
                    },
                    "report_checkpoint_ref": carrier.get("checkpoint_ref"),
                }
        remediation = bypass_remediation(
            enabled=allow_incomplete_coverage,
            source_chapter_id=str(
                (current_chapter_sync or {}).get("component_id") or ""
            ),
            report_requirement_ids=list(
                diagnostics.get("missing_requirement_ids") or []
            ),
            obligation_coverage=list(
                (
                    prepared_advance.coverage_submission
                    if prepared_advance is not None else {}
                ).get("coverage") or []
            ),
        )
        click.echo(_json({
            "branch": branch,
            "doctor": diagnostics,
            "diagnostics": diagnostics,
            **({"current_chapter_sync": current_chapter_sync}
               if current_chapter_sync is not None else {}),
            **({"local_report_publish": report_publish}
               if report_publish is not None else {}),
            **({"advance_receipt": accepted_receipt}
               if local_report is not None
               and prepared_advance is not None else {}),
            **({"coverage_remediation": remediation}
               if remediation is not None else {}),
            "next": _with_next_action(next_packet),
        }))

    @edge.command("info")
    @click.argument("instance_id")
    @click.argument("branch_id")
    @click.argument("edge_id")
    def edge_info(instance_id: str, branch_id: str, edge_id: str) -> None:
        """显示一条候选边及其报告要求。"""
        value = client_from_config().get_research_graph_edge_info(
            instance_id, branch_id, edge_id,
        )
        click.echo(_json(_with_next_action(value)))

    @edge.command("choose")
    @click.argument("instance_id")
    @click.argument("branch_id")
    @click.argument("edge_id")
    @click.option(
        "--output",
        type=click.Path(dir_okay=False, path_type=Path),
        help="将选择合同写入本地文件，不改变服务器 Graph 状态",
    )
    @click.option("--profile-id")
    @click.option("--agent-id")
    @click.option(
        "--reason-file",
        type=click.Path(exists=True, dir_okay=False, path_type=Path),
        help="解释 Edge 选择理由的 portable Markdown 富文本",
    )
    @click.option(
        "--release-profile",
        type=click.Path(exists=True, dir_okay=False, path_type=Path),
    )
    @click.option(
        "--submission-sequence",
        type=click.IntRange(min=1),
        default=None,
    )
    def edge_choose(
        instance_id: str,
        branch_id: str,
        edge_id: str,
        output: Path | None,
        profile_id: str | None,
        agent_id: str | None,
        reason_file: Path | None,
        release_profile: Path | None,
        submission_sequence: int | None,
    ) -> None:
        """确认一条候选边；真正改变路径的操作仍是 ``node advance``。"""
        if bool(profile_id) != bool(agent_id):
            raise click.ClickException(
                "--profile-id and --agent-id must be supplied together"
            )
        if profile_id and reason_file is None:
            raise click.ClickException(
                "persisted edge selection requires --reason-file"
            )
        if reason_file is not None and not (profile_id and agent_id):
            raise click.ClickException(
                "--reason-file requires --profile-id and --agent-id"
            )
        if profile_id and agent_id:
            selected = record_edge_selection(
                instance_id=instance_id,
                branch_id=branch_id,
                edge_id=edge_id,
                profile_id=str(profile_id),
                agent_id=str(agent_id),
                release_profile=release_profile,
                reason_markdown=rich_body(
                    body=None, body_file=reason_file,
                ),
                submission_sequence=submission_sequence,
            )
            value = selected
        else:
            value = client_from_config().get_research_graph_edge_info(
                instance_id, branch_id, edge_id,
            )
            selected = {
                "selected_edge_id": edge_id,
                "state_changed": False,
                "server_state_changed": False,
            }
        if submission_sequence is not None and not (profile_id and agent_id):
            raise click.ClickException(
                "--submission-sequence requires --profile-id and --agent-id"
            )
        selected.update({
            "reason": (
                "边选择已写入本地义务账本；node advance 才会改变服务器 Graph"
                if selected["state_changed"] else
                "未提供 Profile 绑定，仅返回边合同且未保存选择"
            ),
            "edge": value.get("edge") or {},
            "report_requirements": value.get("report_requirements") or [],
        })
        _with_next_action(selected)
        if output is not None:
            output.parent.mkdir(parents=True, exist_ok=True)
            selected["output"] = str(output)
            output.write_text(_json(selected) + "\n", encoding="utf-8")
        click.echo(_json(_with_next_action(selected)))
