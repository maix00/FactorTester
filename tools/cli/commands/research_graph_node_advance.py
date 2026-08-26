"""Evidence preparation and doctor checks for ``research graphs node advance``."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import click

from tools.cli.capability_projection import server_capability_resolution
from tools.cli.research_graph_entry_assessment import (
    normalize_entry_assessment,
)


def read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise click.ClickException(f"invalid JSON file: {path}") from exc
    if not isinstance(value, dict):
        raise click.ClickException("JSON file must contain an object")
    return value


def prepare_evidence(
    *,
    evidence_file: Path,
    entry_assessment_file: Path | None,
    target_capability_resolution_file: Path | None,
    report_submission: dict[str, Any] | None,
) -> dict[str, Any]:
    evidence = read_object(evidence_file)
    if target_capability_resolution_file is not None:
        payload = read_object(target_capability_resolution_file)
        resolution = payload.get("resolution")
        if not isinstance(resolution, dict):
            resolution = payload
        try:
            evidence["target_capability_resolution"] = (
                server_capability_resolution(resolution)
            )
        except ValueError as exc:
            raise click.ClickException(str(exc)) from exc
    entry_submission = None
    if entry_assessment_file is not None:
        try:
            assessment = normalize_entry_assessment(
                read_object(entry_assessment_file)
            )
        except ValueError as exc:
            raise click.ClickException(
                f"invalid Entry Requirement assessment: {exc}"
            ) from exc
        assessments = assessment.get("entry_requirement_assessments")
        if not isinstance(assessments, list):
            raise click.ClickException(
                "entry assessment file must contain "
                "entry_requirement_assessments"
            )
        evidence["entry_requirement_assessments"] = assessments
        entry_submission = assessment.get("report_submission")
    if report_submission is not None:
        # The branch report tree is the current, auditable prose source.  An
        # editable Entry Assessment may retain hashes produced before the
        # corresponding report components were corrected or migrated; those
        # hashes must never compete with the current tree projection.
        evidence["report_submission"] = report_submission
    elif entry_submission is not None:
        evidence["report_submission"] = entry_submission
    if evidence.get("report_submission") is None:
        evidence.pop("report_submission", None)
    return evidence


def doctor(
    client: Any,
    instance_id: str,
    branch_id: str,
    edge_id: str,
    *,
    report_submission: dict[str, Any] | None,
    entry_assessment_supplied: bool,
    node_packet: dict[str, Any] | None = None,
    edge_packet: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Check locally visible requirements before the server's atomic check."""
    node = node_packet or client.get_research_graph_node_info(
        instance_id, branch_id,
    )
    edge = edge_packet or client.get_research_graph_edge_info(
        instance_id, branch_id, edge_id,
    )
    human_gate_override = node.get("human_gate_override") or {}
    allow_incomplete_coverage = bool(
        human_gate_override.get("enabled")
    )
    entry_requirements = [
        item for item in node.get("entry_requirements") or []
        if isinstance(item, dict)
    ]
    if entry_requirements and not entry_assessment_supplied:
        requirement_ids = sorted({
            str(item.get("requirement_id") or "")
            for item in entry_requirements
        })
        raise click.ClickException(
            "node advance doctor gate: entry assessment is required for "
            + ", ".join(requirement_ids)
        )
    contract = node.get("report_requirements") or {}
    current = contract.get("current_node") or {}
    rows = list(current.get("on_exit") or [])
    rows.extend(edge.get("report_requirements") or [])
    report_supplied = report_submission is not None
    missing = [
        item for item in rows
        if isinstance(item, dict) and item.get("status") == "missing"
    ]
    if (
        str(contract.get("enforcement") or "optional") == "required"
        and rows
        and not report_supplied
        and not allow_incomplete_coverage
    ):
        requirement_ids = sorted({
            str(item.get("report_requirement_id") or "")
            for item in missing
        })
        raise click.ClickException(
            "node advance doctor gate: report is required for "
            + ", ".join(requirement_ids)
        )
    covered = {
        (
            str(item.get("report_requirement_id") or ""),
            str(item.get("subject_ref") or ""),
        )
        for item in (report_submission or {}).get("items") or []
        if isinstance(item, dict)
    }
    uncovered_static = [
        item for item in rows
        if (
            isinstance(item, dict)
            and item.get("subject_ref")
            and (
                str(item.get("report_requirement_id") or ""),
                str(item.get("subject_ref") or ""),
            ) not in covered
        )
    ]
    if (
        str(contract.get("enforcement") or "optional") == "required"
        and report_supplied
        and uncovered_static
        and not allow_incomplete_coverage
    ):
        raise click.ClickException(
            "node advance doctor gate: report coverage is incomplete for "
            + ", ".join(
                str(item.get("report_requirement_id") or "")
                for item in uncovered_static
            )
        )
    resolution = node.get("entry_resolution") or {}
    current_node = str(
        (node.get("node") or {}).get("node_id")
        or (node.get("branch") or {}).get("current_node")
        or ""
    )
    return {
        "operation": "node.advance",
        "status": "ready_for_server_validation",
        "current_node": current_node,
        "report_enforcement": str(
            contract.get("enforcement") or "optional"
        ),
        "report_supplied": report_supplied,
        "checked_requirement_count": len(rows),
        "missing_requirement_ids": sorted({
            str(item.get("report_requirement_id") or "")
            for item in missing
        }),
        "human_gate_override": {
            "enabled": allow_incomplete_coverage,
            "scope": str(
                human_gate_override.get("scope")
                or "missing_coverage_only"
            ),
            "warning": (
                "报告或义务覆盖缺失不会阻止本次推进，但必须补写来源"
                "节点章节；报告格式和章节结构门禁仍不可旁路"
                if allow_incomplete_coverage and (
                    missing or uncovered_static
                ) else ""
            ),
        },
        "entry_assessment_supplied": entry_assessment_supplied,
        "entry_resolution": {
            key: resolution.get(key)
            for key in (
                "status", "resume_node", "detour_node",
                "unresolved_requirement_ids",
            )
            if key in resolution
        },
        "server_authority": (
            "server recomputes source-node, edge, target-node and dynamic "
            "object report coverage"
        ),
    }
