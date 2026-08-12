"""Overlay a local branch report on the read-only Graph node packet."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from tools.cli.release.research_reporting.authoring.submission import (
    build_report_submission,
    select_report_submission,
)

from .research_graph_local_report import (
    profile_id_from_ref,
    resolve_local_graph_report,
)
from .research_report_scope import load_authoring, resolve_branch_report_scope


def project_local_report(
    packet: dict[str, Any], *, client_root: Path,
) -> dict[str, Any]:
    """Show locally authored coverage without mutating the server checkpoint."""
    branch = packet.get("branch") or {}
    profile_id = profile_id_from_ref(
        str(branch.get("current_owner_profile_ref") or "")
    )
    instance_id = str(branch.get("instance_id") or "")
    branch_id = str(branch.get("branch_id") or "")
    if not profile_id or not instance_id or not branch_id:
        return packet
    local = resolve_local_graph_report(
        client_root=client_root,
        profile_id=profile_id,
        agent_id="",
        instance_id=instance_id,
        branch_id=branch_id,
    )
    scope = resolve_branch_report_scope(
        client_root=client_root,
        profile_id=profile_id,
        work_package_id=str(local.record["record_id"]),
        branch_id=branch_id,
    )
    requirement_ids = _packet_requirement_ids(packet)
    if not requirement_ids:
        return packet
    submission = select_report_submission(
        build_report_submission(load_authoring(scope)),
        requirement_ids=requirement_ids,
        allow_empty=True,
    )
    return apply_local_report_coverage(packet, submission)


def apply_local_report_coverage(
    packet: dict[str, Any], submission: dict[str, Any],
) -> dict[str, Any]:
    """Return a copy whose requirement rows reflect the local submission."""
    projected = deepcopy(packet)
    covered_ids = {
        str(item.get("report_requirement_id") or "")
        for item in submission.get("items") or []
        if isinstance(item, dict)
    }
    changed = False
    contract = projected.get("report_requirements") or {}
    current = contract.get("current_node") or {}
    groups = [current.get("on_entry") or [], current.get("on_exit") or []]
    groups.extend((contract.get("candidate_edges") or {}).values())
    for rows in groups:
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            report_id = str(row.get("report_requirement_id") or "")
            if report_id in covered_ids and row.get("status") != "satisfied":
                row["status"] = "satisfied"
                row["coverage_source"] = "local_report"
                changed = True
    projected["local_report_projection"] = {
        "status": (
            "pending_server_checkpoint" if changed else "server_consistent"
        ),
        "fragment_hash": str(submission.get("fragment_hash") or ""),
        "covered_requirement_count": len(covered_ids),
    }
    return projected


def _packet_requirement_ids(packet: dict[str, Any]) -> set[str]:
    contract = packet.get("report_requirements") or {}
    current = contract.get("current_node") or {}
    groups = [current.get("on_entry") or [], current.get("on_exit") or []]
    groups.extend((contract.get("candidate_edges") or {}).values())
    return {
        str(item.get("report_requirement_id") or "")
        for rows in groups
        if isinstance(rows, list)
        for item in rows
        if isinstance(item, dict) and item.get("report_requirement_id")
    }
