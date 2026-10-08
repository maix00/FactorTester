"""Small pure builders for the local Report Workspace skeleton."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def initial_index(
    *, report_workspace_id: str, workspace_id: str, branch_id: str,
    branch_ref: str, title: str, status: str,
    factor_family_versions: list[str],
) -> dict[str, Any]:
    branch_report_ref = (
        f"artifact:research/{report_workspace_id}/branches/{branch_id}/REPORT.md"
    )
    source_hash = hashlib.sha256(json.dumps({
        "report_workspace_id": report_workspace_id,
        "branch_ref": branch_ref,
        "title": title,
    }, sort_keys=True).encode()).hexdigest()
    branch_payload = empty_branch_report(
        title=title, report_workspace_id=report_workspace_id,
        branch_id=branch_id, branch_ref=branch_ref, status=status,
    )
    return {
        "schema_version": 2,
        "workspace_id": workspace_id,
        "report_workspace_id": report_workspace_id,
        "branches": [{
            "branch_id": branch_id, "title": title, "status": status,
            "source_hash": source_hash,
            "content_hash": hashlib.sha256(branch_payload).hexdigest(),
            "report_ref": branch_report_ref, "media_type": "text/markdown",
            "factor_family_versions": list(factor_family_versions),
            "evidence_refs": [], "asset_refs": [],
            "decision_contract_hash": hashlib.sha256(b"").hexdigest(),
        }],
        "sections": [], "omitted_section_count": 0,
        "assets_ref": f"artifact:research/{report_workspace_id}/assets/",
    }


def empty_branch_report(
    *, title: str, report_workspace_id: str, branch_id: str,
    branch_ref: str, status: str,
) -> bytes:
    lines = [f"# {title}", ""]
    if status:
        lines.extend([f"- 状态：`{status}`", ""])
    return "\n".join(lines).encode("utf-8")


def snapshot_identity(
    *, workspace_id: str, report_workspace_id: str, branch_id: str,
    title: str, status: str, factor_family_versions: list[str],
) -> dict[str, Any]:
    """Minimal valid snapshot used solely to validate an existing index."""
    return {
        "schema_version": 1, "workspace_id": workspace_id,
        "report_workspace_id": report_workspace_id, "branch_id": branch_id,
        "title": title, "status": status, "product_group": "cnfutures",
        "methodology_hash": "0" * 64,
        "decision_contract_hash": "0" * 64,
        "factor_family_versions": factor_family_versions, "evidence_refs": [],
        "sections": [{
            "section_id": "migration-bootstrap", "title": "迁移初始化",
            "body": "", "evidence_refs": [], "asset_refs": [],
            "links": [], "created_at": 0.0,
        }],
        "assets": [], "gaps": [],
    }
