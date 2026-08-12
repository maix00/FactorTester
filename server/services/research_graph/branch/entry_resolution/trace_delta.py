"""Requirement-row delta kept separate from stack lifecycle events."""

from __future__ import annotations

from typing import Any

from .stack_state import active_frame, text_ids


def entry_resolution_trace_delta(
    *,
    current_frame: dict[str, Any],
    projected_frame: dict[str, Any],
    current_node: str,
    target_node: str,
    assessments: list[dict[str, Any]],
    requirement_titles: dict[str, str] | None = None,
) -> dict[str, Any]:
    current = active_frame(current_frame) or {}
    projected = active_frame(projected_frame) or {}
    preflight = current.get("continuation_preflight") or {}
    assessed = sorted({
        str(item.get("requirement_id") or "")
        for item in assessments
        if isinstance(item, dict) and item.get("requirement_id")
    })
    reused = text_ids(projected.get("reused_entry_requirement_refs"))
    reference_only = text_ids(
        projected.get("reference_only_entry_requirement_refs")
    )
    unresolved = text_ids(
        projected.get("unresolved_entry_requirement_refs")
    )
    titles = requirement_titles or {}
    added = set(text_ids(preflight.get("added_requirement_ids")))
    revised = set(text_ids(preflight.get("revised_requirement_ids")))
    metadata = set(text_ids(
        preflight.get("metadata_changed_requirement_ids")
    ))
    effects = {
        str(item.get("requirement_id") or ""): str(
            (item.get("entry_effect") or {}).get("status") or ""
        )
        for item in assessments
        if isinstance(item, dict) and item.get("requirement_id")
    }
    item_ids = sorted(set(assessed + reused + reference_only + unresolved))
    return {
        "schema_version": 1,
        "reason": str(preflight.get("reason") or "node_entry"),
        "from_node": current_node,
        "to_node": target_node,
        "assessed_requirement_ids": assessed,
        "reused_requirement_ids": reused,
        "reference_only_requirement_ids": reference_only,
        "unresolved_requirement_ids": unresolved,
        "items": [
            _item(
                requirement_id=item_id,
                title=str(titles.get(item_id) or item_id),
                assessed=item_id in assessed,
                change_kind=(
                    "added" if item_id in added
                    else "revised" if item_id in revised
                    else "metadata_only" if item_id in metadata
                    else "unchanged"
                ),
                status=(
                    "reused" if item_id in reused
                    else "reference_only" if item_id in reference_only
                    else "unresolved" if item_id in unresolved
                    else "assessed_limited" if effects.get(item_id)
                    == "pass_limited"
                    else "assessed_pass" if effects.get(item_id) == "pass"
                    else "not_applicable"
                ),
            )
            for item_id in item_ids
        ],
        "resume_node": str(projected.get("target_node") or target_node),
    }


def _item(
    *, requirement_id: str, title: str, assessed: bool,
    change_kind: str, status: str,
) -> dict[str, Any]:
    return {
        "requirement_id": requirement_id,
        "title_zh": title,
        "assessed": assessed,
        "change_kind": change_kind,
        "resolution_status": status,
    }
