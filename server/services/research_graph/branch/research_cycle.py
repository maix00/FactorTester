"""Research Cycle checkpoint continuity inside ordinary Graph traces."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from server.services.research_graph.protocol import json_hash, loads
from server.services.research_graph.research_cycle.replay import (
    replay_research_cycle_events,
    validate_research_cycle_checkpoint,
)


def checkpoint_from_branch_row(row: Any) -> dict[str, Any] | None:
    """Read only the current checkpoint carried by the latest trace."""
    raw = row["latest_trace_evidence_json"]
    if raw in (None, ""):
        return None
    evidence = loads(raw)
    if not isinstance(evidence, dict):
        return None
    checkpoint = evidence.get("research_cycle_checkpoint")
    if checkpoint is None:
        return None
    return validate_research_cycle_checkpoint(checkpoint)


def prepare_research_cycle_trace(
    *,
    update: Any,
    previous_checkpoint: dict[str, Any] | None,
    latest_trace_id: str,
    requirement_catalog: dict[str, Any] | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Validate one update and return trace event plus current checkpoint."""
    if update is None:
        if previous_checkpoint is None:
            return None, None
        return {
            "schema_version": 1,
            "parent_trace_ref": f"trace:{latest_trace_id}",
            "checkpoint_before_hash": previous_checkpoint["projection_hash"],
            "events": [],
        }, deepcopy(previous_checkpoint)
    if not isinstance(update, dict):
        raise ValueError("research_cycle update must be an object")
    if update.get("schema_version") != 1:
        raise ValueError("research_cycle update schema_version must be 1")
    parent_trace_ref = update.get("parent_trace_ref", "")
    expected_parent = f"trace:{latest_trace_id}" if latest_trace_id else ""
    if parent_trace_ref != expected_parent:
        raise ValueError("research_cycle parent trace is stale")
    initial = update.get("initial_checkpoint")
    if previous_checkpoint is None:
        if initial is None:
            raise ValueError(
                "research_cycle requires an initial unknown-state checkpoint"
            )
        base = _validate_initial_checkpoint(initial)
    else:
        if initial is not None:
            raise ValueError("research_cycle is already initialized")
        base = previous_checkpoint
    events = update.get("events")
    if not isinstance(events, list):
        raise ValueError("research_cycle events must be an array")
    if previous_checkpoint is None and events:
        raise ValueError(
            "initial research_cycle checkpoint cannot adjudicate events"
        )
    expected_base_hash = update.get("expected_base_hash")
    if not isinstance(expected_base_hash, str):
        raise ValueError("research_cycle expected_base_hash is required")
    current = replay_research_cycle_events(
        base,
        events=events,
        expected_base_hash=expected_base_hash,
        requirement_catalog=requirement_catalog,
    )
    trace_event = {
        "schema_version": 1,
        "parent_trace_ref": parent_trace_ref,
        "checkpoint_before_hash": base["projection_hash"],
        "events": deepcopy(events),
    }
    if previous_checkpoint is None:
        trace_event["bootstrap_checkpoint"] = True
    return trace_event, current


def release_trial_plan_for_new_hypothesis(
    *,
    trace_event: dict[str, Any] | None,
    checkpoint: dict[str, Any] | None,
    current_trial_plan_hash: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Append one server-owned release event without scanning old traces."""
    if trace_event is None or checkpoint is None:
        raise ValueError(
            "new hypothesis lineage requires a Research Cycle checkpoint"
        )
    event = {
        "event_type": "trial_plan_released",
        "from_hash": current_trial_plan_hash,
        "reason": "new_hypothesis_lineage",
    }
    current = replay_research_cycle_events(
        checkpoint,
        events=[event],
        expected_base_hash=checkpoint["projection_hash"],
    )
    value = deepcopy(trace_event)
    value["events"] = [*(value.get("events") or []), event]
    return value, current


def agent_cycle_summary(
    checkpoint: dict[str, Any] | None,
) -> dict[str, Any]:
    """Return bounded current semantics without full Claim/proposal bodies."""
    if checkpoint is None:
        return {
            "protocol_status": "uninitialized",
            "projection_hash": None,
            "claim_states": [],
            "open_obligations": [],
            "pending_adjudication_ids": [],
            "closure": None,
        }
    return {
        "protocol_status": "current",
        "projection_hash": checkpoint["projection_hash"],
        "contract_hash": checkpoint["contract_hash"],
        "trial_plan_hash": checkpoint["trial_plan_hash"] or None,
        "methodology_hash": checkpoint["methodology_hash"],
        "claim_states": [{
            "claim_id": item["claim_id"],
            "claim_ref": item["claim_ref"],
            "claim_type": item["claim_type"],
            "scope": deepcopy(item["scope"]),
            "evidence_state": item["evidence_state"],
            "detail_ref": (
                "research-cycle-object:claim:" + item["claim_id"]
            ),
        } for item in checkpoint["claims"]],
        "open_obligations": [{
            "obligation_id": item["obligation_id"],
            "claim_ids": deepcopy(item["claim_ids"]),
            "materiality": item["materiality"],
            "status": item["status"],
            "question_summary": _bounded_text(
                item["epistemic_question"],
                max_bytes=240,
            ),
            "criterion_ref": _criterion_ref(
                item["discharge_criterion"]
            ),
            "detail_ref": (
                "research-cycle-object:obligation:"
                + item["obligation_id"]
            ),
        } for item in checkpoint["obligations"] if item["status"] in {
            "open",
            "reopened",
        }],
        "pending_adjudication_ids": [
            item["proposal_id"]
            for item in checkpoint["pending_adjudications"]
        ],
        "closure": (
            {
                "proposal_id": checkpoint["closure"]["proposal_id"],
                "disposition": checkpoint["closure"]["disposition"],
            }
            if checkpoint["closure"] is not None
            else None
        ),
    }


def _criterion_ref(value: dict[str, Any]) -> str:
    for key in ("rule_ref", "method_ref", "criterion_ref"):
        candidate = value.get(key)
        if isinstance(candidate, str) and candidate:
            return candidate
    return "sha256:" + json_hash(value)


def _bounded_text(value: str, *, max_bytes: int) -> str:
    encoded = str(value).encode()
    if len(encoded) <= max_bytes:
        return str(value)
    return encoded[: max_bytes - 3].decode(errors="ignore") + "..."


def _validate_initial_checkpoint(value: Any) -> dict[str, Any]:
    checkpoint = validate_research_cycle_checkpoint(value)
    if (
        checkpoint["pending_adjudications"]
        or checkpoint["pending_closure"] is not None
        or checkpoint["closure"] is not None
    ):
        raise ValueError("initial checkpoint cannot contain decisions")
    if any(
        item["evidence_state"] not in {"unassessed", "unknown"}
        or item["evidence_refs"]
        for item in checkpoint["claims"]
    ):
        raise ValueError("initial Claim state must be unknown and evidence-free")
    if any(
        item["status"] != "open"
        for item in checkpoint["obligations"]
    ):
        raise ValueError("initial obligations must be open")
    return checkpoint
