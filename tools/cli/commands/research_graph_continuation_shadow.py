"""Local report binding for an isolated Graph continuation shadow."""

from __future__ import annotations

from pathlib import Path
import time
from typing import Any

from tools.cli.release.local_profile import LocalProfileStore
from tools.cli.release.research_reporting.package_layout import (
    PACKAGE_DIRECTORIES,
    safe_package_component,
)
from tools.cli.release.research_reporting.authoring.tree_model import (
    load_snapshot,
)


def materialize_shadow_continuation_record(
    *,
    client_root: Path,
    profile_id: str,
    agent_id: str,
    source_instance_id: str,
    source_branch_id: str,
    target_instance_id: str,
    target_branch_id: str,
    target_work_package_id: str,
) -> dict[str, Any]:
    """Register a shadow report without moving the live Agent scope."""
    store = LocalProfileStore(client_root)
    profile, agent = store.load_agent(profile_id, agent_id)
    if agent["role"] != "research":
        raise ValueError("Graph continuation requires a research Agent")
    source_ref = (
        f"graph-branch:{source_instance_id}:{source_branch_id}"
    )
    source_records = [
        item for item in profile["research_records"]
        if item["agent_id"] == agent_id
        and item["graph_branch_ref"] == source_ref
    ]
    if len(source_records) != 1:
        raise ValueError(
            "shadow continuation requires exactly one local source record"
        )
    source = source_records[0]
    source_work_package_id = safe_package_component(
        str(source["record_id"]),
        field="source Work Package id",
    )
    target_work_package_id = safe_package_component(
        target_work_package_id,
        field="target Work Package id",
    )
    target_branch_id = safe_package_component(
        target_branch_id,
        field="target branch_id",
    )
    target_ref = (
        f"graph-branch:{target_instance_id}:{target_branch_id}"
    )
    workspace_root = Path(profile["workspace_root"]).expanduser()
    source_root = workspace_root / "research" / source_work_package_id
    if not source_root.is_dir():
        raise ValueError("source Work Package is not initialized locally")
    factor_versions = list(source["factor_family_versions"])
    if not factor_versions:
        factor_versions = _report_factor_refs(
            source_root, source_branch_id,
        )
    if not factor_versions:
        raise ValueError(
            "source research has no frozen or report-bound factor identity"
        )
    existing = [
        item for item in profile["research_records"]
        if item["record_id"] == target_work_package_id
        or item["graph_branch_ref"] == target_ref
    ]
    if existing:
        if (
            len(existing) == 1
            and existing[0]["record_id"] == target_work_package_id
            and existing[0]["graph_branch_ref"] == target_ref
        ):
            if not existing[0]["factor_family_versions"]:
                repaired = {
                    **existing[0],
                    "factor_family_versions": factor_versions,
                }
                store.upsert_research_record(profile_id, repaired)
                existing = [repaired]
            return {
                **existing[0],
                "source_work_package_id": source_work_package_id,
            }
        raise ValueError("shadow continuation local identity conflicts")

    target_root = workspace_root / "research" / target_work_package_id
    for relative in PACKAGE_DIRECTORIES:
        (target_root / relative).mkdir(parents=True, exist_ok=True)

    now = time.time()
    record = {
        **source,
        "record_id": target_work_package_id,
        "status": "pending",
        "created_at": now,
        "updated_at": now,
        "graph_instance_ref": f"work-package:{target_work_package_id}",
        "graph_branch_ref": target_ref,
        "checkpoint_ref": "",
        "factor_family_versions": factor_versions,
        "artifacts": [],
        "provenance": {
            "kind": "shadow_graph_continuation",
            "source_work_package_id": source_work_package_id,
            "source_graph_branch_ref": source_ref,
        },
    }
    store.upsert_research_record(profile_id, record)
    return {
        **record,
        "source_work_package_id": source_work_package_id,
    }


def _report_factor_refs(
    package_root: Path,
    branch_id: str,
) -> list[str]:
    snapshot = load_snapshot(
        package_root=package_root,
        branch_id=branch_id,
    )
    return sorted({
        str(item.get("target_ref") or "")
        for item in snapshot.get("bindings") or []
        if item.get("kind") in {"factor", "factor_family"}
        and str(item.get("target_ref") or "").startswith(
            ("factor-family:", "factor:")
        )
    })
