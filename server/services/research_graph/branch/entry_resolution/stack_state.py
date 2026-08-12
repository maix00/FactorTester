"""Canonical persisted state for nested entry-resolution attempts."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import orjson

from .guard import resume_guard_hash
from .legacy_adapter import upgrade_legacy_frame

def canonical_entry_resolution_state(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or not value:
        return {"schema_version": 2, "frames": [], "assessment_receipts": []}
    raw_frames = value.get("frames")
    frames = (
        raw_frames
        if value.get("schema_version") == 2 and isinstance(raw_frames, list)
        else [value]
    )
    receipts = receipts_from(value.get("assessment_receipts"))
    canonical_frames = []
    for raw in frames:
        if not isinstance(raw, dict):
            raise ValueError("entry resolution frames must be objects")
        receipts = merge_receipts(
            receipts, receipts_from(raw.get("assessment_receipts"))
        )
        frame = canonical_frame(raw)
        if frame is not None:
            canonical_frames.append(frame)
    return {
        "schema_version": 2,
        "frames": canonical_frames,
        "assessment_receipts": receipts,
    }


def active_frame(state: Any) -> dict[str, Any] | None:
    frames = canonical_entry_resolution_state(state)["frames"]
    return deepcopy(frames[-1]) if frames else None


def canonical_frame(value: dict[str, Any]) -> dict[str, Any] | None:
    if value.get("schema_version") == 2:
        return _canonical_v2_frame(value)
    return upgrade_legacy_frame(value)


def receipts_from(value: Any) -> list[dict[str, Any]]:
    return [deepcopy(item) for item in value or [] if isinstance(item, dict)]


def merge_receipts(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    values = {}
    for item in (entry for group in groups for entry in group):
        key = str(item.get("receipt_hash") or "") or orjson.dumps(
            item, option=orjson.OPT_SORT_KEYS
        ).decode()
        values[key] = deepcopy(item)
    return [values[key] for key in sorted(values)]


def text_ids(value: Any) -> list[str]:
    return sorted({str(item) for item in value or [] if str(item)})


def _canonical_v2_frame(value: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(value)
    result.pop("assessment_receipts", None)
    for field in ("entry_attempt_id", "target_node"):
        if not str(result.get(field) or ""):
            raise ValueError(f"entry resolution frame requires {field}")
    if result.get("status") not in {
        "resolving", "waiting", "resumable", "resolved", "abandoned",
    }:
        raise ValueError("entry resolution frame status is invalid")
    result["schema_version"] = 2
    for field in (
        "blocking_obligation_refs", "entry_requirement_refs",
        "unresolved_entry_requirement_refs",
        "resolved_entry_requirement_refs", "dispatch_refs", "completion_refs",
    ):
        if field in result:
            result[field] = text_ids(result[field])
    if (
        "unresolved_entry_requirement_refs" not in result
        and result["status"] in {"resolving", "waiting", "resumable"}
    ):
        result["unresolved_entry_requirement_refs"] = text_ids(
            result.get("entry_requirement_refs")
        )
    guard_fields = (
        str(result.get("graph_ref") or ""),
        str(result.get("target_node") or ""),
        str(result.get("origin_checkpoint_ref") or ""),
    )
    if "legacy_projection" not in result and (
        not all(guard_fields)
        or not str(result.get("resume_guard_hash") or "")
    ):
        raise ValueError("native entry frame requires complete resume guard")
    if all(guard_fields):
        expected = resume_guard_hash(
            graph_ref=guard_fields[0],
            target_node=guard_fields[1],
            origin_checkpoint_ref=guard_fields[2],
            blocking_obligation_refs=text_ids(
                result.get("blocking_obligation_refs")
            ),
            entry_requirement_refs=text_ids(
                result.get("entry_requirement_refs")
            ),
        )
        declared = str(result.get("resume_guard_hash") or "")
        if declared and declared != expected:
            raise ValueError("entry resolution resume_guard_hash is invalid")
        result["resume_guard_hash"] = expected
    return result
