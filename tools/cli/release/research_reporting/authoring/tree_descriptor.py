"""Profile-facing descriptors derived from a report tree HEAD revision."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .tree_paths import report_tree_paths
from .tree_schema import digest


def report_tree_descriptor(*, package_root: Path, work_package_id: str, branch_id: str, snapshot: dict[str, Any]) -> dict[str, Any]:
    paths = report_tree_paths(package_root, branch_id)
    section_refs = []
    components = {item["component_id"]: item for item in snapshot["components"]}
    for binding in snapshot["bindings"]:
        data = binding.get("data") or {}
        if data.get("role") != "report_chapter":
            continue
        component = components.get(binding["component_id"])
        if component is not None:
            section_refs.append({
                "link_id": binding["binding_id"], "kind": "report_section",
                "target_ref": data["chapter_ref"], "section_ref": component["component_id"],
                "label": component["title"],
            })
    return {
        "artifact_ref": f"artifact:research/{work_package_id}/branches/{branch_id}/authoring/HEAD.json",
        "format": "report_tree", "status": "ready",
        "content_hash": digest(snapshot["head"]),
        "local_ref": paths["head"].resolve().as_uri(),
        "index_ref": (package_root / "INDEX.json").resolve().as_uri(),
        "section_refs": section_refs,
    }
