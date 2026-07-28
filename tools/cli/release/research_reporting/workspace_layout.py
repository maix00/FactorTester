"""Non-destructive Work Package layout completion for migrations."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .package_layout import PACKAGE_DIRECTORIES, ensure_branch_report_tree
from .writer import index as report_index
from .writer.aggregate import render_work_package_report
from .workspace_schema import empty_branch_report, initial_index, snapshot_identity


def ensure_work_package_layout(
    *, workspace_root: Path, work_package_id: str, branch_id: str,
    workspace_id: str, title: str, branch_ref: str, status: str = "pending",
    factor_family_versions: list[str] | None = None,
) -> dict[str, Any]:
    """Fill missing layout only; never rewrite existing reports or user files."""
    package_root = Path(workspace_root).expanduser() / "research" / work_package_id
    for relative in PACKAGE_DIRECTORIES:
        (package_root / relative).mkdir(parents=True, exist_ok=True)
    branch_root = ensure_branch_report_tree(package_root, branch_id)
    versions = factor_family_versions or []
    index_path = package_root / "INDEX.json"
    if not index_path.exists():
        index_path.write_bytes(report_index.encode_index(initial_index(
            work_package_id=work_package_id, workspace_id=workspace_id,
            branch_id=branch_id, branch_ref=branch_ref, title=title,
            status=status, factor_family_versions=versions,
        )))
    branch_report = branch_root / "REPORT.md"
    if not branch_report.exists():
        branch_report.write_bytes(empty_branch_report(
            title=title, work_package_id=work_package_id, branch_id=branch_id,
            branch_ref=branch_ref, status=status,
        ))
    root_report = package_root / "REPORT.md"
    if not root_report.exists():
        root_report.write_bytes(render_work_package_report(report_index.load_index(
            index_path,
            snapshot_identity(
                workspace_id=workspace_id, work_package_id=work_package_id,
                branch_id=branch_id, title=title, status=status,
                factor_family_versions=versions,
            ),
        )))
    return {
        "package_root": package_root, "branch_root": branch_root,
        "index_path": index_path, "branch_report_path": branch_report,
    }
