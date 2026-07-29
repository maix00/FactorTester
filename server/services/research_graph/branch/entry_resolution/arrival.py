"""Project target-node entry work onto the canonical return stack."""

from __future__ import annotations

from typing import Any

from .projection import project_entry_attempt
from .receipts import project_node_entry_resolution
from .stack_routing import project_target_frame
from .stack_state import canonical_entry_resolution_state, text_ids


def project_arrival_state(
    *,
    previous_state: dict[str, Any],
    graph: dict[str, Any],
    target_node: str,
    checkpoint: dict[str, Any] | None,
    scope: dict[str, str],
    origin_ref: str,
    current_node: str,
    retain_target_frame: bool = False,
) -> dict[str, Any]:
    state = canonical_entry_resolution_state(previous_state)
    receipt_carrier = {
        "assessment_receipts": state["assessment_receipts"],
    }
    provisional = project_node_entry_resolution(
        previous_frame=receipt_carrier,
        graph=graph,
        target_node=target_node,
        checkpoint=checkpoint,
        scope=scope,
    )
    state["assessment_receipts"] = provisional.get(
        "assessment_receipts", []
    )
    frame = project_entry_attempt(
        graph=graph,
        target_node=target_node,
        checkpoint=checkpoint,
        origin_ref=origin_ref,
        unresolved_requirement_refs=text_ids(
            provisional.get("unresolved_requirement_ids")
        ),
        resolved_requirement_refs=text_ids(
            provisional.get("resolved_requirement_ids")
        ),
    )
    reused = text_ids(provisional.get("reused_requirement_ids"))
    reference_only = text_ids(
        provisional.get("reference_only_requirement_ids")
    )
    if reused:
        frame["reused_entry_requirement_refs"] = reused
    if reference_only:
        frame["reference_only_entry_requirement_refs"] = reference_only
    completion_refs = _receipt_refs(
        receipts=state["assessment_receipts"],
        target_node=target_node,
        requirement_refs=reused,
    )
    if completion_refs:
        frame["completion_refs"] = completion_refs
    if retain_target_frame:
        return _retain_current_target(state, frame)
    return project_target_frame(
        state=state,
        target_frame=frame,
        current_node=current_node,
        target_node=target_node,
    )


def _retain_current_target(
    state: dict[str, Any],
    frame: dict[str, Any],
) -> dict[str, Any]:
    if not frame["entry_requirement_refs"]:
        return state
    matches = [
        index
        for index, item in enumerate(state["frames"])
        if item["target_node"] == frame["target_node"]
    ]
    if matches:
        existing = state["frames"][matches[-1]]
        if existing.get("resume_guard_hash") == frame.get("resume_guard_hash"):
            frame["entry_attempt_id"] = existing["entry_attempt_id"]
        state["frames"] = [*state["frames"][: matches[-1]], frame]
    else:
        state["frames"].append(frame)
    return state


def _receipt_refs(
    *,
    receipts: list[dict[str, Any]],
    target_node: str,
    requirement_refs: list[str],
) -> list[str]:
    selected = set(requirement_refs)
    return sorted({
        "entry-assessment-receipt:" + str(item["receipt_hash"])
        for item in receipts
        if item.get("entry_node") == target_node
        and item.get("requirement_id") in selected
        and item.get("receipt_hash")
    })
