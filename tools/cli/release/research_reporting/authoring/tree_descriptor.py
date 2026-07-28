"""Profile-facing descriptors derived from a report tree HEAD revision."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .tree_paths import report_tree_paths
from .tree_schema import digest


def report_tree_descriptor(*, package_root: Path, work_package_id: str, branch_id: str, snapshot: dict[str, Any]) -> dict[str, Any]:
    paths = report_tree_paths(package_root, branch_id)
    section_refs = []
    components = {
        item["component_id"] for item in snapshot.get("components") or []
    }
    for binding in snapshot.get("bindings") or []:
        data = binding.get("data") or {}
        if data.get("role") != "report_chapter":
            continue
        if binding["component_id"] in components:
            section_refs.append({
                "link_id": binding["binding_id"], "kind": "report_section",
                "target_ref": data["chapter_ref"],
                "section_ref": binding["component_id"],
                "label": binding["label"],
            })
    return {
        "artifact_ref": f"artifact:research/{work_package_id}/branches/{branch_id}/authoring/HEAD.json",
        "format": "report_tree", "status": "ready",
        "content_hash": digest(snapshot["head"]),
        "local_ref": paths["head"].resolve().as_uri(),
        "section_refs": section_refs,
    }
