"""Local branch binding for an isolated Graph continuation shadow."""

from __future__ import annotations

from pathlib import Path
import time
from typing import Any

from tools.cli.release.local_profile import LocalProfileStore
from tools.cli.release.research_branch_bindings import (
    owns_branch,
    with_branch_binding,
)
from tools.cli.release.research_reporting.authoring.tree_model import (
    load_snapshot,
)
from tools.cli.release.research_reporting.package_layout import (
    safe_package_component,
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
    """Attach a shadow branch to its existing logical Work Package."""
    store = LocalProfileStore(client_root)
    profile, agent = store.load_agent(profile_id, agent_id)
    if agent["role"] != "research":
        raise ValueError("Graph continuation requires a research Agent")
    source_ref = f"graph-branch:{source_instance_id}:{source_branch_id}"
    source_records = [
        item for item in profile["research_records"]
        if item["agent_id"] == agent_id and owns_branch(item, source_ref)
    ]
    if len(source_records) != 1:
        raise ValueError(
            "shadow continuation requires exactly one local source record"
        )
    source = source_records[0]
    source_work_package_id = safe_package_component(
        str(source["record_id"]), field="source Work Package id",
    )
    target_work_package_id = safe_package_component(
        target_work_package_id, field="target Work Package id",
    )
    target_branch_id = safe_package_component(
        target_branch_id, field="target branch_id",
    )
    if target_work_package_id != source_work_package_id:
        raise ValueError(
            "shadow continuation must retain the source Work Package"
        )
    target_ref = f"graph-branch:{target_instance_id}:{target_branch_id}"
    owners = [
        item for item in profile["research_records"]
        if owns_branch(item, target_ref)
    ]
    if owners and (
        len(owners) != 1 or owners[0]["record_id"] != source_work_package_id
    ):
        raise ValueError("shadow continuation local branch identity conflicts")
    workspace_root = Path(profile["workspace_root"]).expanduser()
    package_root = workspace_root / "research" / source_work_package_id
    if not package_root.is_dir():
        raise ValueError("source Work Package is not initialized locally")
    factor_versions = list(source["factor_family_versions"])
    if not factor_versions:
        factor_versions = _report_factor_refs(package_root, source_branch_id)
    if not factor_versions:
        raise ValueError(
            "source research has no frozen or report-bound factor identity"
        )
    updated = with_branch_binding(
        source,
        branch_ref=target_ref,
        kind="shadow_continuation",
        source_branch_ref=source_ref,
    )
    updated["factor_family_versions"] = factor_versions
    updated["updated_at"] = max(float(updated["updated_at"]), time.time())
    store.upsert_research_record(profile_id, updated)
    return {
        **updated,
        "source_work_package_id": source_work_package_id,
    }


def _report_factor_refs(
    package_root: Path,
    branch_id: str,
) -> list[str]:
    snapshot = load_snapshot(package_root=package_root, branch_id=branch_id)
    return sorted({
        str(item.get("target_ref") or "")
        for item in snapshot.get("bindings") or []
        if item.get("kind") in {"factor", "factor_family"}
        and str(item.get("target_ref") or "").startswith(
            ("factor-family:", "factor:")
        )
    })
