"""Replay helpers for immutable capability-detour deltas."""

from __future__ import annotations

from copy import deepcopy
import json
from typing import Any

from .state import make_state, normalize_state


def evidence_payload(raw: Any) -> dict[str, Any]:
    try:
        value = json.loads(str(raw or "{}"))
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def continuation_state(
    evidence: dict[str, Any],
) -> dict[str, Any] | None:
    descriptor = evidence.get("graph_continuation")
    value = descriptor.get("capability_detour") if isinstance(
        descriptor, dict
    ) else None
    return normalize_state(value)


def persisted_delta(
    evidence: dict[str, Any],
) -> dict[str, Any] | None:
    value = evidence.get("capability_detour_delta")
    return deepcopy(value) if isinstance(value, dict) else None


def project_persisted_delta(
    state: Any,
    delta: dict[str, Any],
    *,
    trace_id: str,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, dict[str, Any]]:
    status = str(delta.get("status") or "")
    if status not in {"opened", "retained", "resumed"}:
        raise ValueError("historical capability detour delta is invalid")
    reconstructed = make_state(
        delta.get("resume_node"),
        delta.get("origin_trace_id"),
    )
    container = delta.get("report_container")
    if isinstance(container, dict):
        reconstructed["report_container"] = deepcopy(container)
    current = normalize_state(state)
    if status == "opened":
        before, after = current, reconstructed
    elif status == "retained":
        before = current or reconstructed
        after = before
    else:
        before, after = current or reconstructed, None
    persisted = {
        **deepcopy(delta),
        "latest_trace_id": str(delta.get("latest_trace_id") or trace_id),
    }
    return before, after, persisted
