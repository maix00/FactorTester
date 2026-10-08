"""Non-destructive Report Workspace layout completion for migrations."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .package_layout import PACKAGE_DIRECTORIES, ensure_branch_report_tree


def ensure_report_workspace_layout(
    *, workspace_root: Path, report_workspace_id: str, branch_id: str,
    workspace_id: str, title: str, branch_ref: str, status: str = "pending",
    factor_family_versions: list[str] | None = None,
) -> dict[str, Any]:
    """Fill missing layout only; never rewrite existing reports or user files."""
    package_root = Path(workspace_root).expanduser() / "research" / report_workspace_id
    for relative in PACKAGE_DIRECTORIES:
        (package_root / relative).mkdir(parents=True, exist_ok=True)
    branch_root = ensure_branch_report_tree(package_root, branch_id)
    return {
        "package_root": package_root, "branch_root": branch_root,
    }
