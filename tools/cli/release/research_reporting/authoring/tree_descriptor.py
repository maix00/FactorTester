"""Profile-facing descriptors derived from a report tree HEAD revision."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .tree_paths import report_tree_paths
from .tree_schema import digest


def report_tree_descriptor(
    *, package_root: Path, report_workspace_id: str, branch_id: str,
    head: dict[str, Any], section_refs: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    paths = report_tree_paths(package_root, branch_id)
    return {
        "artifact_ref": f"artifact:research/{report_workspace_id}/branches/{branch_id}/authoring/HEAD.json",
        "format": "report_tree", "status": "ready",
        "content_hash": digest(head),
        "local_ref": paths["head"].resolve().as_uri(),
        "section_refs": section_refs or [],
    }


def section_refs_from_snapshot(snapshot: dict[str, Any]) -> list[dict[str, str]]:
    components = {item["component_id"] for item in snapshot.get("components") or []}
    refs = []
    for binding in snapshot.get("bindings") or []:
        data = binding.get("data") or {}
        if data.get("role") != "report_chapter":
            continue
        if binding["component_id"] in components:
            refs.append({
                "link_id": binding["binding_id"], "kind": "report_section",
                "target_ref": data["chapter_ref"],
                "section_ref": binding["component_id"],
                "label": binding["label"],
            })
    return refs


def merge_section_refs(
    existing: list[dict[str, Any]], updates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    refs = {
        str(item.get("target_ref") or ""): item
        for item in existing if isinstance(item, dict) and item.get("target_ref")
    }
    refs.update({
        str(item.get("target_ref") or ""): item
        for item in updates if isinstance(item, dict) and item.get("target_ref")
    })
    return list(refs.values())
