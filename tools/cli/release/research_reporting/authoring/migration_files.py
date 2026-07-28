"""Byte-preserving file operations used by Work Package report migration."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any

from ..document import (
    bindings_path_for,
    document_hash,
    load_bindings,
    load_document,
    new_bindings,
    save_bindings,
)
from .paths import authoring_paths
from .service import load_branch_authoring


def root_report_paths(package_root: Path) -> tuple[Path, Path]:
    document = package_root / "REPORT.json"
    return document, bindings_path_for(document)


def read_root_source(document_path: Path, bindings_path: Path) -> dict[str, Any]:
    document = load_document(document_path)
    bindings = (
        load_bindings(bindings_path, document)
        if bindings_path.exists() else new_bindings(document)
    )
    return {"document": document, "bindings": bindings}


def move_source(
    *, package_root: Path, branch_id: str, source: dict[str, Any],
    old_document: Path, old_bindings: Path,
) -> dict[str, Path]:
    target = authoring_paths(package_root, branch_id)
    target["root"].mkdir(parents=True, exist_ok=True)
    if target["document"].exists():
        existing, existing_bindings, _ = load_branch_authoring(
            package_root=package_root, branch_id=branch_id,
        )
        if (
            document_hash(existing) != document_hash(source["document"])
            or existing_bindings != source["bindings"]
        ):
            raise ValueError("branch authoring already exists with different content")
        old_document.unlink()
        if old_bindings.exists():
            old_bindings.unlink()
        _remove_old_locks(old_document, old_bindings)
        return target
    os.replace(old_document, target["document"])
    if old_bindings.exists():
        os.replace(old_bindings, target["bindings"])
    else:
        save_bindings(target["bindings"], source["bindings"], source["document"])
    _remove_old_locks(old_document, old_bindings)
    return target


def verify_moved_source(
    source: dict[str, Any], document: dict[str, Any], bindings: dict[str, Any],
) -> None:
    if document_hash(document) != document_hash(source["document"]):
        raise ValueError("migrated report document hash differs from source")
    if bindings != source["bindings"]:
        raise ValueError("migrated report bindings differ from source")


def file_hashes(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file() and ".git" not in path.relative_to(root).parts
    }


def verify_preserved(
    before: dict[str, str], after: dict[str, str], old_document: Path,
    old_bindings: Path,
) -> None:
    root = old_document.parent
    removed = {
        str(old_document.relative_to(root)), str(old_bindings.relative_to(root)),
        str(old_document.with_suffix(old_document.suffix + ".lock").relative_to(root)),
        str(old_bindings.with_suffix(old_bindings.suffix + ".lock").relative_to(root)),
    }
    changed = {
        path for path, digest in before.items()
        if path not in removed and after.get(path) != digest
    }
    if changed:
        raise ValueError(
            "migration changed pre-existing Work Package files: "
            + ", ".join(sorted(changed))
        )


def _remove_old_locks(document: Path, bindings: Path) -> None:
    """Discard only locks owned by the removed root report source."""
    for path in (document, bindings):
        lock = path.with_suffix(path.suffix + ".lock")
        if lock.exists():
            lock.unlink()
