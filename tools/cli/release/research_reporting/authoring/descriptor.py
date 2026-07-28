"""Local artifact descriptors for branch Work Package report sources."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..document import document_hash
from .paths import authoring_paths


def authoring_descriptor(
    *, package_root: Path, work_package_id: str, branch_id: str,
    document: dict[str, Any], bindings: dict[str, Any],
) -> dict[str, Any]:
    paths = authoring_paths(package_root, branch_id)
    components = {item["component_id"]: item for item in document["components"]}
    section_refs = []
    for binding in bindings["bindings"]:
        data = binding.get("data") or {}
        if data.get("role") != "report_chapter":
            continue
        component = components.get(binding["component_id"])
        if component is None:
            continue
        section_refs.append({
            "link_id": binding["binding_id"], "kind": "report_section",
            "target_ref": data["chapter_ref"],
            "section_ref": component["component_id"],
            "label": component["title"],
        })
    return {
        "artifact_ref": (
            f"artifact:research/{work_package_id}/branches/{branch_id}/"
            "authoring/DOCUMENT.json"
        ),
        "format": "document", "status": "ready",
        "content_hash": document_hash(document),
        "local_ref": paths["document"].resolve().as_uri(),
        "index_ref": (package_root / "INDEX.json").resolve().as_uri(),
        "section_refs": section_refs,
    }
