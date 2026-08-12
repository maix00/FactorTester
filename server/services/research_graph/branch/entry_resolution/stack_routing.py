"""Ordered LIFO routing for entry-resolution return frames."""

from __future__ import annotations

from typing import Any

from .stack_departure import advance_active_frame
from .stack_state import (
    canonical_entry_resolution_state,
    canonical_frame,
    merge_receipts,
    receipts_from,
)


def project_target_frame(
    *,
    state: Any,
    target_frame: dict[str, Any],
    current_node: str,
    target_node: str,
) -> dict[str, Any]:
    value = canonical_entry_resolution_state(state)
    target = canonical_frame(target_frame)
    value["assessment_receipts"] = merge_receipts(
        value["assessment_receipts"],
        receipts_from(target_frame.get("assessment_receipts")),
    )
    frames = value["frames"]
    pending = target.get("status") in {
        "resolving", "waiting", "resumable",
    } and bool(
        target.get("unresolved_entry_requirement_refs")
    )
    matches = [
        index
        for index, item in enumerate(frames)
        if str(item["target_node"]) == target_node
    ]
    if matches:
        match = matches[-1]
        existing = frames[match]
        if (
            str(existing.get("resume_guard_hash") or "")
            == str(target.get("resume_guard_hash") or "")
        ):
            if (
                not pending
                and match == len(frames) - 1
                and current_node == target_node
            ):
                value["frames"] = frames[:match]
            else:
                value["frames"] = frames[: match + 1]
                resumed = value["frames"][-1]
                if resumed.get("status") == "waiting":
                    resumed["status"] = "resumable"
        else:
            value["frames"] = [
                *frames[:match],
                *([target] if pending else []),
            ]
        return value
    if not frames:
        value["frames"] = (
            [target] if pending or current_node != target_node else []
        )
        return value
    top = frames[-1]
    if top.get("status") in {"resolving", "waiting", "resumable"}:
        if target_node == current_node:
            if pending:
                frames[-1] = target
            else:
                frames.pop()
        elif pending:
            frames.append(target)
        return value
    remaining = frames[:-1] if len(frames) > 1 else []
    if not remaining:
        value["frames"] = [target] if pending else []
    elif pending:
        value["frames"] = [*remaining, target]
    else:
        value["frames"] = remaining
    return value
