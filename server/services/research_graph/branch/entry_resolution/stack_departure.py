"""Resolve or route the active entry-attempt frame."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .stack_state import canonical_entry_resolution_state, text_ids


def advance_active_frame(
    *,
    state: Any,
    current_node: str,
    target_node: str,
    assessments: list[dict[str, Any]],
) -> dict[str, Any]:
    value = canonical_entry_resolution_state(state)
    if not value["frames"]:
        return value
    top = deepcopy(value["frames"][-1])
    if str(top["target_node"]) != current_node:
        return value
    active = text_ids(top.get("unresolved_entry_requirement_refs"))
    by_id = {
        str(item.get("requirement_id") or ""): item
        for item in assessments
        if isinstance(item, dict)
    }
    resolved = {
        item
        for item in active
        if (by_id.get(item, {}).get("entry_effect") or {}).get("status")
        in {"pass", "pass_limited"}
    }
    unresolved = sorted(set(active) - resolved)
    top["resolved_entry_requirement_refs"] = sorted(
        set(text_ids(top.get("resolved_entry_requirement_refs"))) | resolved
    )
    top["unresolved_entry_requirement_refs"] = unresolved
    routes = {
        _selected_route(
            str((by_id[item].get("resolution") or {}).get("route") or "")
        )
        for item in unresolved
        if item in by_id
    } - {""}
    if len(routes) == 1:
        top["selected_route"] = next(iter(routes))
    completion_refs = {
        str(reference)
        for requirement_id in resolved
        for reference in (
            (by_id[requirement_id].get("resolution") or {}).get(
                "validation_refs"
            )
            or []
        )
        if str(reference)
    }
    if completion_refs:
        top["completion_refs"] = sorted({
            *text_ids(top.get("completion_refs")),
            *completion_refs,
        })
    if not unresolved:
        top["status"] = "resolved"
    elif target_node != current_node:
        top["status"] = "waiting"
    else:
        top["status"] = "resolving"
    value["frames"][-1] = top
    return value


def _selected_route(value: str) -> str:
    return {
        "existing_evidence": "existing_capability",
        "cli_evidence": "existing_capability",
        "trial": "trial",
        "capability_gap": "capability_gap",
        "bounded_unknown": "paused_other",
    }.get(value, "")
