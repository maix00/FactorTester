"""Migrate a retired root report into its branch-owned immutable tree."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from ..document import (
    bindings_path_for,
    document_hash,
    load_bindings,
    load_document,
)
from ..workspace_layout import ensure_work_package_layout
from .legacy_import import equivalent_to_document, import_document_source
from .service import ensure_branch_authoring


MIGRATION_NAME = "root-report-to-report-tree-v2"


def migrate_record(
    profile: dict[str, Any], record: dict[str, Any], *, apply: bool,
) -> dict[str, Any]:
    package_root = (
        Path(profile["workspace_root"]).expanduser()
        / "research" / str(record["record_id"])
    )
    if not package_root.exists():
        return _skipped(record, "local_work_package_missing")
    branch_id = branch_id_for(record)
    source_path = package_root / "REPORT.json"
    bindings_path = bindings_path_for(source_path)
    if bindings_path.exists() and not source_path.exists():
        raise ValueError("root report bindings exist without REPORT.json")
    source = _source(source_path, bindings_path) if source_path.exists() else None
    target_head = package_root / "branches" / branch_id / "authoring" / "HEAD.json"
    needs_write = source is not None or not target_head.exists()
    if not apply:
        return {
            "status": "would_migrate" if needs_write else "ready",
            "record_id": record["record_id"], "branch_id": branch_id,
            "source_root_report": str(source_path) if source else "",
            "target_head": str(target_head),
        }

    ensure_layout(profile, record, branch_id)
    result = ensure_branch_authoring(
        package_root=package_root,
        work_package_id=str(record["record_id"]),
        branch_id=branch_id,
        title=str(record["title"]),
        branch_ref=str(record["graph_branch_ref"]),
        commit=False,
    )
    if source is not None:
        snapshot = import_document_source(
            package_root=package_root,
            branch_id=branch_id,
            document=source["document"],
            bindings=source["bindings"],
        )
        if not equivalent_to_document(
            snapshot, source["document"], source["bindings"],
        ):
            raise ValueError("migrated report tree differs from source document")
        result = ensure_branch_authoring(
            package_root=package_root,
            work_package_id=str(record["record_id"]),
            branch_id=branch_id,
            title=str(record["title"]),
            branch_ref=str(record["graph_branch_ref"]),
            commit=False,
        )

    receipt = _receipt_path(package_root, branch_id)
    if needs_write or not receipt.exists():
        receipt = _write_receipt(
            package_root=package_root,
            record=record,
            branch_id=branch_id,
            source_path=source_path if source else None,
            bindings_path=bindings_path if source else None,
            source=source,
            target_head=target_head,
            revision=result["head"]["revision"],
        )
    if source is not None:
        _retire_source(source_path, bindings_path)
    from ..writer import render_branch_authoring_report

    rendered = render_branch_authoring_report(
        package_root=package_root,
        work_package_id=str(record["record_id"]),
        branch_id=branch_id,
    )
    return {
        "status": "migrated" if needs_write else "ready",
        "record_id": record["record_id"], "branch_id": branch_id,
        "source_root_report": str(source_path) if source else "",
        "target_head": str(target_head), "receipt": str(receipt),
        "git": rendered["git"],
        "record": _updated_record(record, result["descriptor"]),
        "report_path": str(rendered["path"]),
    }


def branch_id_for(record: dict[str, Any]) -> str:
    parts = str(record["graph_branch_ref"]).split(":")
    if len(parts) != 3 or parts[0] != "graph-branch" or not parts[2]:
        raise ValueError("research record Graph branch reference is invalid")
    return parts[2]


def ensure_layout(
    profile: dict[str, Any], record: dict[str, Any], branch_id: str,
) -> None:
    ensure_work_package_layout(
        workspace_root=Path(profile["workspace_root"]),
        work_package_id=str(record["record_id"]),
        branch_id=branch_id,
        workspace_id=str(record["workspace_ref"]).removeprefix("workspace:"),
        title=str(record["title"]),
        branch_ref=str(record["graph_branch_ref"]),
        status=str(record["status"]),
        factor_family_versions=list(record["factor_family_versions"]),
    )


def _source(document_path: Path, bindings_path: Path) -> dict[str, Any]:
    document = load_document(document_path)
    bindings = load_bindings(bindings_path, document)
    return {"document": document, "bindings": bindings}


def _write_receipt(
    *, package_root: Path, record: dict[str, Any], branch_id: str,
    source_path: Path | None, bindings_path: Path | None,
    source: dict[str, Any] | None, target_head: Path, revision: int,
) -> Path:
    path = _receipt_path(package_root, branch_id)
    payload = {
        "schema_version": 1,
        "migration": MIGRATION_NAME,
        "record_id": record["record_id"],
        "branch_id": branch_id,
        "source_root_report": str(source_path) if source_path else "",
        "source_document_hash": (
            document_hash(source["document"]) if source else ""
        ),
        "source_bindings_hash": (
            _digest(source["bindings"]) if source else ""
        ),
        "target_head": str(target_head),
        "target_revision": revision,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _receipt_path(package_root: Path, branch_id: str) -> Path:
    return package_root / "migrations" / f"{MIGRATION_NAME}.{branch_id}.json"


def _retire_source(document_path: Path, bindings_path: Path) -> None:
    """Remove only the superseded root source after tree equivalence passed."""
    document_path.unlink()
    bindings_path.unlink()
    for path in (document_path, bindings_path):
        lock = path.with_suffix(path.suffix + ".lock")
        if lock.exists():
            lock.unlink()


def _updated_record(record: dict[str, Any], descriptor: dict[str, Any]) -> dict[str, Any]:
    result = dict(record)
    result["artifacts"] = [
        item for item in record["artifacts"]
        if not _retired_root_artifact(item)
        and item.get("artifact_ref") != descriptor["artifact_ref"]
    ] + [descriptor]
    return result


def _retired_root_artifact(item: dict[str, Any]) -> bool:
    return any(
        str(item.get(field) or "").endswith("/REPORT.json")
        for field in ("artifact_ref", "local_ref")
    )


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode()).hexdigest()


def _skipped(record: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "status": "skipped", "record_id": record["record_id"],
        "reason": reason,
    }
