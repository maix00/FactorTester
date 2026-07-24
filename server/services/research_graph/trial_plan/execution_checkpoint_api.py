"""Bounded public contract for one current TrialPlan v5 Evidence Action."""

from __future__ import annotations

import sqlite3
from typing import Any

import orjson

import settings as Settings
from tools.data.sqlite.db import connect_sqlite

from .contract import canonical_trial_plan, trial_plan_hash
from .execution_checkpoint_contract import validate_execution_checkpoint
from .execution_checkpoint import initial_execution_checkpoint
from .execution_checkpoint_repository import (
    compare_and_swap_checkpoint_json,
    load_execution_branch,
    validate_execution_branch,
)
from .execution_checkpoint_store import apply_execution_checkpoint_operation
from .execution_checkpoint_store import ExecutionCheckpointConflictError
from .fields import identifier_field, sha256_field


def load_execution_checkpoint_contract(
    *,
    instance_id: str,
    branch_id: str,
    owner: str,
) -> dict[str, Any]:
    """Read only the current branch cursor and its immutable canonical plan."""
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        row = load_execution_branch(
            conn,
            instance_id=instance_id,
            branch_id=branch_id,
            owner=owner,
        )
        plan = _load_current_plan(
            conn,
            row=row,
            instance_id=instance_id,
            branch_id=branch_id,
        )
        checkpoint = validate_execution_checkpoint(
            orjson.loads(str(row["trial_stage_projection_json"] or "{}"))
        )
        return _contract(
            instance_id=instance_id,
            branch_id=branch_id,
            row=row,
            plan=plan,
            checkpoint=checkpoint,
        )


def operate_execution_checkpoint(
    *,
    instance_id: str,
    branch_id: str,
    owner: str,
    expected_latest_trace_id: str,
    expected_checkpoint_hash: str,
    operation: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Apply one server-derived CAS operation without accepting a plan body."""
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = load_execution_branch(
            conn,
            instance_id=instance_id,
            branch_id=branch_id,
            owner=owner,
        )
        plan = _load_current_plan(
            conn,
            row=row,
            instance_id=instance_id,
            branch_id=branch_id,
        )
        outcome = apply_execution_checkpoint_operation(
            conn,
            instance_id=instance_id,
            branch_id=branch_id,
            owner=owner,
            trial_plan=plan,
            expected_latest_trace_id=expected_latest_trace_id,
            expected_checkpoint_hash=expected_checkpoint_hash,
            operation=operation,
            payload=payload,
        )
        return {
            "operation": outcome["operation"],
            "checkpoint": outcome["checkpoint"],
            **{
                key: value
                for key, value in outcome.items()
                if key not in {"operation", "checkpoint"}
            },
        }


def recover_missing_execution_checkpoint(
    *,
    instance_id: str,
    branch_id: str,
    owner: str,
    expected_latest_trace_id: str,
    expected_execution_node: str,
) -> dict[str, Any]:
    """CAS-initialize only a historical v5 branch whose cursor is exactly ``{}``."""
    execution_node = identifier_field(
        expected_execution_node,
        "expected_execution_node",
    )
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = load_execution_branch(
            conn,
            instance_id=instance_id,
            branch_id=branch_id,
            owner=owner,
        )
        if str(row["latest_trace_id"] or "") != expected_latest_trace_id:
            raise ExecutionCheckpointConflictError("branch trace changed")
        if str(row["current_node"] or "") != execution_node:
            raise ValueError("branch is not at the expected execution node")
        raw_current = str(row["trial_stage_projection_json"] or "")
        if raw_current != "{}":
            raise ValueError("execution checkpoint recovery requires exact {}")
        plan = _load_current_plan(
            conn,
            row=row,
            instance_id=instance_id,
            branch_id=branch_id,
        )
        plan_hash = trial_plan_hash(plan)
        if str(row["current_trial_plan_hash"] or "") != plan_hash:
            raise ValueError("current TrialPlan body does not match branch")
        validate_execution_branch(
            row,
            plan_hash=plan_hash,
            execution_node=execution_node,
            expected_latest_trace_id=expected_latest_trace_id,
        )
        checkpoint = initial_execution_checkpoint(
            trial_plan=plan,
            expected_trial_plan_hash=plan_hash,
            execution_node=execution_node,
        )
        compare_and_swap_checkpoint_json(
            conn,
            instance_id=instance_id,
            branch_id=branch_id,
            expected_latest_trace_id=expected_latest_trace_id,
            raw_current=raw_current,
            serialized_checkpoint=orjson.dumps(
                checkpoint,
                option=orjson.OPT_SORT_KEYS,
            ).decode(),
        )
        return {
            "operation": "initialize_missing",
            "recovered": True,
            "trial_plan_hash": plan_hash,
            "latest_trace_id": expected_latest_trace_id,
            "execution_node": execution_node,
            "previous_checkpoint": {},
            "checkpoint": checkpoint,
        }


def current_action_trial_binding(
    *,
    instance_id: str,
    branch_id: str,
    owner: str,
    run_spec_hash: str,
    trial_role: str,
    comparison_id: str,
) -> dict[str, Any]:
    """Generate the exact current-action input accepted by ``run submit``."""
    contract = load_execution_checkpoint_contract(
        instance_id=instance_id,
        branch_id=branch_id,
        owner=owner,
    )
    checkpoint = contract["checkpoint"]
    if checkpoint["current_action_status"] != "released":
        raise ValueError("current Evidence Action is not released")
    plan = contract["trial_plan"]
    action = plan["evidence_actions"][checkpoint["current_action_index"]]
    normalized_run_hash = sha256_field(run_spec_hash, "run_spec_hash")
    normalized_role = identifier_field(trial_role, "trial_role")
    normalized_comparison = identifier_field(comparison_id, "comparison_id")
    if normalized_run_hash not in action["run_spec_hashes"]:
        raise ValueError("RunSpec hash is not declared by current Evidence Action")
    if normalized_comparison not in action["comparison_ids"]:
        raise ValueError("comparison_id is not declared by current Evidence Action")
    comparison = next(
        (
            item for item in plan["comparisons"]
            if item["comparison_id"] == normalized_comparison
        ),
        None,
    )
    if comparison is None or not any(
        member["run_spec_hash"] == normalized_run_hash
        and member["trial_role"] == normalized_role
        for member in comparison["members"]
    ):
        raise ValueError("RunSpec hash and trial_role are not a planned member")
    return {
        "instance_id": instance_id,
        "branch_id": branch_id,
        "trial_plan": plan,
        "trial_plan_hash": contract["trial_plan_hash"],
        "trial_plan_version": plan["version"],
        "trial_role": normalized_role,
        "comparison_id": normalized_comparison,
        "evidence_action_id": action["action_id"],
        "expected_checkpoint_hash": checkpoint["projection_hash"],
        "expected_latest_trace_id": contract["latest_trace_id"],
    }


def _load_current_plan(
    conn: sqlite3.Connection,
    *,
    row: sqlite3.Row,
    instance_id: str,
    branch_id: str,
) -> dict[str, Any]:
    plan_hash = str(row["current_trial_plan_hash"] or "")
    if not plan_hash:
        raise ValueError("branch has no current TrialPlan")
    trace = conn.execute(
        """
        SELECT evidence_json
        FROM research_graph_trace
        WHERE instance_id=? AND branch_id=?
          AND json_extract(evidence_json, '$.trial_plan_hash')=?
          AND json_type(evidence_json, '$.trial_plan')='object'
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (instance_id, branch_id, plan_hash),
    ).fetchone()
    if trace is None:
        raise ValueError("current TrialPlan body is unavailable")
    evidence = orjson.loads(str(trace["evidence_json"]) or "{}")
    plan = canonical_trial_plan(evidence.get("trial_plan"))
    if plan["schema_version"] != 5 or trial_plan_hash(plan) != plan_hash:
        raise ValueError("current TrialPlan body does not match branch")
    return plan


def _contract(
    *,
    instance_id: str,
    branch_id: str,
    row: sqlite3.Row,
    plan: dict[str, Any],
    checkpoint: dict[str, Any],
) -> dict[str, Any]:
    status = checkpoint["current_action_status"]
    operations_by_status = {
        "unreleased": ["release"],
        "released": [
            "mark_running", "mark_evidence_ready", "mark_blocked", "mark_failed"
        ],
        "running": ["mark_evidence_ready", "mark_blocked", "mark_failed"],
        "blocked": ["retry"],
        "evidence_ready": ["admit"],
        "admitted": ["audit"],
        "audited": ["advance"],
    }
    payload_contracts = {
        "mark_evidence_ready": {"required_fields": ["evidence_refs"]},
        "admit": {"required_fields": ["evidence_records"]},
        "audit": {"required_fields": ["proposal", "decision"]},
    }
    return {
        "instance_id": instance_id,
        "branch_id": branch_id,
        "trial_plan_hash": trial_plan_hash(plan),
        "latest_trace_id": str(row["latest_trace_id"] or ""),
        "checkpoint": checkpoint,
        "current_action": plan["evidence_actions"][
            checkpoint["current_action_index"]
        ],
        "allowed_operations": operations_by_status.get(status, []),
        "operation_payload_contracts": {
            operation: payload_contracts.get(
                operation, {"required_fields": []}
            )
            for operation in operations_by_status.get(status, [])
        },
        "trial_plan": plan,
    }
