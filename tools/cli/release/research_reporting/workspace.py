"""Bootstrap and maintain the on-disk Work Package workspace."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from .git import commit_work_package
from .package_layout import PACKAGE_DIRECTORIES, ensure_branch_report_tree
from .writer import index as report_index
from .writer.aggregate import render_work_package_report
from .workspace_schema import empty_branch_report, initial_index


def initialize_work_package(
    *,
    workspace_root: Path,
    work_package_id: str,
    branch_id: str,
    workspace_id: str,
    title: str,
    branch_ref: str,
    status: str = "pending",
    factor_family_versions: list[str] | None = None,
) -> dict[str, Any]:
    """Create an empty but complete Work Package before its first checkpoint."""
    package_root = (
        Path(workspace_root).expanduser() / "research" / work_package_id
    )
    for relative in PACKAGE_DIRECTORIES:
        (package_root / relative).mkdir(parents=True, exist_ok=True)
    branch_root = ensure_branch_report_tree(package_root, branch_id)

    index = initial_index(
        work_package_id=work_package_id,
        workspace_id=workspace_id,
        branch_id=branch_id,
        branch_ref=branch_ref,
        title=title,
        status=status,
        factor_family_versions=factor_family_versions or [],
    )
    index_path = package_root / "INDEX.json"
    index_path.write_bytes(report_index.encode_index(index))
    branch_path = branch_root / "REPORT.md"
    branch_path.write_bytes(empty_branch_report(
        title=title,
        work_package_id=work_package_id,
        branch_id=branch_id,
        branch_ref=branch_ref,
        status=status,
    ))
    (package_root / "REPORT.md").write_bytes(
        render_work_package_report(index)
    )
    git = commit_work_package(
        package_root,
        message="Initialize research Work Package",
    )
    descriptor = {
        "artifact_ref": (
            f"artifact:research/{work_package_id}/branches/{branch_id}/REPORT.md"
        ),
        "format": "markdown",
        "status": "ready",
        "content_hash": hashlib.sha256(branch_path.read_bytes()).hexdigest(),
        "local_ref": branch_path.resolve().as_uri(),
        "index_ref": index_path.resolve().as_uri(),
        "section_refs": [],
    }
    return {
        "package_root": package_root,
        "branch_root": branch_root,
        "branch_report_path": branch_path,
        "index_path": index_path,
        "descriptor": descriptor,
        "git": git,
        "initialized": True,
    }
