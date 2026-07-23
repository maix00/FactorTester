"""Pure-local staging and finalization for trusted historical reports."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from ...local_profile import LocalProfileStore
from ..journal import build_fragment, content_hash
from ..assets import verify_snapshot_assets
from ..writer import render_branch_report, stage_branch_fragment
from .carrier import canonical_carrier
from .identity import ref_id, safe_id, scope_identity
from .narrative import canonical_narrative
from .snapshot import report_snapshot


def stage_historical_research_checkpoint(
    *, client_root: Path, profile_id: str, agent_id: str,
    current_branch_id: str,
    carrier: dict[str, Any], narrative: dict[str, Any],
) -> dict[str, Any]:
    """Stage one trusted root-to-head fragment without moving local HEAD."""
    context = _context(
        client_root=client_root,
        profile_id=profile_id,
        agent_id=agent_id,
        carrier=carrier,
        narrative=narrative,
        require_current=False,
    )
    if context["narrative"]["time_basis"] != "historical_backfill":
        raise ValueError("historical staging requires historical_backfill timing")
    record_branch_id = safe_id(
        context["record"]["graph_branch_ref"].split(":")[-1],
        "record_branch_id",
    )
    if safe_id(current_branch_id, "current_branch_id") != record_branch_id:
        raise ValueError("historical Carrier was not read through the current branch")
    if context["created_at"] > float(context["record"]["updated_at"]):
        raise ValueError("historical checkpoint is newer than the local research HEAD")
    staged = stage_branch_fragment(
        context["fragment"],
        workspace_root=Path(context["profile"]["workspace_root"]),
        work_package_id=context["work_package_id"],
    )
    return {
        "changed": bool(staged["changed"]),
        "finalized": False,
        "profile_changed": False,
        "checkpoint_ref": context["carrier"]["checkpoint_ref"],
        "carrier_hash": context["carrier_hash"],
        "narrative_hash": context["narrative_hash"],
        "section_hash": context["fragment"]["section_hash"],
    }


def finalize_historical_research_backfill(
    *, client_root: Path, profile_id: str, agent_id: str,
    carrier: dict[str, Any], narrative: dict[str, Any],
) -> dict[str, Any]:
    """Publish the staged lineage exactly at the already-recorded local HEAD."""
    context = _context(
        client_root=client_root,
        profile_id=profile_id,
        agent_id=agent_id,
        carrier=carrier,
        narrative=narrative,
        require_current=True,
    )
    record = context["record"]
    if context["carrier"]["checkpoint_ref"] != record["checkpoint_ref"]:
        raise ValueError("backfill finalization must target the existing local HEAD")
    if context["created_at"] != float(record["updated_at"]):
        raise ValueError("backfill finalization cannot change local freshness")

    report = render_branch_report(
        context["snapshot"],
        workspace_root=Path(context["profile"]["workspace_root"]),
        journal_fragment=context["fragment"],
        journal_replaced_branch_id=_continued_source_branch_id(
            context["carrier"], context["branch_id"],
        ),
    )
    descriptor = deepcopy(report["local_artifact_descriptor"])
    updated = deepcopy(record)
    updated["timeline_refs"] = descriptor["section_refs"]
    updated["artifacts"] = [
        item for item in record["artifacts"]
        if item["artifact_ref"] != descriptor["artifact_ref"]
    ] + [descriptor]
    store = context["store"]
    saved = store.upsert_research_record(profile_id, updated)
    profile_changed = saved != context["profile"]
    return {
        "changed": bool(report["changed"] or profile_changed),
        "finalized": True,
        "report_changed": bool(report["changed"]),
        "profile_changed": profile_changed,
        "checkpoint_ref": context["carrier"]["checkpoint_ref"],
        "artifact": descriptor,
        "carrier_hash": context["carrier_hash"],
        "narrative_hash": context["narrative_hash"],
        "section_hash": context["fragment"]["section_hash"],
    }


def _context(
    *, client_root: Path, profile_id: str, agent_id: str,
    carrier: dict[str, Any], narrative: dict[str, Any],
    require_current: bool,
) -> dict[str, Any]:
    value = canonical_carrier(carrier)
    narrative_value = canonical_narrative(narrative, value)
    if narrative_value["schema_version"] != 3:
        raise ValueError("historical backfill requires narrative v3")
    if value["checkpoint_ref"] != value["latest_transition"]["step_ref"]:
        raise ValueError("checkpoint_ref must equal latest transition step_ref")

    store = LocalProfileStore(client_root)
    profile = store.load(profile_id)
    agent = _find_agent(profile, agent_id)
    if agent["role"] != "research":
        raise ValueError("historical backfill requires a research Agent")
    record = _find_record(
        profile,
        work_package_ref=value["work_package_ref"],
        agent_id=agent_id,
    )
    if not record["scope"] or not record["factor_family_versions"]:
        raise ValueError("research record lacks scope or factor-family identity")
    if record["workspace_ref"] != value["workspace_ref"]:
        raise ValueError("checkpoint workspace does not match research record")

    workspace_id = ref_id(value["workspace_ref"], "workspace")
    work_package_id = ref_id(value["work_package_ref"], "work-package")
    branch_parts = value["branch_ref"].split(":")
    if len(branch_parts) != 3 or branch_parts[0] != "graph-branch":
        raise ValueError("branch_ref must identify a physical Graph branch")
    instance_id = safe_id(branch_parts[1], "branch_instance_id")
    branch_id = safe_id(branch_parts[2], "branch_id")
    if not any(
        item["workspace_id"] == workspace_id
        and item["server_workspace_ref"] == value["workspace_ref"]
        for item in profile["workspaces"]
    ):
        raise ValueError("checkpoint workspace is not registered in the profile")
    if require_current:
        current_scope = {"instance_id": instance_id, "branch_id": branch_id}
        if agent["scope"] != current_scope:
            raise ValueError("research Agent scope does not match current HEAD")
        if record["graph_branch_ref"] != value["branch_ref"]:
            raise ValueError("research record does not match current HEAD branch")

    carrier_hash = content_hash(value)
    narrative_hash = content_hash(narrative_value)
    snapshot = report_snapshot(
        value,
        narrative=narrative_value,
        workspace_id=workspace_id,
        work_package_id=work_package_id,
        branch_id=branch_id,
        factor_family_versions=record["factor_family_versions"],
        scope_identity=scope_identity(record["scope"]),
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
    return {
        "store": store,
        "profile": profile,
        "record": record,
        "carrier": value,
        "narrative": narrative_value,
        "carrier_hash": carrier_hash,
        "narrative_hash": narrative_hash,
        "created_at": value["latest_transition"]["created_at"],
        "work_package_id": work_package_id,
        "branch_id": branch_id,
        "snapshot": snapshot,
        "fragment": fragment,
    }


def _find_agent(profile: dict[str, Any], agent_id: str) -> dict[str, Any]:
    matches = [item for item in profile["agents"] if item["agent_id"] == agent_id]
    if len(matches) != 1:
        raise ValueError(f"local Agent not found: {agent_id}")
    return matches[0]


def _find_record(
    profile: dict[str, Any], *, work_package_ref: str, agent_id: str,
) -> dict[str, Any]:
    matches = [
        item for item in profile["research_records"]
        if item["graph_instance_ref"] == work_package_ref
        and item["agent_id"] == agent_id
    ]
    if len(matches) != 1:
        raise ValueError(
            "historical backfill requires one Work Package research record"
        )
    return matches[0]


def _continued_source_branch_id(
    carrier: dict[str, Any], branch_id: str,
) -> str | None:
    if carrier["latest_transition"]["edge_ref"] != (
        "graph-edge:__graph_continuation__"
    ):
        return None
    source = str(carrier["report_lineage"].get("source_branch_ref") or "")
    parts = source.split(":")
    if len(parts) != 3 or parts[0] != "graph-branch":
        raise ValueError("graph continuation source branch is invalid")
    source_branch_id = safe_id(parts[2], "source_branch_id")
    if source_branch_id == branch_id:
        raise ValueError("continued branch cannot replace itself")
    return source_branch_id
