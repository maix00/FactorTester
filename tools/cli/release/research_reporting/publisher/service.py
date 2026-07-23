"""Pure-local publication transaction for Active Graph checkpoints."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from ...local_profile import LocalProfileStore
from ..journal import build_fragment, content_hash
from ..assets import verify_snapshot_assets
from ..writer import render_branch_report
from .carrier import canonical_carrier
from .identity import (
    ref_id as _ref_id,
    safe_id as _safe_id,
    scope_identity as _scope_identity,
)
from .narrative import canonical_narrative
from .snapshot import report_snapshot



def publish_research_checkpoint(
    *,
    client_root: Path,
    profile_id: str,
    agent_id: str,
    carrier: dict[str, Any],
    narrative: dict[str, Any],
) -> dict[str, Any]:
    """Materialize one checkpoint and update its existing local record."""
    value = canonical_carrier(carrier)
    narrative_value = canonical_narrative(narrative, value)
    carrier_hash = content_hash(value)
    narrative_hash = content_hash(narrative_value)
    store = LocalProfileStore(client_root)
    profile = store.load(profile_id)
    agent = _find_agent(profile, agent_id)
    if agent["role"] != "research":
        raise ValueError("checkpoint publisher requires a research Agent")

    workspace_id = _ref_id(value["workspace_ref"], "workspace")
    work_package_id = _ref_id(value["work_package_ref"], "work-package")
    branch_parts = value["branch_ref"].split(":")
    if (
        len(branch_parts) != 3
        or branch_parts[0] != "graph-branch"
    ):
        raise ValueError("branch_ref must identify a physical Graph branch")
    branch_instance_id = _safe_id(
        branch_parts[1], "branch_instance_id"
    )
    branch_id = _safe_id(branch_parts[2], "branch_id")
    if value["checkpoint_ref"] != value["latest_transition"]["step_ref"]:
        raise ValueError("checkpoint_ref must equal latest transition step_ref")

    if agent["scope"] != {
        "instance_id": branch_instance_id,
        "branch_id": branch_id,
    }:
        raise ValueError("research Agent scope does not match checkpoint branch")
    record = _find_record(
        profile,
        work_package_ref=value["work_package_ref"],
        branch_ref=value["branch_ref"],
        agent_id=agent_id,
    )
    if not record["scope"] or not record["factor_family_versions"]:
        raise ValueError("research record lacks scope or factor-family identity")
    scope_identity = _scope_identity(record["scope"])
    if record["workspace_ref"] != value["workspace_ref"]:
        raise ValueError("checkpoint workspace does not match research record")
    if record["graph_instance_ref"] != value["work_package_ref"]:
        raise ValueError("checkpoint Work Package does not match research record")
    if record["graph_branch_ref"] != value["branch_ref"]:
        raise ValueError("checkpoint branch does not match research record")
    if not any(
        item["workspace_id"] == workspace_id
        and item["server_workspace_ref"] == value["workspace_ref"]
        for item in profile["workspaces"]
    ):
        raise ValueError("checkpoint workspace is not registered in the profile")
    previous_checkpoint = str(record["checkpoint_ref"] or "")
    previous_timestamp = float(record["updated_at"] or 0)
    incoming_timestamp = value["latest_transition"]["created_at"]
    if previous_checkpoint:
        if incoming_timestamp < previous_timestamp:
            raise ValueError("checkpoint is older than the local research record")
        if incoming_timestamp == previous_timestamp and (
            value["checkpoint_ref"] != previous_checkpoint
        ):
            raise ValueError("checkpoint timestamp conflicts with local record")
        if value["checkpoint_ref"] == previous_checkpoint and (
            incoming_timestamp != previous_timestamp
        ):
            raise ValueError("checkpoint identity has a conflicting timestamp")
    snapshot = report_snapshot(
        value,
        narrative=narrative_value,
        report_title=record["title"],
        workspace_id=workspace_id,
        work_package_id=work_package_id,
        branch_id=branch_id,
        factor_family_versions=record["factor_family_versions"],
        scope_identity=scope_identity,
    )
    verify_snapshot_assets(
        Path(profile["workspace_root"]),
        work_package_id,
        snapshot["assets"],
    )
    fragment = build_fragment(
        checkpoint_ref=value["checkpoint_ref"],
        created_at=value["latest_transition"]["created_at"],
        carrier_hash=carrier_hash,
        narrative_hash=narrative_hash,
        sections=snapshot["sections"],
        evidence_refs=snapshot["evidence_refs"],
        gaps=snapshot["gaps"],
        lineage=value["report_lineage"],
        graph_ref=value["graph_ref"],
        branch_ref=value["branch_ref"],
        edge_ref=value["latest_transition"]["edge_ref"],
    )
    journal_replaced_branch_id = (
        _journal_source_branch_id(
            value["report_lineage"], branch_id=branch_id,
        )
        if _is_graph_continuation(value["latest_transition"])
        else None
    )
    report = render_branch_report(
        snapshot,
        workspace_root=Path(profile["workspace_root"]),
        journal_fragment=fragment,
        journal_replaced_branch_id=journal_replaced_branch_id,
    )
    if (
        previous_checkpoint == value["checkpoint_ref"]
        and not report["journal_fragment_changed"]
        and not report["changed"]
    ):
        existing_artifact = _existing_branch_artifact(
            record,
            work_package_id=work_package_id,
            branch_id=branch_id,
            checkpoint_ref=value["checkpoint_ref"],
        )
        if existing_artifact is not None:
            return {
                "changed": bool(report["changed"]),
                "report_changed": bool(report["changed"]),
                "profile_changed": False,
                "checkpoint_ref": value["checkpoint_ref"],
                "artifact": existing_artifact,
                "carrier_hash": carrier_hash,
                "narrative_hash": narrative_hash,
                "section_hash": fragment["section_hash"],
            }
    descriptor = deepcopy(report["local_artifact_descriptor"])
    updated = deepcopy(record)
    updated.update({
        "status": "ready",
        "updated_at": value["latest_transition"]["created_at"],
        "checkpoint_ref": value["checkpoint_ref"],
        "run_ref": (
            value["run_refs"][0] if value["run_refs"] else record["run_ref"]
        ),
        "evidence_refs": snapshot["evidence_refs"],
        "timeline_refs": descriptor["section_refs"],
    })
    updated["artifacts"] = [
        item for item in record["artifacts"]
        if item["artifact_ref"] != descriptor["artifact_ref"]
    ] + [descriptor]
    saved = store.upsert_research_record(profile_id, updated)
    profile_changed = saved != profile
    return {
        "changed": bool(report["changed"] or profile_changed),
        "report_changed": bool(report["changed"]),
        "profile_changed": profile_changed,
        "checkpoint_ref": value["checkpoint_ref"],
        "artifact": descriptor,
        "carrier_hash": carrier_hash,
        "narrative_hash": narrative_hash,
        "section_hash": fragment["section_hash"],
    }


def _journal_source_branch_id(
    lineage: dict[str, Any], *, branch_id: str,
) -> str | None:
    """Return the physical source branch named by a lineage edge.

    This identity is used only to retire the old current entry in the logical
    Work Package index.  Physical fragments remain under their source branch.
    """
    source = lineage.get("source_branch_ref")
    if not source:
        return None
    parts = str(source).split(":")
    if (
        len(parts) != 3
        or parts[0] != "graph-branch"
    ):
        raise ValueError("report lineage source branch is invalid")
    _safe_id(parts[1], "report_lineage.source_instance_id")
    source_branch_id = _safe_id(parts[2], "report_lineage.source_branch_id")
    if source_branch_id == branch_id:
        raise ValueError("report lineage source branch cannot equal target")
    return source_branch_id


def _is_graph_continuation(transition: dict[str, Any]) -> bool:
    """Distinguish a Graph-version continuation from a real research fork."""
    return transition.get("edge_ref") == "graph-edge:__graph_continuation__"


def _find_agent(profile: dict[str, Any], agent_id: str) -> dict[str, Any]:
    for item in profile["agents"]:
        if item["agent_id"] == agent_id:
            return item
    raise ValueError(f"local Agent not found: {agent_id}")


def _find_record(
    profile: dict[str, Any],
    *,
    work_package_ref: str,
    branch_ref: str,
    agent_id: str,
) -> dict[str, Any]:
    matches = [
        item for item in profile["research_records"]
        if item["graph_instance_ref"] == work_package_ref
        and item["graph_branch_ref"] == branch_ref
        and item["agent_id"] == agent_id
    ]
    if len(matches) != 1:
        raise ValueError(
            "checkpoint requires exactly one matching local research record"
        )
    return matches[0]


def _existing_branch_artifact(
    record: dict[str, Any],
    *,
    work_package_id: str,
    branch_id: str,
    checkpoint_ref: str,
) -> dict[str, Any] | None:
    if not any(
        item.get("target_ref") == checkpoint_ref
        for item in record["timeline_refs"]
    ):
        return None
    expected_ref = (
        f"artifact:research/{work_package_id}/branches/{branch_id}/REPORT.md"
    )
    matches = [
        item for item in record["artifacts"]
        if item.get("artifact_ref") == expected_ref
    ]
    return deepcopy(matches[0]) if len(matches) == 1 else None
