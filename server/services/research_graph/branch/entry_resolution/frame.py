"""Compact branch projection for obligation work caused by Graph reentry."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


def initial_entry_resolution_frame(
    descriptor: dict[str, Any],
    *,
    inherited_frame: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create an attached frame; it is not a business-state Graph node."""
    if descriptor.get("continuation_mode") != "same_node_reentry":
        return {}
    preflight = descriptor.get("requirement_preflight")
    if not isinstance(preflight, dict):
        return {}
    unresolved = _text_ids(preflight.get("assessment_required_ids"))
    value = {
        "schema_version": 1,
        "reason": "graph_continuation",
        "status": "pending" if unresolved else "resolved",
        "source_graph_version": int(
            descriptor.get("source_graph_version") or 0
        ),
        "target_graph_version": int(
            descriptor.get("target_graph_version") or 0
        ),
        "resume_node": str(descriptor.get("target_node") or ""),
        "requirement_delta_hash": str(preflight.get("delta_hash") or ""),
        "unresolved_requirement_ids": unresolved,
        "resolved_requirement_ids": [],
        "removed_requirement_ids": _text_ids(
            preflight.get("entry_removed_ids")
        ),
        "metadata_changed_requirement_ids": _text_ids(
            preflight.get("entry_metadata_changed_ids")
        ),
    }
    receipts = (
        inherited_frame.get("assessment_receipts")
        if isinstance(inherited_frame, dict)
        else None
    )
    if isinstance(receipts, list) and receipts:
        value["assessment_receipts"] = deepcopy(receipts)
    return value


def active_entry_requirement_ids(
    *, frame: dict[str, Any], current_node: str,
) -> list[str] | None:
    """Return the upgrade delta at its resume node; None means normal entry."""
    if (
        frame.get("schema_version") == 1
        and str(frame.get("resume_node") or "") == current_node
    ):
        return _text_ids(frame.get("unresolved_requirement_ids"))
    return None


def advance_entry_resolution_frame(
    *,
    frame: dict[str, Any],
    current_node: str,
    target_node: str,
    assessments: list[dict[str, Any]],
) -> dict[str, Any]:
    """Resolve changed requirements or retain them across a bounded detour."""
    value = deepcopy(frame)
    active = active_entry_requirement_ids(
        frame=value,
        current_node=current_node,
    )
    if active is None:
        return value
    by_id = {
        str(item.get("requirement_id") or ""): item
        for item in assessments
        if isinstance(item, dict)
    }
    resolved_now = {
        requirement_id
        for requirement_id in active
        if (
            by_id.get(requirement_id, {}).get("entry_effect") or {}
        ).get("status") in {"pass", "pass_limited"}
    }
    unresolved = sorted(set(active) - resolved_now)
    value["resolved_requirement_ids"] = sorted(set(
        _text_ids(value.get("resolved_requirement_ids"))
    ) | resolved_now)
    value["unresolved_requirement_ids"] = unresolved
    value["status"] = "pending" if unresolved else "resolved"
    if unresolved and target_node != current_node:
        value["detour_node"] = target_node
    else:
        value.pop("detour_node", None)
    return value


def compact_entry_resolution_frame(
    frame: dict[str, Any],
) -> dict[str, Any] | None:
    if frame.get("schema_version") != 1:
        return None
    value = {
        key: deepcopy(frame.get(key))
        for key in (
            "reason",
            "status",
            "source_graph_version",
            "target_graph_version",
            "resume_node",
            "requirement_delta_hash",
            "unresolved_requirement_ids",
            "removed_requirement_ids",
            "metadata_changed_requirement_ids",
            "reference_only_requirement_ids",
            "detour_node",
        )
        if key in frame
    }
    value["reused_requirement_count"] = len(
        _text_ids(frame.get("reused_requirement_ids"))
    )
    value["cached_receipt_count"] = len(
        frame.get("assessment_receipts") or []
    )
    return value


def entry_resolution_trace_delta(
    *, current_frame: dict[str, Any], projected_frame: dict[str, Any],
    current_node: str, target_node: str,
    assessments: list[dict[str, Any]],
    requirement_titles: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Persist only reportable change IDs; detailed bodies stay lazy."""
    assessed = sorted({
        str(item.get("requirement_id") or "")
        for item in assessments
        if isinstance(item, dict) and item.get("requirement_id")
    })
    reused = _text_ids(projected_frame.get("reused_requirement_ids"))
    reference_only = _text_ids(
        projected_frame.get("reference_only_requirement_ids")
    )
    unresolved = _text_ids(
        projected_frame.get("unresolved_requirement_ids")
    )
    titles = requirement_titles or {}
    item_ids = sorted(set(
        assessed + reused + reference_only + unresolved
    ))
    return {
        "schema_version": 1,
        "reason": str(
            current_frame.get("reason") or "node_entry"
        ),
        "from_node": current_node,
        "to_node": target_node,
        "assessed_requirement_ids": assessed,
        "reused_requirement_ids": reused,
        "reference_only_requirement_ids": reference_only,
        "unresolved_requirement_ids": unresolved,
        "items": [{
            "requirement_id": requirement_id,
            "title_zh": str(titles.get(requirement_id) or requirement_id),
            "assessed": requirement_id in assessed,
            "arrival_status": (
                "reused" if requirement_id in reused
                else "reference_only" if requirement_id in reference_only
                else "unresolved" if requirement_id in unresolved
                else "not_applicable"
            ),
        } for requirement_id in item_ids],
        "resume_node": str(projected_frame.get("resume_node") or ""),
    }


def _text_ids(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return sorted({str(item) for item in value if str(item)})
