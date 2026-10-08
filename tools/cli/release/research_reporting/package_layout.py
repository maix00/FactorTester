"""Paths for the physical, local representation of a Report Workspace."""

from __future__ import annotations

from pathlib import Path
import re


PACKAGE_DIRECTORIES = (
    "assets",
    "artifacts",
    "branches",
    "migrations",
    "proposals",
    "protocol",
)

_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


def safe_package_component(value: str, *, field: str) -> str:
    """Validate an identifier before it is used as a package path component."""
    if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
        raise ValueError(f"{field} must be a safe identifier")
    return value


def ensure_branch_report_tree(package_root: Path, branch_id: str) -> Path:
    """Materialize one ReportBranch's local report tree.

    This is deliberately a normal directory within one Report Workspace Git
    repository, not a Git worktree. Git records atomic snapshots of the Report
    workspace after genuine report writes.
    """
    branch_id = safe_package_component(branch_id, field="branch_id")
    branch_root = Path(package_root) / "branches" / branch_id
    branch_root.mkdir(parents=True, exist_ok=True)
    return branch_root
