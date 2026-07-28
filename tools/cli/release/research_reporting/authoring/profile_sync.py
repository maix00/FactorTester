"""Profile-bound node chapter creation inside a Work Package branch."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .service import ensure_branch_authoring


def ensure_branch_report_chapter(
    *, workspace_root: Path, work_package_id: str, title: str,
    node_id: str, branch_id: str, branch_ref: str,
) -> dict[str, Any]:
    """Create the current node chapter in its branch-owned authoring source."""
    package_root = Path(workspace_root).expanduser() / "research" / work_package_id
    if not (package_root / "INDEX.json").is_file():
        raise ValueError("Work Package is not initialized locally")
    result = ensure_branch_authoring(
        package_root=package_root,
        work_package_id=work_package_id,
        branch_id=branch_id,
        title=title,
        branch_ref=branch_ref,
        node_id=node_id,
        commit=False,
    )
    # A graph node chapter must be visible immediately in the branch report,
    # rather than waiting for a later report-specific command to render it.
    from ..writer import render_branch_authoring_report

    rendered = render_branch_authoring_report(
        package_root=package_root,
        work_package_id=work_package_id,
        branch_id=branch_id,
    )
    return {**result, "rendered": rendered}
