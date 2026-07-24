"""Atomic supersession of an unused TrialPlan v5 execution cursor."""

from __future__ import annotations

import time
import uuid
from typing import Any

import orjson

import settings as Settings
from server.services.research_graph.protocol import (
    loads,
    serialize_bounded_trace_evidence,
)
from server.services.research_graph.research_cycle.replay import (
    replay_research_cycle_events,
)
from tools.data.sqlite.db import connect_sqlite

from .contract import canonical_trial_plan, trial_plan_hash
from .execution_checkpoint import revised_execution_checkpoint
from .execution_checkpoint_contract import validate_execution_checkpoint
from .execution_checkpoint_repository import (
    load_execution_branch,
    validate_execution_branch,
)
from .execution_checkpoint_store import ExecutionCheckpointConflictError


def revise_current_trial_plan(
    *,
    instance_id: str,
    branch_id: str,
    owner: str,
    expected_latest_trace_id: str,
    expected_checkpoint_hash: str,
    expected_trial_plan_hash: str,
    trial_plan: dict[str, Any],
    acting_profile_ref: str = "",
) -> dict[str, Any]:
    """Supersede only a current Action that has produced no durable result."""
    replacement = canonical_trial_plan(trial_plan)
    replacement_hash = trial_plan_hash(replacement)
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = load_execution_branch(
            conn,
            instance_id=instance_id,
            branch_id=branch_id,
            owner=owner,
        )
        current_hash = str(row["current_trial_plan_hash"] or "")
        if current_hash != expected_trial_plan_hash:
            raise ExecutionCheckpointConflictError("TrialPlan changed")
        current_plan = _load_plan(
            conn,
            instance_id=instance_id,
            branch_id=branch_id,
            plan_hash=current_hash,
        )
        raw_current = str(row["trial_stage_projection_json"] or "{}")
        current = validate_execution_checkpoint(orjson.loads(raw_current))
        validate_execution_branch(
            row,
            plan_hash=current_hash,
            execution_node=current["execution_node"],
            expected_latest_trace_id=expected_latest_trace_id,
        )
        if current["projection_hash"] != expected_checkpoint_hash:
            raise ExecutionCheckpointConflictError(
                "execution checkpoint changed"
            )
        _require_unused_action(
            conn,
            instance_id=instance_id,
            branch_id=branch_id,
            plan_hash=current_hash,
            checkpoint=current,
        )
        if replacement["trial_plan_id"] != current_plan["trial_plan_id"]:
            raise ValueError("revised TrialPlan must preserve trial_plan_id")
        checkpoint = revised_execution_checkpoint(
            trial_plan=replacement,
            expected_trial_plan_hash=replacement_hash,
            previous_trial_plan_hash=current_hash,
            previous_version=int(current_plan["version"]),
            execution_node=current["execution_node"],
        )
        _require_profile(
            conn,
            instance_id=instance_id,
            owner=owner,
            acting_profile_ref=acting_profile_ref,
        )
        trace_id = uuid.uuid4().hex
        now = time.time()
        evidence = _revision_evidence(
            conn,
            instance_id=instance_id,
            branch_id=branch_id,
            previous_trace_id=expected_latest_trace_id,
            previous_hash=current_hash,
            replacement_hash=replacement_hash,
            replacement=replacement,
        )
        conn.execute(
            """
            UPDATE research_graph_branches
            SET current_trial_plan_hash=?, trial_stage_projection_json=?,
                latest_trace_id=?, updated_at=?
            WHERE instance_id=? AND branch_id=? AND latest_trace_id=?
              AND current_trial_plan_hash=?
              AND trial_stage_projection_json=?
            """,
            (
                replacement_hash,
                orjson.dumps(checkpoint).decode(),
                trace_id,
                now,
                instance_id,
                branch_id,
                expected_latest_trace_id,
                current_hash,
                raw_current,
            ),
        )
        if int(conn.execute("SELECT changes()").fetchone()[0]) != 1:
            raise ExecutionCheckpointConflictError("branch changed")
        conn.execute(
            """
            INSERT INTO research_graph_trace (
                trace_id, instance_id, branch_id, edge_id, from_node, to_node,
                evidence_json, telemetry_json, actor, acting_profile_ref,
                created_at
            ) VALUES (?, ?, ?, '__trial_plan_revision__', ?, ?, ?, '{}',
                      ?, ?, ?)
            """,
            (
                trace_id,
                instance_id,
                branch_id,
                current["execution_node"],
                current["execution_node"],
                serialize_bounded_trace_evidence(evidence),
                owner,
                acting_profile_ref,
                now,
            ),
        )
    return {
        "operation": "revise_unused_trial_plan",
        "previous_trial_plan_hash": current_hash,
        "trial_plan_hash": replacement_hash,
        "latest_trace_id": trace_id,
        "checkpoint": checkpoint,
    }


def _require_unused_action(
    conn,
    *,
    instance_id: str,
    branch_id: str,
    plan_hash: str,
    checkpoint: dict[str, Any],
) -> None:
    if checkpoint["current_action_status"] not in {
        "unreleased", "released", "running",
    }:
        raise ValueError("TrialPlan revision requires an unused current Action")
    if checkpoint["current_action_output_evidence_refs"]:
        raise ValueError("TrialPlan revision rejects existing Evidence")
    table = conn.execute(
        "SELECT 1 FROM sqlite_master "
        "WHERE type='table' AND name='research_runs'"
    ).fetchone()
    if table is None:
        return
    run = conn.execute(
        """
        SELECT 1 FROM research_runs
        WHERE graph_instance_id=? AND graph_branch_id=?
          AND trial_plan_hash=? AND evidence_action_id=?
        LIMIT 1
        """,
        (
            instance_id,
            branch_id,
            plan_hash,
            checkpoint["current_action_id"],
        ),
    ).fetchone()
    if run is not None:
        raise ValueError("TrialPlan revision rejects existing Run or Job")


def _load_plan(conn, *, instance_id: str, branch_id: str, plan_hash: str):
    row = conn.execute(
        """
        SELECT evidence_json FROM research_graph_trace
        WHERE instance_id=? AND branch_id=?
          AND json_extract(evidence_json, '$.trial_plan_hash')=?
          AND json_type(evidence_json, '$.trial_plan')='object'
        ORDER BY created_at DESC LIMIT 1
        """,
        (instance_id, branch_id, plan_hash),
    ).fetchone()
    if row is None:
        raise ValueError("current TrialPlan body is unavailable")
    plan = canonical_trial_plan(loads(row["evidence_json"])["trial_plan"])
    if trial_plan_hash(plan) != plan_hash:
        raise ValueError("current TrialPlan body does not match branch")
    return plan


def _require_profile(
    conn,
    *,
    instance_id: str,
    owner: str,
    acting_profile_ref: str,
) -> None:
    row = conn.execute(
        """
        SELECT current_owner_profile_ref FROM research_graph_instances
        WHERE instance_id=? AND owner=?
        """,
        (instance_id, owner),
    ).fetchone()
    if row is None:
        raise KeyError("graph branch not found")
    expected = str(row["current_owner_profile_ref"] or "")
    if expected and acting_profile_ref != expected:
        raise PermissionError("branch is owned by another Profile")


def _revision_evidence(
    conn,
    *,
    instance_id: str,
    branch_id: str,
    previous_trace_id: str,
    previous_hash: str,
    replacement_hash: str,
    replacement: dict[str, Any],
) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT evidence_json FROM research_graph_trace
        WHERE instance_id=? AND branch_id=? AND trace_id=?
        """,
        (instance_id, branch_id, previous_trace_id),
    ).fetchone()
    previous = loads(row["evidence_json"]) if row is not None else {}
    value = {
        "trial_plan": replacement,
        "trial_plan_hash": replacement_hash,
        "trial_plan_revision": {
            "reason": "unused_action_configuration_correction",
            "previous_trial_plan_hash": previous_hash,
            "replacement_trial_plan_hash": replacement_hash,
        },
        "report_lineage": {
            "status": "linked",
            "predecessor_checkpoint_ref": f"trace:{previous_trace_id}",
        },
    }
    cycle = (previous or {}).get("research_cycle_checkpoint")
    if isinstance(cycle, dict):
        event = {
            "event_type": "trial_plan_bound",
            "from_hash": previous_hash,
            "to_hash": replacement_hash,
        }
        projected = replay_research_cycle_events(
            cycle,
            events=[event],
            expected_base_hash=cycle["projection_hash"],
        )
        value["research_cycle"] = {
            "schema_version": 1,
            "parent_trace_ref": f"trace:{previous_trace_id}",
            "checkpoint_before_hash": cycle["projection_hash"],
            "events": [event],
        }
        value["research_cycle_checkpoint"] = projected
    return value
