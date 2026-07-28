"""Direct checkpoint publication into the one branch-owned report tree."""

from __future__ import annotations

from pathlib import Path
import hashlib
from typing import Any

from .checkpoint_operations import checkpoint_operations
from .service import apply_branch_batch, commit_branch_authoring, ensure_branch_authoring
from .tree_descriptor import report_tree_descriptor
from .tree_schema import digest


def publish_checkpoint_snapshot(
    *, package_root: Path, work_package_id: str, branch_id: str,
    branch_ref: str, title: str, node_id: str, snapshot: dict[str, Any],
) -> dict[str, Any]:
    """Append a validated Graph checkpoint without a report-side Journal."""
    authoring = ensure_branch_authoring(
        package_root=package_root, work_package_id=work_package_id,
        branch_id=branch_id, title=title, branch_ref=branch_ref,
        node_id=node_id, commit=False,
    )
    parent_id = _node_chapter(authoring, node_id)
    operations = _checkpoint_receipt(authoring, parent_id, snapshot)
    operations.extend(checkpoint_operations(
        snapshot, parent_id=parent_id,
        existing_ids={item["component_id"] for item in authoring["components"]},
        existing_bindings={item["binding_id"] for item in authoring["bindings"]},
        existing_assets={item["asset_ref"] for item in authoring["head"]["assets"]},
    ))
    saved = (
        apply_branch_batch(
            package_root=package_root, work_package_id=work_package_id,
            branch_id=branch_id, operations=operations,
        )
        if operations else authoring
    )
    git = commit_branch_authoring(
        package_root,
        message="Publish checkpoint report tree",
    )
    descriptor = report_tree_descriptor(
        package_root=package_root, work_package_id=work_package_id,
        branch_id=branch_id, snapshot=saved,
    )
    return {
        "changed": bool(operations or authoring["chapter_sync"]["created"]),
        "operations": len(operations), "descriptor": descriptor,
        "generation": saved["head"]["generation"], "git": git,
    }


def _node_chapter(authoring: dict[str, Any], node_id: str) -> str:
    expected = f"node:{node_id}"
    for binding in authoring["bindings"]:
        data = binding.get("data") or {}
        if data.get("role") == "report_chapter" and data.get("chapter_ref") == expected:
            return str(binding["component_id"])
    raise ValueError("checkpoint report node chapter is unavailable")


def _checkpoint_receipt(
    authoring: dict[str, Any], chapter_id: str, snapshot: dict[str, Any],
) -> list[dict[str, Any]]:
    refs = {
        str(link.get("target_ref") or "")
        for section in snapshot.get("sections") or []
        for link in section.get("links") or []
        if isinstance(link, dict) and link.get("kind") == "checkpoint"
    }
    if len(refs) != 1:
        raise ValueError("checkpoint snapshot requires one checkpoint reference")
    checkpoint_ref = refs.pop()
    snapshot_hash = digest(snapshot)
    existing = [
        item for item in authoring["bindings"]
        if item.get("kind") == "checkpoint"
        and item.get("target_ref") == checkpoint_ref
        and (item.get("data") or {}).get("role") == "checkpoint_receipt"
    ]
    if existing:
        if len(existing) != 1 or existing[0]["data"].get("snapshot_hash") != snapshot_hash:
            raise ValueError("checkpoint has conflicting narrative")
        return []
    binding_id = "checkpoint-" + hashlib.sha256(checkpoint_ref.encode()).hexdigest()[:48]
    return [{
        "op": "chip", "component_id": chapter_id,
        "binding": {
            "binding_id": binding_id, "kind": "checkpoint",
            "target_ref": checkpoint_ref, "label": "报告检查点",
            "data": {"role": "checkpoint_receipt", "snapshot_hash": snapshot_hash},
        },
    }]
