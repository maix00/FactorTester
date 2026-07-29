"""Resolve a branch-owned report source from local Profile state."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tools.cli.release.local_profile import LocalProfileStore
from tools.cli.release.research_reporting.authoring import (
    ensure_branch_authoring,
    load_branch_authoring,
)
from tools.cli.release.research_reporting.authoring.tree_descriptor import (
    merge_section_refs,
    report_tree_descriptor,
    section_refs_from_snapshot,
)
from .research_report_scope_identity import (
    BranchReportScope,
    resolve_branch_report_scope,
    resolve_history_migration_scope,
)


def ensure_authoring(
    scope: BranchReportScope, *, node_id: str = "", materialize: bool = True,
    persist: bool = True,
) -> dict[str, Any]:
    """Create the exact branch source, then persist its descriptor locally."""
    result = ensure_branch_authoring(
        package_root=scope.package_root,
        work_package_id=scope.work_package_id,
        branch_id=scope.branch_id,
        title=scope.record["title"],
        branch_ref=scope.branch_ref,
        node_id=node_id,
        commit=False,
        materialize=materialize,
    )
    if persist:
        _replace_descriptor(scope, result["descriptor"])
    return result


def load_authoring(scope: BranchReportScope) -> dict[str, Any]:
    """Load the branch source after the caller has explicitly initialized it."""
    return load_branch_authoring(
        package_root=scope.package_root, branch_id=scope.branch_id,
    )


def load_current_authoring(scope: BranchReportScope) -> dict[str, Any]:
    """Materialize the current HEAD and derive its complete descriptor."""
    snapshot = load_authoring(scope)
    return {
        **snapshot,
        "descriptor": report_tree_descriptor(
            package_root=scope.package_root,
            work_package_id=scope.work_package_id,
            branch_id=scope.branch_id,
            head=snapshot["head"],
            section_refs=section_refs_from_snapshot(snapshot),
        ),
    }


def persist_descriptor(scope: BranchReportScope, descriptor: dict[str, Any]) -> None:
    _replace_descriptor(scope, descriptor)


def _replace_descriptor(scope: BranchReportScope, descriptor: dict[str, Any]) -> None:
    record = dict(scope.record)
    existing = next((
        item for item in record["artifacts"]
        if item.get("artifact_ref") == descriptor["artifact_ref"]
    ), None)
    if isinstance(existing, dict):
        descriptor = {
            **descriptor,
            "section_refs": merge_section_refs(
                existing.get("section_refs") or [], descriptor["section_refs"],
            ),
        }
    record["artifacts"] = [
        item for item in record["artifacts"]
        if item["artifact_ref"] != descriptor["artifact_ref"]
    ] + [descriptor]
    LocalProfileStore(scope.client_root).upsert_research_record(
        scope.profile_id, record,
    )
