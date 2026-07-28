"""One-shot conversion of retired report documents into branch report trees."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .export import export_branch_report
from .legacy_import import equivalent_to_document, import_document_source
from .legacy_inventory import (
    journals, projection_branches, retired_root_paths, verify_projection_ownership,
)
from .legacy_projections import verify_legacy_projections
from .legacy_sources import discover_document_sources, retire_source, source_receipt
from .migration_steps import (
    ensure_tree, import_journal, missing_head_branches,
    retire_legacy_projections, write_receipt,
)
from .service import ensure_branch_authoring
from ..git import commit_work_package


MIGRATION_NAME = "retired-report-sources-to-tree-v4"


def migrate_record(
    profile: dict[str, Any], record: dict[str, Any], *, apply: bool,
) -> dict[str, Any]:
    package = (
        Path(profile["workspace_root"]).expanduser()
        / "research" / str(record["record_id"])
    )
    if not package.is_dir():
        return {
            "status": "skipped", "record_id": record["record_id"],
            "reason": "local_work_package_missing",
        }
    primary = branch_id_for(record)
    sources = discover_document_sources(package, primary_branch_id=primary)
    journal_paths = journals(package)
    projection_branch_ids = projection_branches(package)
    branch_ids = sorted({
        primary, *(item["branch_id"] for item in sources),
        *(path.parent.name for path in journal_paths),
    })
    pending = missing_head_branches(package, branch_ids)
    needed = bool(
        sources or journal_paths or projection_branch_ids or pending
        or retired_root_paths(package)
    )
    if not apply:
        return _result(
            "would_migrate" if needed else "ready", record, primary,
            sources, pending, journal_paths, projection_branch_ids,
        )
    verify_projection_ownership(journal_paths, projection_branch_ids)
    verify_legacy_projections(journal_paths)
    for branch_id in branch_ids:
        ensure_tree(profile, record, package, branch_id)
    for source in sources:
        snapshot = import_document_source(
            package_root=package, branch_id=source["branch_id"],
            document=source["document"], bindings=source["bindings"],
        )
        if not equivalent_to_document(snapshot, source["document"], source["bindings"]):
            raise ValueError("migrated report tree differs from retired document")
    for journal in journal_paths:
        import_journal(package, str(record["record_id"]), journal)
    rendered = [export_branch_report(
        package_root=package, work_package_id=str(record["record_id"]),
        branch_id=branch,
        message="Migrate retired report documents to report tree",
        commit=False,
    ) for branch in branch_ids]
    _verify_exported(package, branch_ids)
    for source in sources:
        retire_source(source)
    retire_legacy_projections(package, journal_paths)
    receipt_path = package / "migrations" / f"{MIGRATION_NAME}.json"
    receipt = (
        write_receipt(
            package, name=MIGRATION_NAME, record=record,
            sources=[source_receipt(item) for item in sources],
            branches=branch_ids, journals=journal_paths,
        )
        if needed or not receipt_path.is_file() else receipt_path
    )
    current = next(item for item in rendered if item["branch_id"] == primary)
    descriptor = ensure_branch_authoring(
        package_root=package, work_package_id=str(record["record_id"]),
        branch_id=primary, title=str(record["title"]),
        branch_ref=str(record["graph_branch_ref"]), commit=False,
    )["descriptor"]
    result = _result(
        "migrated" if needed else "ready", record, primary, sources, pending,
        journal_paths, projection_branch_ids,
    )
    final_git = commit_work_package(package, message="Record report tree migration")
    result.update({
        "receipt": str(receipt), "report_path": str(current["path"]),
        "git": final_git or current["git"],
        "record": _updated_record(record, descriptor),
    })
    return result


def branch_id_for(record: dict[str, Any]) -> str:
    parts = str(record["graph_branch_ref"]).split(":")
    if len(parts) != 3 or parts[0] != "graph-branch" or not parts[2]:
        raise ValueError("research record Graph branch reference is invalid")
    return parts[2]


def _verify_exported(package: Path, branch_ids: list[str]) -> None:
    for branch_id in branch_ids:
        if not (package / "branches" / branch_id / "REPORT.md").is_file():
            raise ValueError("report tree export is missing")


def _updated_record(record: dict[str, Any], descriptor: dict[str, Any]) -> dict[str, Any]:
    result = dict(record)
    result["artifacts"] = [
        item for item in record["artifacts"]
        if not str(item.get("artifact_ref") or "").endswith("/REPORT.json")
        and item.get("artifact_ref") != descriptor["artifact_ref"]
    ] + [descriptor]
    return result


def _result(
    status: str, record: dict[str, Any], branch: str, sources: list[dict[str, Any]],
    pending: list[str], journals: list[Path] | None = None,
    projection_branches: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "status": status, "record_id": record["record_id"],
        "branch_id": branch,
        "sources": [source_receipt(item) for item in sources],
        "journals": [str(path) for path in journals or []],
        "projection_branches": list(projection_branches or []),
        "missing_heads": pending,
    }
