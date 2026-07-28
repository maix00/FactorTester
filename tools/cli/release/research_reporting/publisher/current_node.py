"""Publish substantive current-node report items without a Journal."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from ..report_items import report_fragment_hash
from .carrier import MAX_ITEMS
from .current_node_carrier import current_node_carrier
from .current_node_history import branch_history, item_identity, publication_clock
from .current_node_narrative import narrative
from .service import publish_research_checkpoint


def publish_current_node_report_checkpoint(
    *, client_root: Path, profile_id: str, agent_id: str,
    carrier: dict[str, Any], projection: dict[str, Any],
) -> dict[str, Any]:
    """Publish new report items as an additive same-node checkpoint."""
    submission, ordered = _ordered_items(projection)
    history, record, artifact = branch_history(
        client_root=client_root, profile_id=profile_id, agent_id=agent_id,
        carrier=carrier,
    )
    local = [item for item in ordered if item_identity(item) not in history]
    if not local:
        if artifact is None:
            raise ValueError("local research record has no report-tree artifact")
        return {
            "changed": False, "report_changed": False, "profile_changed": False,
            "checkpoint_ref": record["checkpoint_ref"], "artifact": artifact,
            "report_submission": submission,
            "report_artifact_ref": artifact["artifact_ref"],
        }
    compact = _submission(submission, local)
    checkpoint_ref = "report-checkpoint:sha256:" + _checkpoint_hash(carrier, compact)
    previous, recorded_at = publication_clock(
        client_root=client_root, profile_id=profile_id, agent_id=agent_id,
        carrier=carrier, checkpoint_ref=checkpoint_ref,
        minimum=float((carrier.get("latest_transition") or {}).get("created_at") or 0),
    )
    item_refs = list(dict.fromkeys(
        str(link["target_ref"]) for item in local
        for link in item.get("links") or []
    ))
    synthetic = current_node_carrier(
        carrier, checkpoint_ref=checkpoint_ref, predecessor_ref=previous,
        recorded_at=recorded_at, submission=compact, item_refs=item_refs,
    )
    result = publish_research_checkpoint(
        client_root=client_root, profile_id=profile_id, agent_id=agent_id,
        carrier=synthetic,
        narrative=narrative(local, recorded_at=recorded_at, current_node=str(carrier.get("current_node") or "")),
        local_reference_allowlist=tuple(item_refs[MAX_ITEMS:]),
    )
    return {**result, "report_submission": submission, "report_artifact_ref": result["artifact"]["artifact_ref"]}


def _ordered_items(projection: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    submission, local = projection.get("report_submission"), projection.get("local_report_items")
    if not isinstance(submission, dict) or not isinstance(local, list):
        raise ValueError("entry projection needs report_submission and local_report_items")
    by_hash = {str(item.get("item_hash") or ""): item for item in local if isinstance(item, dict)}
    projected = submission.get("items")
    if not isinstance(projected, list) or not projected or len(by_hash) != len(projected):
        raise ValueError("entry projection report items are incomplete")
    ordered = []
    for item in projected:
        if not isinstance(item, dict):
            raise ValueError("entry projection report item is invalid")
        full = by_hash.get(str(item.get("item_hash") or ""))
        fields = ("report_requirement_id", "subject_ref", "content_kind", "item_hash")
        if full is None or any(str(full.get(field) or "") != str(item.get(field) or "") for field in fields):
            raise ValueError("local report content does not match projection")
        ordered.append(full)
    return submission, ordered


def _submission(submission: dict[str, Any], items: list[dict[str, Any]]) -> dict[str, Any]:
    projected = [{key: item[key] for key in ("report_requirement_id", "subject_ref", "content_kind", "item_hash")} for item in items]
    return {"schema_version": submission["schema_version"], "fragment_hash": report_fragment_hash(projected), "items": projected}


def _checkpoint_hash(carrier: dict[str, Any], submission: dict[str, Any]) -> str:
    value = {"base_checkpoint_ref": carrier.get("checkpoint_ref"), "fragment_hash": submission["fragment_hash"], "items": submission["items"]}
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
