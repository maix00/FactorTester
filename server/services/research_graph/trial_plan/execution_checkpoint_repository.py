"""Two-statement SQL hot path for the TrialPlan v5 execution cursor."""

from __future__ import annotations

import sqlite3
import time


def load_execution_branch(
    conn: sqlite3.Connection,
    *,
    instance_id: str,
    branch_id: str,
    owner: str,
) -> sqlite3.Row:
    row = conn.execute(
        """
        SELECT b.current_node, b.current_trial_plan_hash,
               b.trial_stage_projection_json, b.latest_trace_id,
               b.is_current_incarnation,
               COALESCE(w.lifecycle, 'active') AS work_package_lifecycle
        FROM research_graph_instances AS i
        JOIN research_graph_branches AS b ON b.instance_id=i.instance_id
        LEFT JOIN research_work_packages AS w
          ON w.owner=i.owner
         AND w.work_package_id=COALESCE(
             NULLIF(i.work_package_id, ''), i.instance_id
         )
        WHERE i.instance_id=? AND b.branch_id=? AND i.owner=?
        """,
        (instance_id, branch_id, owner),
    ).fetchone()
    if row is None:
        raise KeyError("graph branch not found")
    return row


def validate_execution_branch(
    row: sqlite3.Row,
    *,
    plan_hash: str,
    execution_node: str,
    expected_latest_trace_id: str,
) -> None:
    from .execution_checkpoint_store import ExecutionCheckpointConflictError

    if not bool(row["is_current_incarnation"]):
        raise ValueError("graph branch is not the current incarnation")
    if str(row["work_package_lifecycle"] or "") != "active":
        raise ValueError("execution checkpoint requires an active Work Package")
    if str(row["current_node"] or "") != execution_node:
        raise ValueError("branch is not at the TrialPlan execution node")
    if str(row["current_trial_plan_hash"] or "") != plan_hash:
        raise ValueError("TrialPlan is not current for the hypothesis branch")
    if str(row["latest_trace_id"] or "") != expected_latest_trace_id:
        raise ExecutionCheckpointConflictError("branch trace changed")


def compare_and_swap_checkpoint_json(
    conn: sqlite3.Connection,
    *,
    instance_id: str,
    branch_id: str,
    expected_latest_trace_id: str,
    raw_current: str,
    serialized_checkpoint: str,
) -> None:
    from .execution_checkpoint_store import ExecutionCheckpointConflictError

    cursor = conn.execute(
        """
        UPDATE research_graph_branches
        SET trial_stage_projection_json=?, updated_at=?
        WHERE instance_id=? AND branch_id=?
          AND latest_trace_id=? AND trial_stage_projection_json=?
        """,
        (
            serialized_checkpoint,
            time.time(),
            instance_id,
            branch_id,
            expected_latest_trace_id,
            raw_current,
        ),
    )
    if int(cursor.rowcount) != 1:
        raise ExecutionCheckpointConflictError("execution checkpoint changed")
