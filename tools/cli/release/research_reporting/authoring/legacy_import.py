"""One-shot import of the retired document-plus-bindings report source."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .tree_model import apply_batch, load_snapshot


_BATCH_SIZE = 128


def import_document_source(
    *, package_root: Path, branch_id: str, document: dict[str, Any],
    bindings: dict[str, Any],
) -> dict[str, Any]:
    """Copy a validated v2 document into the immutable tree without loss.

    The caller must have initialized the target tree.  A non-empty target is
    accepted only if it already carries the same visible content, making a
    completed migration safe to retry after interruption.
    """
    current = load_snapshot(package_root=package_root, branch_id=branch_id)
    if current["components"] or current["head"]["assets"]:
        if not equivalent_to_document(current, document, bindings):
            raise ValueError("report tree already has different visible content")
        return current
    links_by_component: dict[str, list[dict[str, Any]]] = {}
    for item in bindings["bindings"]:
        links_by_component.setdefault(item["component_id"], []).append({
            "binding_id": item["binding_id"], "kind": item["kind"],
            "target_ref": item["target_ref"], "label": item["label"],
            "data": item["data"],
        })
    operations = [
        {"op": "asset", "asset": item} for item in document["assets"]
    ]
    operations.extend({
        "op": "add", "component_id": item["component_id"],
        "kind": item["kind"], "title": item["title"],
        "parent_id": item["parent_id"], "body": item["body"],
        "content": item["content"], "display_kind": item["display_kind"],
        "bindings": links_by_component.get(item["component_id"], []),
    } for item in document["components"])
    for offset in range(0, len(operations), _BATCH_SIZE):
        apply_batch(
            package_root=package_root,
            branch_id=branch_id,
            operations=operations[offset:offset + _BATCH_SIZE],
            include_snapshot=False,
        )
    return load_snapshot(package_root=package_root, branch_id=branch_id)


def equivalent_to_document(
    snapshot: dict[str, Any], document: dict[str, Any],
    bindings: dict[str, Any],
) -> bool:
    """Compare the visible report model, ignoring generated tree timestamps."""
    source_components = [
        {
            key: item[key]
            for key in (
                "component_id", "kind", "parent_id", "title", "body",
                "content", "display_kind",
            )
        }
        for item in document["components"]
    ]
    tree_components = [
        {
            key: item[key]
            for key in (
                "component_id", "kind", "parent_id", "title", "body",
                "content", "display_kind",
            )
        }
        for item in snapshot["components"]
    ]
    source_bindings = [
        {
            key: item[key]
            for key in (
                "binding_id", "component_id", "kind", "target_ref", "label",
                "data",
            )
        }
        for item in bindings["bindings"]
    ]
    tree_bindings = [
        {
            key: item[key]
            for key in (
                "binding_id", "component_id", "kind", "target_ref", "label",
                "data",
            )
        }
        for item in snapshot["bindings"]
    ]
    return (
        tree_components == source_components
        and tree_bindings == source_bindings
        and snapshot["head"]["assets"] == document["assets"]
    )
