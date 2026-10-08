"""Freeze one local report HEAD for an explicitly report-bound ResearchRun."""

from __future__ import annotations

from typing import Any

from tools.cli.release.research_reporting.authoring.tree_schema import digest
from tools.cli.release.research_reporting.authoring.tree_presence import (
    ReportTreePresence,
)
from .research_report_scope import BranchReportScope, load_authoring


def freeze_report_binding(
    scope: BranchReportScope,
    *,
    report_parent_id: str = "",
) -> dict[str, Any]:
    """Freeze the report tree identity independently of run methodology."""
    parent_id = str(report_parent_id or "").strip()
    if not parent_id:
        raise ValueError("报告绑定必须明确提供 report parent_id")
    presence = ReportTreePresence.load(
        package_root=scope.package_root,
        branch_id=scope.branch_id,
    )
    if not presence.component_exists(parent_id):
        raise ValueError("报告绑定的 parent_id 不存在")
    if presence.component_kind(parent_id) not in {
        "chapter", "section", "subsection", "special",
    }:
        raise ValueError("报告绑定的 parent_id 必须是报告 container")
    head = load_authoring(scope)["head"]
    return {
        "profile_ref": f"profile:{scope.profile_id}",
        "report_workspace_id": scope.report_workspace_id,
        "branch_id": scope.branch_id,
        "report_id": str(head["report_id"]),
        "report_generation": int(head["generation"]),
        "report_head_hash": digest(head),
        "report_parent_id": parent_id,
    }
