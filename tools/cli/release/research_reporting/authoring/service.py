"""Store graph-independent report components inside a branch Work Package."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from ..git import commit_work_package
from ..package_layout import ensure_branch_report_tree, safe_package_component
from ..document import (
    document_hash,
    load_bindings,
    load_document,
    new_bindings,
    new_document,
    save_bindings,
    save_document,
)
from ..document.chapter_sync import ensure_report_chapters


_DIRECTORY = "authoring"
_DOCUMENT = "DOCUMENT.json"
_BINDINGS = "BINDINGS.json"


def authoring_paths(package_root: Path, branch_id: str) -> dict[str, Path]:
    """Return the branch-owned, non-legacy authoring source paths."""
    branch_root = ensure_branch_report_tree(package_root, branch_id)
    root = branch_root / _DIRECTORY
    return {
        "root": root,
        "document": root / _DOCUMENT,
        "bindings": root / _BINDINGS,
    }


def ensure_branch_authoring(
    *, package_root: Path, work_package_id: str, branch_id: str,
    title: str, branch_ref: str, node_id: str = "", commit: bool = True,
) -> dict[str, Any]:
    """Create the branch authoring source and optionally its node chapter."""
    paths = authoring_paths(package_root, branch_id)
    document_path = paths["document"]
    bindings_path = paths["bindings"]
    if document_path.exists():
        document = load_document(document_path)
        bindings = load_bindings(bindings_path, document)
    else:
        document = new_document(
            _document_id(work_package_id, branch_id), title,
        )
        bindings = new_bindings(document)
    if node_id:
        document, bindings, chapter_sync = ensure_report_chapters(
            document,
            bindings,
            {
                "node": {"node_id": node_id},
                "research_scope": {"branch_ref": branch_ref},
            },
        )
    else:
        chapter_sync = _unchanged_sync()
    paths["root"].mkdir(parents=True, exist_ok=True)
    save_document(document_path, document)
    save_bindings(bindings_path, bindings, document)
    git = (
        commit_work_package(
            package_root,
            message="Update branch report authoring",
        )
        if commit
        else None
    )
    return {
        "paths": paths,
        "document": document,
        "bindings": bindings,
        "descriptor": _descriptor(
            package_root=package_root,
            work_package_id=work_package_id,
            branch_id=branch_id,
            document=document,
            bindings=bindings,
        ),
        "chapter_sync": chapter_sync,
        "git": git,
    }


def load_branch_authoring(
    *, package_root: Path, branch_id: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Path]]:
    """Load an existing branch authoring source without a legacy fallback."""
    paths = authoring_paths(package_root, branch_id)
    if not paths["document"].is_file() or not paths["bindings"].is_file():
        raise ValueError("branch authoring source is not initialized")
    document = load_document(paths["document"])
    return document, load_bindings(paths["bindings"], document), paths


def save_branch_authoring(
    *, package_root: Path, work_package_id: str, branch_id: str,
    document: dict[str, Any], bindings: dict[str, Any],
    message: str = "Update branch report authoring",
) -> dict[str, Any]:
    """Atomically save structured authoring data and commit the Work Package."""
    paths = authoring_paths(package_root, branch_id)
    paths["root"].mkdir(parents=True, exist_ok=True)
    saved = save_document(paths["document"], document)
    saved_bindings = save_bindings(paths["bindings"], bindings, saved)
    git = commit_work_package(package_root, message=message)
    return {
        "paths": paths,
        "document": saved,
        "bindings": saved_bindings,
        "descriptor": _descriptor(
            package_root=package_root,
            work_package_id=work_package_id,
            branch_id=branch_id,
            document=saved,
            bindings=saved_bindings,
        ),
        "git": git,
    }


def _descriptor(
    *, package_root: Path, work_package_id: str, branch_id: str,
    document: dict[str, Any], bindings: dict[str, Any],
) -> dict[str, Any]:
    paths = authoring_paths(package_root, branch_id)
    components = {
        item["component_id"]: item for item in document["components"]
    }
    section_refs = []
    for binding in bindings["bindings"]:
        data = binding.get("data") or {}
        if data.get("role") != "report_chapter":
            continue
        component = components.get(binding["component_id"])
        if component is None:
            continue
        section_refs.append({
            "link_id": binding["binding_id"],
            "kind": "report_section",
            "target_ref": data["chapter_ref"],
            "section_ref": component["component_id"],
            "label": component["title"],
        })
    return {
        "artifact_ref": (
            f"artifact:research/{work_package_id}/branches/{branch_id}/"
            f"authoring/{_DOCUMENT}"
        ),
        "format": "document",
        "status": "ready",
        "content_hash": document_hash(document),
        "local_ref": paths["document"].resolve().as_uri(),
        "index_ref": (package_root / "INDEX.json").resolve().as_uri(),
        "section_refs": section_refs,
    }


def _document_id(work_package_id: str, branch_id: str) -> str:
    return "authoring-" + safe_package_component(
        work_package_id, field="work_package_id",
    ) + "-" + safe_package_component(branch_id, field="branch_id")


def _unchanged_sync() -> dict[str, Any]:
    return deepcopy({
        "status": "synchronized",
        "created": [],
        "existing": [],
        "created_count": 0,
        "existing_count": 0,
    })
