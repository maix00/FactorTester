"""Pure-local publication transaction for Active Graph checkpoints."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from ...local_profile import LocalProfileStore
from ..authoring.checkpoint_publish import publish_checkpoint_snapshot
from ..authoring.tree_schema import digest
from ..assets import verify_snapshot_assets
from .carrier import canonical_carrier
from .identity import (
    ref_id as _ref_id,
    safe_id as _safe_id,
    scope_identity as _scope_identity,
)
from .narrative import canonical_narrative
from .snapshot import report_snapshot
from ..authoring.tree_descriptor import merge_section_refs



def publish_research_checkpoint(
    *,
    client_root: Path,
    profile_id: str,
    agent_id: str,
    carrier: dict[str, Any],
    narrative: dict[str, Any] | None,
    local_reference_allowlist: tuple[str, ...] = (),
    report_parent_id: str = "",
) -> dict[str, Any]:
    """Materialize one checkpoint and update its existing local record."""
    value = canonical_carrier(carrier)
    event = value["latest_transition"].get("entry_resolution_event")
    if narrative is None:
        if event is None:
            raise ValueError(
                "checkpoint publication requires a local narrative"
            )
        narrative_value = {
            "schema_version": 2, "language": "zh-Hans",
            "title": "进入要求处理", "sections": [],
        }
    else:
        narrative_value = canonical_narrative(
            narrative,
            value,
            local_reference_allowlist=local_reference_allowlist,
        )
    carrier_hash = digest(value)
    narrative_hash = digest(narrative_value)
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

    record = _find_record(
        profile,
        work_package_ref=value["work_package_ref"],
        branch_ref=value["branch_ref"],
        agent_id=agent_id,
    )
    target_scope = {
        "instance_id": branch_instance_id,
        "branch_id": branch_id,
    }
    if (
        agent["scope"] != target_scope
        and not _is_agent_shadow_record(record, agent)
    ):
        raise ValueError("research Agent scope does not match checkpoint branch")
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
    report = publish_checkpoint_snapshot(
        package_root=Path(profile["workspace_root"]) / "research" / work_package_id,
        work_package_id=work_package_id, branch_id=branch_id,
        branch_ref=value["branch_ref"], title=record["title"],
        node_id=value["current_node"], snapshot=snapshot,
        report_parent_id=report_parent_id,
        entry_resolution_event=event,
        checkpoint_ref=value["checkpoint_ref"],
    )
    if previous_checkpoint == value["checkpoint_ref"] and not report["changed"]:
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
                "report_generation": report["generation"],
            }
    descriptor = deepcopy(report["descriptor"])
    prior_artifact = next((
        item for item in record["artifacts"]
        if item.get("artifact_ref") == descriptor["artifact_ref"]
    ), {})
    descriptor["section_refs"] = merge_section_refs(
        prior_artifact.get("section_refs") or [], descriptor["section_refs"],
    )
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
        "report_generation": report["generation"],
    }


def _find_agent(profile: dict[str, Any], agent_id: str) -> dict[str, Any]:
    for item in profile["agents"]:
        if item["agent_id"] == agent_id:
            return item
    raise ValueError(f"local Agent not found: {agent_id}")


def _is_agent_shadow_record(
    record: dict[str, Any],
    agent: dict[str, Any],
) -> bool:
    provenance = record.get("provenance") or {}
    scope = agent.get("scope") or {}
    source_branch_ref = (
        f"graph-branch:{scope.get('instance_id', '')}:"
        f"{scope.get('branch_id', '')}"
    )
    return (
        provenance.get("kind") == "shadow_graph_continuation"
        and provenance.get("source_graph_branch_ref") == source_branch_ref
    )


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
    expected_ref = (
        f"artifact:research/{work_package_id}/branches/{branch_id}/authoring/HEAD.json"
    )
    matches = [
        item for item in record["artifacts"]
        if item.get("artifact_ref") == expected_ref
    ]
    return deepcopy(matches[0]) if len(matches) == 1 else None
