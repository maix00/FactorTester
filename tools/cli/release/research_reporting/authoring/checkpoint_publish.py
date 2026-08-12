"""Direct checkpoint publication into the one branch-owned report tree."""

from __future__ import annotations

from pathlib import Path
import hashlib
from typing import Any

from .checkpoint_operations import (
    checkpoint_operations,
    checkpoint_system_parent,
)
from .service import apply_branch_batch, commit_branch_authoring, ensure_branch_authoring
from .tree_descriptor import report_tree_descriptor
from .tree_presence import ReportTreePresence
from .tree_schema import digest


def publish_checkpoint_snapshot(
    *, package_root: Path, work_package_id: str, branch_id: str,
    branch_ref: str, title: str, node_id: str, snapshot: dict[str, Any],
    report_parent_id: str = "",
    entry_resolution_event: dict[str, Any] | None = None,
    checkpoint_ref: str = "",
) -> dict[str, Any]:
    """Append a validated Graph checkpoint without a report-side Journal."""
    # Stack events stay available from the Graph timeline. They are workflow
    # internals and must not become titled report content.
    _ = entry_resolution_event
    authoring = ensure_branch_authoring(
        package_root=package_root, work_package_id=work_package_id,
        branch_id=branch_id, title=title, branch_ref=branch_ref,
        node_id="" if report_parent_id else node_id, commit=False,
        materialize=bool(report_parent_id),
    )
    if report_parent_id:
        matches = [
            item for item in authoring["components"]
            if item["component_id"] == report_parent_id
            and item["kind"] in {"chapter", "special"}
        ]
        if len(matches) != 1:
            raise ValueError(
                "explicit report checkpoint parent is unavailable"
            )
        parent_id = report_parent_id
        parent_kind = str(matches[0]["kind"])
    else:
        parent_id = str(authoring["chapter_sync"]["component_id"])
        parent_kind = "chapter"
    presence = ReportTreePresence.load(
        package_root=package_root, branch_id=branch_id,
    )
    system_parent_id = checkpoint_system_parent(
        snapshot, default_parent_id=parent_id,
    )
    checkpoint_ops = checkpoint_operations(
        snapshot, parent_id=parent_id,
        parent_kind=parent_kind,
        component_exists=presence.component_exists,
        binding_exists=presence.binding_exists,
        asset_exists=presence.asset_exists,
    )
    receipt_ops = _checkpoint_receipt(
        (
            presence.bindings_for(system_parent_id)
            if presence.component_exists(system_parent_id)
            else []
        ),
        system_parent_id, snapshot,
        checkpoint_ref=checkpoint_ref,
    )
    operations = (
        [*checkpoint_ops, *receipt_ops]
        if system_parent_id != parent_id
        else [*receipt_ops, *checkpoint_ops]
    )
    saved = (
        apply_branch_batch(
            package_root=package_root, work_package_id=work_package_id,
            branch_id=branch_id, operations=operations, materialize=False,
        )
        if operations else authoring
    )
    git = commit_branch_authoring(
        package_root,
        message="Publish checkpoint report tree",
    )
    descriptor = report_tree_descriptor(
        package_root=package_root, work_package_id=work_package_id,
        branch_id=branch_id, head=saved["head"],
        section_refs=authoring["descriptor"]["section_refs"],
    )
    return {
        "changed": bool(
            operations or authoring["chapter_sync"]["created"]
        ),
        "operations": len(operations), "descriptor": descriptor,
        "generation": saved["head"]["generation"], "git": git,
    }


def _checkpoint_receipt(
    bindings: list[dict[str, Any]], chapter_id: str, snapshot: dict[str, Any],
    *, checkpoint_ref: str = "",
) -> list[dict[str, Any]]:
    refs = {
        str(link.get("target_ref") or "")
        for section in snapshot.get("sections") or []
        for link in section.get("links") or []
        if isinstance(link, dict) and link.get("kind") == "checkpoint"
    }
    if checkpoint_ref:
        refs.add(checkpoint_ref)
    if len(refs) != 1:
        raise ValueError("checkpoint snapshot requires one checkpoint reference")
    checkpoint_ref = refs.pop()
    snapshot_hash = digest(snapshot)
    existing = [
        item for item in bindings
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
        "op": "bind", "component_id": chapter_id,
        "binding": {
            "binding_id": binding_id, "kind": "checkpoint",
            "target_ref": checkpoint_ref, "label": "报告检查点",
            "data": {"role": "checkpoint_receipt", "snapshot_hash": snapshot_hash},
        },
    }]
