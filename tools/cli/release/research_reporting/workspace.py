"""Bootstrap a report-owned local authoring workspace."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .package_layout import PACKAGE_DIRECTORIES, ensure_branch_report_tree
from .authoring.tree_descriptor import report_tree_descriptor, section_refs_from_snapshot
from .authoring.tree_projection import load_snapshot
from .authoring.tree_model import initialize_tree
from .authoring.service import commit_branch_authoring
from .report_workspace_identity import (
    ensure_report_workspace_identity,
    load_report_workspace_identity,
)


def initialize_report_workspace(
    *,
    workspace_root: Path,
    report_workspace_id: str,
    branch_id: str,
    report_id: str = "",
    workspace_id: str,
    title: str,
    branch_ref: str,
    status: str = "pending",
    factor_family_versions: list[str] | None = None,
) -> dict[str, Any]:
    """Create the report's branch-owned authoring tree."""
    package_root = (
        Path(workspace_root).expanduser() / "research" / report_workspace_id
    )
    for relative in PACKAGE_DIRECTORIES:
        (package_root / relative).mkdir(parents=True, exist_ok=True)
    branch_root = ensure_branch_report_tree(package_root, branch_id)

    if not report_id:
        try:
            identity = load_report_workspace_identity(package_root)
            report_id = str(identity["report_id"])
        except (OSError, ValueError):
            report_id = f"report-{report_workspace_id}"
    identity = ensure_report_workspace_identity(
        package_root, report_workspace_id=report_workspace_id,
        report_id=report_id,
        workspace_id=workspace_id, title=title,
    )
    initialized = initialize_tree(
        package_root=package_root, branch_id=branch_id,
        report_id=str(identity["report_id"]), title=title,
    )
    descriptor = report_tree_descriptor(
        package_root=package_root, report_workspace_id=report_workspace_id,
        branch_id=branch_id, head=initialized["head"],
        section_refs=section_refs_from_snapshot(load_snapshot(package_root=package_root, branch_id=branch_id)),
    )
    git = commit_branch_authoring(
        package_root,
        message="Initialize report authoring tree",
    )
    return {
        "package_root": package_root,
        "branch_root": branch_root,
        "head_path": initialized["paths"]["head"],
        "descriptor": descriptor,
        "git": git,
        "initialized": initialized["created"],
    }
