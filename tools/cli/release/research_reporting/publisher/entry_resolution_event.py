"""Validate the server-owned entry-resolution report event."""

from __future__ import annotations

from copy import deepcopy
import re
from typing import Any

from .identity import bounded_text, reference, safe_id


EVENTS = frozenset({
    "push", "route", "wait", "resume", "resolve", "abandon",
})
_FIELDS = {
    "schema_version", "trace_ref",
    "stack_hash_before", "stack_hash_after",
    "depth_before", "depth_after", "events",
}
_ITEM_FIELDS = {
    "event", "entry_attempt_id", "target_node", "ordinal", "report_item",
}
_REPORT_ITEM_FIELDS = {"kind", "entry_attempt_id", "target_node"}
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def canonical_entry_resolution_event(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != _FIELDS:
        raise ValueError("entry_resolution_event fields are invalid")
    result = deepcopy(value)
    if result["schema_version"] != 2:
        raise ValueError("entry_resolution_event contract is invalid")
    reference(result["trace_ref"], "entry_resolution_event.trace_ref")
    if not result["trace_ref"].startswith("trace:"):
        raise ValueError("entry_resolution_event trace_ref must identify a trace")
    for field in ("stack_hash_before", "stack_hash_after"):
        if not isinstance(result[field], str) or not _SHA256.fullmatch(
            result[field]
        ):
            raise ValueError(f"entry_resolution_event.{field} must be sha256")
    for field in ("depth_before", "depth_after"):
        if (
            type(result[field]) is not int
            or not 0 <= result[field] <= 64
        ):
            raise ValueError(f"entry_resolution_event.{field} is invalid")
    events = result["events"]
    if not isinstance(events, list) or not 1 <= len(events) <= 16:
        raise ValueError("entry_resolution_event.events is invalid")
    for ordinal, item in enumerate(events):
        if not isinstance(item, dict) or set(item) != _ITEM_FIELDS:
            raise ValueError("entry_resolution_event event is invalid")
        if item["event"] not in EVENTS or item["ordinal"] != ordinal:
            raise ValueError("entry_resolution_event event order is invalid")
        attempt = str(item["entry_attempt_id"] or "")
        target = str(item["target_node"] or "")
        report_item = item["report_item"]
        if (
            not isinstance(report_item, dict)
            or set(report_item) != _REPORT_ITEM_FIELDS
            or report_item["kind"] != f"entry_resolution.{item['event']}"
            or str(report_item["entry_attempt_id"] or "") != attempt
            or str(report_item["target_node"] or "") != target
        ):
            raise ValueError(
                "entry_resolution_event report_item conflicts"
            )
        if attempt:
            safe_id(attempt, "entry_resolution_event.entry_attempt_id")
        if target:
            safe_id(target, "entry_resolution_event.target_node")
        bounded_text(item["event"], "entry_resolution_event.event")
    return result
