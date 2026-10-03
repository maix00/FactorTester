"""将目录报告初始化为现有的 Profile 报告树，不依赖 Graph 或因子工作区。"""

from __future__ import annotations

from pathlib import Path

from tools.cli.release.local_profile import LocalProfileStore
from .report_workspace_identity import (
    ensure_report_workspace_identity,
    report_workspace_id_for,
)
from .workspace import initialize_report_workspace


def initialize_report_space(store: LocalProfileStore, profile_id: str, report: dict) -> dict:
    """使用报告身份派生稳定载体；重试复用同一树，不创建第二份报告。"""
    profile = store.load(profile_id)
    owner = str((profile.get("session_binding") or {}).get("principal_ref") or "")
    if not owner or owner != report.get("owner_ref"):
        raise ValueError("报告所有者与当前 Profile 主体不一致")
    if report.get("profile_ref") != profile_id or profile.get("status") != "active":
        raise ValueError("报告不属于当前活动 Profile")
    report_id = str(report.get("report_id") or "")
    if not report_id or not report.get("workspace_id"):
        raise ValueError("报告缺少 report_id 或 workspace_id")
    report_workspace_id = report_workspace_id_for(report_id)
    branch_id = "main"
    root = Path(profile["workspace_root"]).expanduser()
    report_root = root / "research" / report_workspace_id
    ensure_report_workspace_identity(
        report_root, report_workspace_id=report_workspace_id,
        report_id=report_id, workspace_id=report["workspace_id"],
        title=report["title"],
    )
    tree = initialize_report_workspace(
        workspace_root=root, report_workspace_id=report_workspace_id,
        report_id=report_id, branch_id=branch_id,
        workspace_id=report["workspace_id"], title=report["title"],
        branch_ref=f"report-branch:{branch_id}",
    )
    return {
        **report,
        "report_workspace_id": report_workspace_id,
        "branch_id": branch_id,
        "source_ref": f"{profile_id}:{report_workspace_id}:{branch_id}",
        "authoring_root": str(tree["package_root"]),
    }
