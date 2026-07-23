"""Work Package and Hypothesis Branch summaries."""

from __future__ import annotations

import sqlite3
from typing import Any

from server.services.research_graph.protocol import loads
from server.services.research_graph.report_checkpoint import (
    safe_hash as _safe_hash,
    safe_identifier as _safe_identifier,
)

from .refs import research_ref_for, work_package_ref_for, workspace_ref_for

def _work_package_summary(row: sqlite3.Row) -> dict[str, Any]:
    work_package_id = str(row["work_package_id"] or row["instance_id"])
    work_package_ref = work_package_ref_for(work_package_id)
    branch_count = int(row["branch_count"])
    running_count = int(row["running_branch_count"])
    return {
        "research_ref": work_package_ref,
        "work_package_ref": work_package_ref,
        "workspace_ref": workspace_ref_for(str(row["workspace_id"])),
        "created_by_profile_ref": _profile_ref(row, "created_by_profile_ref"),
        "current_owner_profile_ref": _profile_ref(
            row, "current_owner_profile_ref"
        ),
        "graph_ref": (
            f"{str(row['graph_id'])}@v{int(row['graph_version'])}"
        ),
        "product_group": str(row["product_group"]),
        "mode": str(row["mode"]),
        "lifecycle": str(row["lifecycle"]),
        "lifecycle_revision": int(row["lifecycle_revision"]),
        "branch_count": branch_count,
        "running_branch_count": running_count,
        "status": "running" if running_count else "stopped",
        "created_at": float(row["instance_created_at"]),
        "updated_at": float(row["updated_at"]),
        "detail_href": f"/api/profile-research/{work_package_ref}",
        "report_lookup_ref": work_package_ref,
    }


def _branch_summary(row: sqlite3.Row) -> dict[str, Any]:
    instance_id = str(row["instance_id"])
    work_package_id = str(row["work_package_id"] or instance_id)
    branch_id = str(row["branch_id"])
    branch_ref = research_ref_for(instance_id, branch_id)
    work_package_ref = work_package_ref_for(work_package_id)
    trial_plan_hash = str(row["current_trial_plan_hash"] or "")
    return {
        "research_ref": work_package_ref,
        "work_package_ref": work_package_ref,
        "branch_ref": branch_ref,
        "workspace_ref": workspace_ref_for(str(row["workspace_id"])),
        "created_by_profile_ref": _profile_ref(row, "created_by_profile_ref"),
        "current_owner_profile_ref": _profile_ref(
            row, "current_owner_profile_ref"
        ),
        "graph_ref": (
            f"{str(row['graph_id'])}@v{int(row['graph_version'])}"
        ),
        "product_group": str(row["product_group"]),
        "mode": str(row["mode"]),
        "label": str(row["label"]),
        "current_node": str(row["current_node"]),
        "status": str(row["status"]),
        "trial_plan_ref": (
            f"trial-plan:sha256:{trial_plan_hash}"
            if trial_plan_hash
            else None
        ),
        "latest_trace_ref": (
            f"trace:{str(row['latest_trace_id'])}"
            if row["latest_trace_id"]
            else None
        ),
        "latest_acting_profile_ref": _profile_ref(
            row, "latest_trace_acting_profile_ref"
        ),
        "created_at": float(row["created_at"]),
        "updated_at": float(row["updated_at"]),
        "detail_href": (
            f"/api/profile-research/{work_package_ref}/branches/{branch_id}"
        ),
        "report_lookup_ref": branch_ref,
        "lineage": _branch_lineage(row),
    }


def _branch_lineage(row: sqlite3.Row) -> dict[str, Any]:
    """Project only lineage written atomically by branch creation paths."""
    try:
        edge_id = str(row["lineage_edge_id"] or "")
        evidence = _json_object(row["lineage_evidence_json"])
    except (IndexError, KeyError):
        # Any projection path lacking creation evidence fails closed.
        return {"relation": "unknown"}
    if not edge_id:
        if (
            str(row["label"]) == "primary"
            and float(row["created_at"])
            == float(row["instance_created_at"])
        ):
            return {"relation": "root"}
        return {"relation": "unknown"}
    if edge_id == "__branch_fork__":
        descriptor = evidence.get("branch_fork")
        if not isinstance(descriptor, dict):
            return {"relation": "unknown"}
        source_branch_id = _safe_identifier(
            descriptor.get("source_branch_id")
        )
        source_trace_ref = _safe_trace_ref(
            descriptor.get("source_trace_ref")
        )
        if not source_branch_id:
            return {"relation": "unknown"}
        value = {
            "relation": "fork",
            "source_branch_ref": research_ref_for(
                str(row["instance_id"]), source_branch_id
            ),
        }
        if source_trace_ref:
            value["source_trace_ref"] = source_trace_ref
        return value
    if edge_id == "__graph_continuation__":
        descriptor = evidence.get("graph_continuation")
        if not isinstance(descriptor, dict):
            return {"relation": "unknown"}
        source_instance_id = _safe_identifier(
            descriptor.get("source_instance_id")
        )
        source_branch_id = _safe_identifier(
            descriptor.get("source_branch_id")
        )
        source_trace_id = _safe_identifier(
            descriptor.get("source_trace_id")
        )
        checkpoint_hash = _safe_hash(
            descriptor.get("source_checkpoint_hash")
        )
        if not all((
            source_instance_id,
            source_branch_id,
            source_trace_id,
            checkpoint_hash,
        )):
            return {"relation": "unknown"}
        return {
            "relation": "continuation",
            "source_branch_ref": research_ref_for(
                source_instance_id, source_branch_id
            ),
            "source_trace_ref": f"trace:{source_trace_id}",
            "source_checkpoint_hash": checkpoint_hash,
        }
    return {"relation": "unknown"}



def _safe_trace_ref(value: Any) -> str:
    if not isinstance(value, str) or not value.startswith("trace:"):
        return ""
    identifier = _safe_identifier(value.removeprefix("trace:"))
    return f"trace:{identifier}" if identifier else ""



def _json_object(value: Any) -> dict[str, Any]:
    if value in (None, ""):
        return {}
    parsed = loads(value) if isinstance(value, str) else value
    return parsed if isinstance(parsed, dict) else {}


def _profile_ref(row: sqlite3.Row, key: str) -> str | None:
    """Expose only the opaque Profile reference, never local Profile data."""
    try:
        value = row[key]
    except (IndexError, KeyError):
        return None
    value = str(value or "")
    return value or None
