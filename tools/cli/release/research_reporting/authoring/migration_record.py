"""Migrate one Profile research record into its branch Work Package."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..document import document_hash
from ..git import commit_work_package
from ..workspace_layout import ensure_work_package_layout
from .descriptor import authoring_descriptor
from .migration_files import (
    file_hashes, move_source, read_root_source, root_report_paths,
    verify_moved_source, verify_preserved,
)
from .paths import authoring_paths
from .service import ensure_branch_authoring, load_branch_authoring


MIGRATION_NAME = "root-report-to-branch-authoring-v1"


def migrate_record(
    profile: dict[str, Any], record: dict[str, Any], *, apply: bool,
) -> dict[str, Any]:
    package_root = Path(profile["workspace_root"]).expanduser() / "research" / str(record["record_id"])
    if not package_root.exists():
        return {"status": "skipped", "record_id": record["record_id"], "reason": "local_work_package_missing"}
    branch_id = branch_id_for(record)
    old_document, old_bindings = root_report_paths(package_root)
    source_present = old_document.exists()
    if old_bindings.exists() and not source_present:
        raise ValueError(f"root report bindings exist without REPORT.json: {package_root}")
    source = read_root_source(old_document, old_bindings) if source_present else None
    before = file_hashes(package_root)
    target = authoring_paths(package_root, branch_id)
    needs_write = source_present or not target["document"].is_file()
    if not apply:
        return {
            "status": "would_migrate" if needs_write else "ready",
            "record_id": record["record_id"], "branch_id": branch_id,
            "source_root_report": str(old_document) if source_present else "",
            "target_document": str(target["document"]),
            "preserved_file_count": len(before),
        }
    ensure_layout(profile, record, branch_id)
    if source is not None:
        target = move_source(
            package_root=package_root, branch_id=branch_id, source=source,
            old_document=old_document, old_bindings=old_bindings,
        )
    elif needs_write:
        ensure_branch_authoring(
            package_root=package_root, work_package_id=str(record["record_id"]),
            branch_id=branch_id, title=str(record["title"]),
            branch_ref=str(record["graph_branch_ref"]), commit=False,
        )
    document, bindings, _ = load_branch_authoring(
        package_root=package_root, branch_id=branch_id,
    )
    if source is not None:
        verify_moved_source(source, document, bindings)
    verify_preserved(before, file_hashes(package_root), old_document, old_bindings)
    descriptor = authoring_descriptor(
        package_root=package_root, work_package_id=str(record["record_id"]),
        branch_id=branch_id, document=document, bindings=bindings,
    )
    receipt = package_root / "migrations" / f"{MIGRATION_NAME}.{branch_id}.receipt.json"
    if needs_write or not receipt.exists():
        receipt = write_receipt(
            package_root=package_root, record=record, branch_id=branch_id,
            source=source, target=target, document=document,
            preserved_count=len(before),
        )
    git = commit_work_package(package_root, message="Migrate report into Work Package branch")
    return {
        "status": "migrated" if needs_write else "ready",
        "record_id": record["record_id"], "branch_id": branch_id,
        "source_root_report": str(old_document) if source is not None else "",
        "target_document": str(target["document"]), "receipt": str(receipt),
        "git": git, "record": updated_record(record, descriptor),
    }


def branch_id_for(record: dict[str, Any]) -> str:
    parts = str(record["graph_branch_ref"]).split(":")
    if len(parts) != 3 or parts[0] != "graph-branch" or not parts[2]:
        raise ValueError("research record Graph branch reference is invalid")
    return parts[2]


def ensure_layout(profile: dict[str, Any], record: dict[str, Any], branch_id: str) -> None:
    ensure_work_package_layout(
        workspace_root=Path(profile["workspace_root"]),
        work_package_id=str(record["record_id"]), branch_id=branch_id,
        workspace_id=str(record["workspace_ref"]).removeprefix("workspace:"),
        title=str(record["title"]), branch_ref=str(record["graph_branch_ref"]),
        status=str(record["status"]), factor_family_versions=list(record["factor_family_versions"]),
    )


def write_receipt(
    *, package_root: Path, record: dict[str, Any], branch_id: str,
    source: dict[str, Any] | None, target: dict[str, Path],
    document: dict[str, Any], preserved_count: int,
) -> Path:
    path = package_root / "migrations" / f"{MIGRATION_NAME}.{branch_id}.receipt.json"
    path.write_text(json.dumps({
        "schema_version": 1, "migration": MIGRATION_NAME,
        "record_id": record["record_id"], "branch_id": branch_id,
        "source_root_report": str(package_root / "REPORT.json") if source else "",
        "target_document": str(target["document"]),
        "document_hash": document_hash(document),
        "preserved_file_count": preserved_count,
    }, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def updated_record(record: dict[str, Any], descriptor: dict[str, Any]) -> dict[str, Any]:
    updated = dict(record)
    updated["artifacts"] = [
        item for item in record["artifacts"]
        if item.get("artifact_ref") != descriptor["artifact_ref"]
        and not _is_retired_root_document(item)
    ] + [descriptor]
    return updated


def _is_retired_root_document(item: dict[str, Any]) -> bool:
    """Remove the descriptor of the deleted root REPORT.json, not history."""
    return any(
        str(item.get(field) or "").endswith("/REPORT.json")
        for field in ("artifact_ref", "local_ref")
    )
