"""将目录报告初始化为现有的 Profile 报告树，不依赖 Graph 或因子工作区。"""

from __future__ import annotations

import hashlib
import time
from pathlib import Path

from tools.cli.release.local_profile import LocalProfileStore
from .work_package_identity import ensure_work_package_identity
from .workspace import initialize_work_package


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
    package_id = "report-" + hashlib.sha256(report_id.encode()).hexdigest()[:24]
    branch_id = "main"
    root = Path(profile["workspace_root"]).expanduser()
    package_root = root / "research" / package_id
    ensure_work_package_identity(package_root, work_package_id=package_id, report_id=report_id)
    tree = initialize_work_package(
        workspace_root=root, work_package_id=package_id, branch_id=branch_id,
        workspace_id=report["workspace_id"], title=report["title"],
        branch_ref=f"report-branch:{branch_id}",
    )
    existing = next((item for item in profile["research_records"]
                     if item["record_id"] == package_id), None)
    if existing is None:
        now = time.time()
        store.upsert_research_record(profile_id, {
            "record_id": package_id, "title": report["title"], "status": "pending",
            "scope": {"profile_id": profile_id, "research_id": report["research_id"]},
            "factor_family_versions": [], "agent_id": profile_id,
            "created_at": now, "updated_at": now,
            "workspace_ref": "workspace:" + report["workspace_id"], "run_ref": "",
            "graph_instance_ref": f"work-package:{package_id}",
            "graph_branch_ref": "", "branch_bindings": [], "checkpoint_ref": "",
            "evidence_refs": [], "artifacts": [tree["descriptor"]], "timeline_refs": [],
            "provenance": {"created_by": "factortester research report-create",
                           "research_id": report["research_id"], "report_id": report_id},
        })
    return {**report, "work_package_id": package_id, "branch_id": branch_id,
            "source_ref": f"{profile_id}:{package_id}:{branch_id}"}
