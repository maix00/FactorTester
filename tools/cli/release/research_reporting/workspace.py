"""Bootstrap and maintain the on-disk Work Package workspace."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .package_layout import PACKAGE_DIRECTORIES, ensure_branch_report_tree
from .authoring.tree_descriptor import report_tree_descriptor
from .authoring.tree_model import initialize_tree
from .authoring.service import commit_branch_authoring
from .work_package_identity import ensure_work_package_identity


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

    identity = ensure_work_package_identity(
        package_root, work_package_id=work_package_id,
    )
    initialized = initialize_tree(
        package_root=package_root, branch_id=branch_id,
        report_id=str(identity["report_id"]), title=title,
    )
    descriptor = report_tree_descriptor(
        package_root=package_root, work_package_id=work_package_id,
        branch_id=branch_id, head=initialized["head"],
    )
    git = commit_branch_authoring(
        package_root,
        message="Initialize Work Package report tree",
    )
    return {
        "package_root": package_root,
        "branch_root": branch_root,
        "head_path": initialized["paths"]["head"],
        "descriptor": descriptor,
        "git": git,
        "initialized": initialized["created"],
    }
