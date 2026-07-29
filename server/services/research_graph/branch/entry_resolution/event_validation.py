"""Strict validation for server-owned entry-resolution event envelopes."""

from __future__ import annotations

from copy import deepcopy
import re
from typing import Any


EVENTS = frozenset({
    "push", "route", "wait", "resume", "resolve", "abandon",
})
_ID = re.compile(r"^[A-Za-z0-9_.-]+$")
_HASH = re.compile(r"^[0-9a-f]{64}$")
_ENVELOPE_FIELDS = {
    "schema_version", "trace_ref", "stack_hash_before", "stack_hash_after",
    "depth_before", "depth_after", "events",
}
_EVENT_FIELDS = {
    "ordinal", "event", "entry_attempt_id", "target_node", "report_item",
}
_REPORT_FIELDS = {"kind", "entry_attempt_id", "target_node"}


def canonical_entry_resolution_event(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != _ENVELOPE_FIELDS:
        raise ValueError("entry_resolution_event fields are invalid")
    result = deepcopy(value)
    if result["schema_version"] != 2:
        raise ValueError("entry_resolution_event schema_version must be 2")
    trace_ref = result["trace_ref"]
    if not isinstance(trace_ref, str) or not trace_ref.startswith("trace:"):
        raise ValueError("entry_resolution_event trace_ref is invalid")
    for field in ("stack_hash_before", "stack_hash_after"):
        if not isinstance(result[field], str) or not _HASH.fullmatch(
            result[field]
        ):
            raise ValueError(f"entry_resolution_event {field} is invalid")
    for field in ("depth_before", "depth_after"):
        if type(result[field]) is not int or result[field] < 0:
            raise ValueError(f"entry_resolution_event {field} is invalid")
    events = result["events"]
    if not isinstance(events, list) or not events or len(events) > 16:
        raise ValueError("entry_resolution_event events are invalid")
    for ordinal, item in enumerate(events):
        _validate_event(item, ordinal=ordinal)
    return result


def _validate_event(value: Any, *, ordinal: int) -> None:
    if not isinstance(value, dict) or set(value) != _EVENT_FIELDS:
        raise ValueError("entry_resolution_event item fields are invalid")
    if value["ordinal"] != ordinal or value["event"] not in EVENTS:
        raise ValueError("entry_resolution_event item order is invalid")
    for field in ("entry_attempt_id", "target_node"):
        if not isinstance(value[field], str) or not _ID.fullmatch(value[field]):
            raise ValueError(f"entry_resolution_event {field} is invalid")
    report = value["report_item"]
    if not isinstance(report, dict) or set(report) != _REPORT_FIELDS:
        raise ValueError("entry_resolution_event report_item is invalid")
    expected = {
        "kind": f"entry_resolution.{value['event']}",
        "entry_attempt_id": value["entry_attempt_id"],
        "target_node": value["target_node"],
    }
    if report != expected:
        raise ValueError("entry_resolution_event report_item does not match")
