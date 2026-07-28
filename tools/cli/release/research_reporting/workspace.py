"""Bootstrap and maintain the on-disk Work Package workspace."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .git import commit_work_package
from .writer import index as report_index
from .writer.aggregate import render_work_package_report


PACKAGE_DIRECTORIES = (
    "assets",
    "artifacts",
    "branches",
    "migrations",
    "proposals",
    "protocol",
)


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
    branch_root = package_root / "branches" / branch_id
    sections_root = branch_root / "sections"
    for relative in PACKAGE_DIRECTORIES:
        (package_root / relative).mkdir(parents=True, exist_ok=True)
    sections_root.mkdir(parents=True, exist_ok=True)

    index = _initial_index(
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
    branch_path.write_bytes(_empty_branch_report(
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


def _initial_index(
    *, work_package_id: str, workspace_id: str, branch_id: str,
    branch_ref: str, title: str, status: str,
    factor_family_versions: list[str],
) -> dict[str, Any]:
    branch_report_ref = (
        f"artifact:research/{work_package_id}/branches/{branch_id}/REPORT.md"
    )
    source_hash = hashlib.sha256(
        json.dumps({
            "work_package_id": work_package_id,
            "branch_ref": branch_ref,
            "title": title,
        }, sort_keys=True).encode()
    ).hexdigest()
    branch_payload = _empty_branch_report(
        title=title, work_package_id=work_package_id,
        branch_id=branch_id, branch_ref=branch_ref,
        status=status,
    )
    return {
        "schema_version": 2,
        "workspace_id": workspace_id,
        "work_package_id": work_package_id,
        "branches": [{
            "branch_id": branch_id,
            "title": title,
            "status": status,
            "source_hash": source_hash,
            "content_hash": hashlib.sha256(branch_payload).hexdigest(),
            "report_ref": branch_report_ref,
            "media_type": "text/markdown",
            "factor_family_versions": list(factor_family_versions),
            "evidence_refs": [],
            "asset_refs": [],
            "decision_contract_hash": hashlib.sha256(
                b""
            ).hexdigest(),
            "trial_plan_hash": "",
        }],
        "sections": [],
        "omitted_section_count": 0,
        "assets_ref": f"artifact:research/{work_package_id}/assets/",
    }


def _empty_branch_report(
    *, title: str, work_package_id: str, branch_id: str,
    branch_ref: str, status: str,
) -> bytes:
    lines = [f"# {title}", ""]
    if status:
        lines.extend([f"- 状态：`{status}`", ""])
    return "\n".join(lines).encode("utf-8")
