"""Resolve a local Profile's report workspace and one report branch."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tools.cli.release.local_profile import LocalProfileStore
from tools.cli.release.research_reporting.authoring.tree_store import load_head
from tools.cli.release.research_reporting.authoring.tree_paths import report_tree_paths
from tools.cli.release.research_reporting.report_workspace_identity import (
    load_report_workspace_identity,
)


@dataclass(frozen=True)
class BranchReportScope:
    client_root: Path
    profile_id: str
    profile: dict[str, Any]
    report_workspace_id: str
    report_id: str
    title: str
    branch_id: str
    package_root: Path
    branch_ref: str


def resolve_branch_report_scope(
    *, client_root: Path,
    profile_id: str,
    report_workspace_id: str,
    branch_id: str,
) -> BranchReportScope:
    """Resolve a report branch from its independent workspace identity."""
    profile = LocalProfileStore(client_root).load(profile_id)
    return _scope(
        client_root=client_root,
        profile_id=profile_id,
        profile=profile,
        report_workspace_id=report_workspace_id,
        branch_id=branch_id,
    )


def resolve_history_migration_scope(
    *, client_root: Path, profile_id: str, report_workspace_id: str,
    branch_id: str,
) -> BranchReportScope:
    """Resolve an existing report branch for an explicit metadata migration."""
    return resolve_branch_report_scope(
        client_root=client_root,
        profile_id=profile_id,
        report_workspace_id=report_workspace_id,
        branch_id=branch_id,
    )


def _scope(
    *, client_root: Path,
    profile_id: str,
    profile: dict[str, Any],
    report_workspace_id: str,
    branch_id: str,
) -> BranchReportScope:
    if not report_workspace_id or "/" in report_workspace_id or "\\" in report_workspace_id:
        raise ValueError("report_workspace_id is invalid")
    if not branch_id or "/" in branch_id or "\\" in branch_id:
        raise ValueError("branch_id is invalid")
    root = Path(profile["workspace_root"]).expanduser() / "research" / report_workspace_id
    if not root.is_dir():
        raise ValueError("report workspace is not initialized locally")
    identity = load_report_workspace_identity(root)
    if identity["report_workspace_id"] != report_workspace_id:
        raise ValueError("report workspace identity does not match its directory")
    title = str(identity.get("title") or "")
    head_path = root / "branches" / branch_id / "authoring" / "HEAD.json"
    if head_path.is_file():
        head = load_head(report_tree_paths(root, branch_id))
        if head["report_id"] != identity["report_id"]:
            raise ValueError("report branch identity does not match its workspace")
        title = str(head["title"] or title)
    return BranchReportScope(
        client_root=client_root,
        profile_id=profile_id,
        profile=profile,
        report_workspace_id=report_workspace_id,
        report_id=identity["report_id"],
        title=title,
        branch_id=branch_id,
        package_root=root,
        branch_ref=f"report-branch:{branch_id}",
    )
