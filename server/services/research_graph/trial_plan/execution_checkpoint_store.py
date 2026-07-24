"""Atomic, server-derived persistence for the TrialPlan v5 action cursor."""

from __future__ import annotations

import sqlite3
from typing import Any

import orjson

from .contract import trial_plan_hash
from .adjudication_receipts import (
    backfill_action_adjudication_receipt,
)
from .evidence_admission import admit_current_action
from .evidence_reuse import reuse_exact_action_evidence
from .execution_checkpoint import (
    advance_after_audit,
    transition_action_status,
)
from .execution_checkpoint_contract import (
    validate_checkpoint_plan_identity,
    validate_execution_checkpoint,
)
from .result_audit import audit_current_action
from .execution_checkpoint_repository import (
    compare_and_swap_checkpoint_json,
    load_execution_branch,
    validate_execution_branch,
)


class ExecutionCheckpointConflictError(ValueError):
    """The branch advanced after the caller read its execution checkpoint."""


_EMPTY_OPERATIONS = {
    "release": "released",
    "mark_running": "running",
    "mark_blocked": "blocked",
    "mark_failed": "failed",
    "retry": "released",
}
_PAYLOAD_FIELDS = {
    "mark_evidence_ready": {"evidence_refs"},
    "admit": {"evidence_records"},
    "audit": {"proposal", "decision"},
    "reuse_exact": {"admission_receipt"},
}


def apply_execution_checkpoint_operation(
    conn: sqlite3.Connection,
    *,
    instance_id: str,
    branch_id: str,
    owner: str,
    trial_plan: dict[str, Any],
    expected_latest_trace_id: str,
    expected_checkpoint_hash: str,
    operation: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Derive and persist exactly one legal operation with compare-and-swap."""
    plan_hash = trial_plan_hash(trial_plan)
    row = load_execution_branch(
        conn,
        instance_id=instance_id,
        branch_id=branch_id,
        owner=owner,
    )
    raw_current = str(row["trial_stage_projection_json"] or "{}")
    current = validate_execution_checkpoint(orjson.loads(raw_current))
    validate_checkpoint_plan_identity(current, trial_plan)
    validate_execution_branch(
        row,
        plan_hash=plan_hash,
        execution_node=current["execution_node"],
        expected_latest_trace_id=expected_latest_trace_id,
    )
    if current["projection_hash"] != expected_checkpoint_hash:
        raise ExecutionCheckpointConflictError("execution checkpoint changed")
    outcome = _derive_operation(
        current,
        trial_plan=trial_plan,
        operation=operation,
        payload=payload or {},
    )
    checkpoint = validate_execution_checkpoint(outcome["checkpoint"])
    serialized = orjson.dumps(checkpoint, option=orjson.OPT_SORT_KEYS).decode()
    compare_and_swap_checkpoint_json(
        conn,
        instance_id=instance_id,
        branch_id=branch_id,
        expected_latest_trace_id=expected_latest_trace_id,
        raw_current=raw_current,
        serialized_checkpoint=serialized,
    )
    if operation == "audit":
        outcome["adjudication_receipt"] = backfill_action_adjudication_receipt(
            conn,
            instance_id=instance_id,
            branch_id=branch_id,
            trial_plan=trial_plan,
            checkpoint=checkpoint,
            proposal=(payload or {})["proposal"],
            decision=(payload or {})["decision"],
        )
    return {**outcome, "checkpoint": checkpoint}


def _derive_operation(
    current: dict[str, Any],
    *,
    trial_plan: dict[str, Any],
    operation: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    if operation in _EMPTY_OPERATIONS:
        _require_payload(payload, set())
        checkpoint = transition_action_status(
            current,
            target=_EMPTY_OPERATIONS[operation],
        )
        return {"operation": operation, "checkpoint": checkpoint}
    if operation == "mark_evidence_ready":
        _require_payload(payload, _PAYLOAD_FIELDS[operation])
        checkpoint = transition_action_status(
            current,
            target="evidence_ready",
            evidence_refs=payload["evidence_refs"],
        )
        return {"operation": operation, "checkpoint": checkpoint}
    if operation == "admit":
        _require_payload(payload, _PAYLOAD_FIELDS[operation])
        return {
            "operation": operation,
            **admit_current_action(
                current,
                trial_plan=trial_plan,
                evidence_records=payload["evidence_records"],
            ),
        }
    if operation == "audit":
        _require_payload(payload, _PAYLOAD_FIELDS[operation])
        checkpoint = audit_current_action(
            current,
            trial_plan=trial_plan,
            proposal=payload["proposal"],
            decision=payload["decision"],
        )
        return {"operation": operation, "checkpoint": checkpoint}
    if operation == "advance":
        _require_payload(payload, set())
        checkpoint = advance_after_audit(current, trial_plan=trial_plan)
        return {"operation": operation, "checkpoint": checkpoint}
    if operation == "reuse_exact":
        _require_payload(payload, _PAYLOAD_FIELDS[operation])
        return {
            "operation": operation,
            **reuse_exact_action_evidence(
                current,
                trial_plan=trial_plan,
                admission_receipt=payload["admission_receipt"],
            ),
        }
    raise ValueError("unsupported execution checkpoint operation")


def _require_payload(payload: dict[str, Any], fields: set[str]) -> None:
    if not isinstance(payload, dict) or set(payload) != fields:
        raise ValueError("execution checkpoint operation payload is invalid")
