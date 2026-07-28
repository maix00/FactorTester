"""Small Agent-facing commands for navigating a Research Graph instance."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import click

from tools.cli.core.context import client_from_config
from tools.cli.client import FactorTesterClient
from tools.cli.http import HttpSession
from tools.cli.release.local_profile import LocalProfileStore
from tools.cli.release.profile import load_profile_root
from tools.cli.release.research_reporting.publisher import (
    publish_research_checkpoint,
)
from tools.cli.release.research_reporting.authoring import (
    ensure_branch_report_chapter,
)
from tools.cli.release.research_reporting.document.submission import (
    build_report_submission,
)
from tools.cli.commands.research_graph_node_advance import (
    doctor,
    prepare_evidence,
    read_object,
)
from tools.cli.commands.research_report_scope import (
    load_authoring,
    resolve_branch_report_scope,
)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)


def _with_next_action(value: dict[str, Any]) -> dict[str, Any]:
    actions = value.get("next_actions") or []
    if actions:
        value["next_action"] = actions[0]
    return value


def _client_for_profile(
    client_root: Path,
    profile_id: str,
) -> FactorTesterClient:
    profile = LocalProfileStore(client_root).load(profile_id)
    return FactorTesterClient(HttpSession(profile["server"]["base_url"]))


def _publish_transition_report(
    *,
    branch: dict[str, Any],
    client_root: Path,
    profile_id: str,
    agent_id: str,
    instance_id: str,
    branch_id: str,
    narrative_file: Path | None,
) -> dict[str, Any]:
    chapter_sync = _sync_current_node_chapter(
        client_root=client_root,
        profile_id=profile_id,
        agent_id=agent_id,
        instance_id=instance_id,
        branch_id=branch_id,
        current_node=str(branch.get("current_node") or ""),
    )
    carrier = branch.get("report_checkpoint")
    if not isinstance(carrier, dict):
        return {
            "status": "not_available",
            "reason": "checkpoint_carrier_not_available",
            "chapter_sync": chapter_sync,
        }
    if narrative_file is None:
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
        narrative = read_object(narrative_file)
        published = publish_research_checkpoint(
            client_root=client_root,
            profile_id=profile_id,
            agent_id=agent_id,
            carrier=carrier,
            narrative=narrative,
        )
    except (OSError, ValueError) as exc:
        return {
            "status": "required",
            "error_code": (
                "local_report_io_error"
                if isinstance(exc, OSError)
                else "local_report_validation_error"
            ),
            "message": "Server transition completed; local report update is required.",
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


def _sync_current_node_chapter(
    *,
    client_root: Path,
    profile_id: str,
    agent_id: str,
    instance_id: str,
    branch_id: str,
    current_node: str,
) -> dict[str, Any]:
    if not current_node:
        return {"status": "not_available", "reason": "current_node_missing"}
    try:
        store = LocalProfileStore(client_root)
        profile = store.load(profile_id)
    except (OSError, ValueError) as exc:
        return {
            "status": "not_available",
            "reason": "local_report_sync_unavailable",
            "message": str(exc),
        }
    branch_ref = f"graph-branch:{instance_id}:{branch_id}"
    records = [
        item for item in profile["research_records"]
        if item["agent_id"] == agent_id
        and item["graph_branch_ref"] == branch_ref
    ]
    if len(records) != 1:
        return {
            "status": "not_available",
            "reason": "local_research_record_not_found",
        }
    record = records[0]
    try:
        report = ensure_branch_report_chapter(
            workspace_root=Path(profile["workspace_root"]),
            work_package_id=record["record_id"],
            title=record["title"],
            node_id=current_node,
            branch_id=branch_id,
            branch_ref=branch_ref,
        )
    except (OSError, ValueError) as exc:
        return {
            "status": "failed",
            "reason": "local_report_sync_failed",
            "message": str(exc),
            "node_id": current_node,
        }
    updated = dict(record)
    updated["artifacts"] = [
        item for item in record["artifacts"]
        if item["artifact_ref"] != report["descriptor"]["artifact_ref"]
    ] + [report["descriptor"]]
    store.upsert_research_record(profile_id, updated)
    return {
        "status": "synchronized",
        "node_id": current_node,
        **report["chapter_sync"],
        "report_file": str(report["paths"]["document"]),
    }


def _current_branch_report_submission(
    *, client_root: Path, profile_id: str, agent_id: str,
    instance_id: str, branch_id: str,
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
        and item["graph_branch_ref"] == branch_ref
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
        return build_report_submission(
            authoring["document"], authoring["bindings"],
        )
    except (OSError, ValueError) as exc:
        raise click.ClickException(
            "branch Work Package report is unavailable; migrate or initialize "
            "the report before advancing this node: " + str(exc)
        ) from exc


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
        """显示当前节点、报告要求和下一步动作。"""
        value = client_from_config().get_research_graph_node_info(
            instance_id, branch_id,
        )
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
        type=click.Path(exists=True, dir_okay=False, path_type=Path),
        help="entry-validate 生成的当前节点义务评估投影",
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
    def node_advance(
        instance_id: str,
        branch_id: str,
        edge_id: str,
        evidence_file: Path,
        entry_assessment_file: Path | None,
        target_capability_resolution_file: Path | None,
        acting_profile_ref: str,
        profile_id: str | None,
        agent_id: str | None,
        narrative_file: Path | None,
        release_profile: Path | None,
    ) -> None:
        """提交证据推进节点，并返回推进后的下一步动作。"""
        if bool(profile_id) != bool(agent_id):
            raise click.ClickException(
                "--profile-id and --agent-id must be provided together"
            )
        if narrative_file is not None and not profile_id:
            raise click.ClickException(
                "--narrative-file requires --profile-id and --agent-id"
            )
        client_root = load_profile_root(release_profile) if profile_id else None
        report_submission = (
            _current_branch_report_submission(
                client_root=client_root,
                profile_id=profile_id,
                agent_id=agent_id,
                instance_id=instance_id,
                branch_id=branch_id,
            )
            if client_root is not None and agent_id is not None
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
        client = (
            _client_for_profile(client_root, profile_id)
            if client_root is not None and profile_id is not None
            else client_from_config()
        )
        diagnostics = doctor(
            client,
            instance_id,
            branch_id,
            edge_id,
            report_submission=evidence.get("report_submission"),
            entry_assessment_supplied=(
                "entry_requirement_assessments" in evidence
            ),
        )
        kwargs: dict[str, Any] = {"edge_id": edge_id, "evidence": evidence}
        if acting_profile_ref:
            kwargs["acting_profile_ref"] = acting_profile_ref
        branch = client.advance_research_graph_node(
            instance_id, branch_id, **kwargs,
        )
        report_publish = None
        if profile_id and agent_id:
            assert client_root is not None
            report_publish = _publish_transition_report(
                branch=branch,
                client_root=client_root,
                profile_id=profile_id,
                agent_id=agent_id,
                instance_id=instance_id,
                branch_id=branch_id,
                narrative_file=narrative_file,
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
        try:
            next_packet = client.get_research_graph_node_info(
                instance_id, branch_id,
            )
        except Exception as exc:  # transition result remains useful
            next_packet = {
                "next_actions": [],
                "next_read_error": str(exc),
            }
        click.echo(_json({
            "branch": branch,
            "doctor": diagnostics,
            "diagnostics": diagnostics,
            **({"local_report_publish": report_publish}
               if report_publish is not None else {}),
            "next": _with_next_action(next_packet),
        }))

    @edge.command("info")
    @click.argument("instance_id")
    @click.argument("branch_id")
    @click.argument("edge_id")
    def edge_info(instance_id: str, branch_id: str, edge_id: str) -> None:
        """显示一条候选边及其报告要求和下一步动作。"""
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
    def edge_choose(
        instance_id: str,
        branch_id: str,
        edge_id: str,
        output: Path | None,
    ) -> None:
        """确认一条候选边；真正改变路径的操作仍是 ``node advance``。"""
        value = client_from_config().get_research_graph_edge_info(
            instance_id, branch_id, edge_id,
        )
        selected = {
            "selected_edge_id": edge_id,
            "state_changed": False,
            "reason": "边选择是本地执行合同，node advance 才会提交路径变化",
            "edge": value.get("edge") or {},
            "report_requirements": value.get("report_requirements") or [],
            "next_actions": value.get("next_actions") or [],
        }
        _with_next_action(selected)
        if output is not None:
            output.parent.mkdir(parents=True, exist_ok=True)
            selected["output"] = str(output)
            output.write_text(_json(selected) + "\n", encoding="utf-8")
        click.echo(_json(_with_next_action(selected)))
