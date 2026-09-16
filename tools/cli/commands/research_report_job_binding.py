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
    trial_binding: dict[str, Any] | None = None,
    report_parent_id: str = "",
) -> dict[str, Any]:
    """Return immutable local report identity without guessing a report scope.

    ``trial_binding=None`` freezes an ordinary run's mount: the work package and
    branch come from the scope and the parent component from the caller, so a
    job never has to carry a TrialPlan just to appear in a report.
    """
    if trial_binding is None or str(trial_binding.get("binding_origin") or "") == "agent_direct":
        return _freeze_direct_report_binding(
            scope,
            report_parent_id=report_parent_id,
            binding_origin="agent_direct" if trial_binding is not None else "report_direct",
        )
    branch_ref = scope.branch_ref.split(":")
    if len(branch_ref) != 3 or branch_ref[0] != "graph-branch":
        raise ValueError("新任务只能绑定当前 Graph 分支，不能绑定历史报告分支")
    instance_id = branch_ref[1]
    if (
        str(trial_binding.get("instance_id") or "") != instance_id
        or str(trial_binding.get("branch_id") or "") != scope.branch_id
    ):
        raise ValueError("Trial binding 与报告的 Graph 分支不一致")
    head = load_authoring(scope)["head"]
    return {
        "profile_ref": f"profile:{scope.profile_id}",
        "work_package_ref": f"work-package:{scope.work_package_id}",
        "instance_id": instance_id,
        "branch_id": scope.branch_id,
        "report_id": str(head["report_id"]),
        "report_generation": int(head["generation"]),
        "report_head_hash": digest(head),
    }


def _freeze_direct_report_binding(
    scope: BranchReportScope,
    *,
    report_parent_id: str,
    binding_origin: str = "agent_direct",
) -> dict[str, Any]:
    parent_id = str(report_parent_id or "").strip()
    if not parent_id:
        raise ValueError("图外报告绑定需要明确的 report parent_id")
    presence = ReportTreePresence.load(
        package_root=scope.package_root,
        branch_id=scope.branch_id,
    )
    if not presence.component_exists(parent_id):
        raise ValueError("报告绑定的 parent_id 不存在")
    if presence.component_kind(parent_id) not in {
        "chapter", "section", "subsection", "special",
    }:
        raise ValueError("图外报告绑定的 parent_id 必须是报告 container")
    head = load_authoring(scope)["head"]
    return {
        "binding_origin": binding_origin,
        "profile_ref": f"profile:{scope.profile_id}",
        "work_package_ref": f"work-package:{scope.work_package_id}",
        "branch_id": scope.branch_id,
        "report_id": str(head["report_id"]),
        "report_generation": int(head["generation"]),
        "report_head_hash": digest(head),
        "report_parent_id": parent_id,
    }
