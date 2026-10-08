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
    scope: BranchReportScope, *, materialize: bool = True,
    persist: bool = True,
) -> dict[str, Any]:
    """Create the exact branch source, then persist its descriptor locally."""
    result = ensure_branch_authoring(
        package_root=scope.package_root,
        report_workspace_id=scope.report_workspace_id,
        branch_id=scope.branch_id,
        title=scope.title,
        branch_ref=scope.branch_ref,
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
            report_workspace_id=scope.report_workspace_id,
            branch_id=scope.branch_id,
            head=snapshot["head"],
            section_refs=section_refs_from_snapshot(snapshot),
        ),
    }


def persist_descriptor(scope: BranchReportScope, descriptor: dict[str, Any]) -> None:
    _replace_descriptor(scope, descriptor)


def _replace_descriptor(scope: BranchReportScope, descriptor: dict[str, Any]) -> None:
    # The branch HEAD is authoritative; no Profile-side research index is kept.
    del scope, descriptor
