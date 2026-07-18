"""ResearchRun binding validation for one frozen TrialPlan."""

from __future__ import annotations

import sqlite3
from typing import Any

from .contract import canonical_trial_plan, trial_plan_hash


def normalize_run_binding(
    *,
    trial_plan: dict[str, Any],
    expected_hash: str,
    expected_version: int,
    run_spec_hash: str,
    trial_role: str,
    comparison_id: str,
) -> dict[str, Any]:
    """Validate one RunSpec member without copying the plan into the run."""
    plan = canonical_trial_plan(trial_plan)
    actual_hash = trial_plan_hash(plan)
    if str(expected_hash).removeprefix("sha256:") != actual_hash:
        raise ValueError("trial_plan_hash does not match TrialPlan body")
    if (
        isinstance(expected_version, bool)
        or not isinstance(expected_version, int)
        or expected_version != plan["version"]
    ):
        raise ValueError("trial_plan_version does not match TrialPlan body")
    normalized_run_hash = str(run_spec_hash).removeprefix("sha256:")
    comparison = next(
        (
            item
            for item in plan["comparisons"]
            if item["comparison_id"] == comparison_id
        ),
        None,
    )
    if comparison is None:
        raise ValueError("comparison_id is not declared by TrialPlan")
    if not any(
        member["run_spec_hash"] == normalized_run_hash
        and member["trial_role"] == trial_role
        for member in comparison["members"]
    ):
        raise ValueError(
            "RunSpec hash and trial_role are not a planned comparison member"
        )
    return {
        "trial_plan_id": str(plan["trial_plan_id"]),
        "trial_plan_hash": actual_hash,
        "trial_plan_version": int(plan["version"]),
        "trial_role": str(trial_role),
        "comparison_id": str(comparison_id),
    }


def validate_branch_binding(
    conn: sqlite3.Connection,
    *,
    owner: str,
    workspace_id: str,
    instance_id: str,
    branch_id: str,
    trial_plan_hash: str,
) -> None:
    """Bind against the current projection without scanning graph trace."""
    row = conn.execute(
        """
        SELECT b.current_trial_plan_hash
        FROM research_graph_instances AS i
        JOIN research_graph_branches AS b
          ON b.instance_id=i.instance_id
        WHERE i.instance_id=? AND b.branch_id=?
          AND i.owner=? AND i.workspace_id=?
        """,
        (instance_id, branch_id, owner, workspace_id),
    ).fetchone()
    if row is None:
        raise ValueError("owned hypothesis branch not found in workspace")
    if str(row["current_trial_plan_hash"]) != trial_plan_hash:
        raise ValueError(
            "TrialPlan is not the current plan for the hypothesis branch"
        )
