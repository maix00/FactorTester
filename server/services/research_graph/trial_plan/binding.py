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
    sample_identity: dict[str, Any] | None = None,
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
    sample = next(
        item
        for item in plan["sample_roles"]
        if normalized_run_hash in item["run_spec_hashes"]
    )
    trial_stage = str(sample["role"])
    protected = trial_stage in {"confirmation", "holdout", "validation"}
    if plan["schema_version"] < 2 and protected:
        raise ValueError(
            "protected sample roles require TrialPlan schema_version 2"
        )
    if plan["schema_version"] >= 2:
        if sample_identity is None:
            raise ValueError(
                "TrialPlan schema_version 2 requires server-derived sample identity"
            )
        if sample["sample_hash"] != sample_identity["sample_hash"]:
            raise ValueError(
                "TrialPlan sample_hash does not match server-derived sample identity"
            )
    return {
        "trial_plan_id": str(plan["trial_plan_id"]),
        "trial_plan_hash": actual_hash,
        "trial_plan_version": int(plan["version"]),
        "trial_role": str(trial_role),
        "trial_stage": trial_stage,
        "comparison_id": str(comparison_id),
        "sample_ref": str(sample["sample_ref"]),
        "sample_hash": str(sample["sample_hash"]),
        "sample_identity_hash": str(
            (sample_identity or {}).get("sample_hash") or ""
        ),
        "sample_start": str(
            (sample_identity or {}).get("sample_start") or ""
        ),
        "sample_end": str(
            (sample_identity or {}).get("sample_end") or ""
        ),
        "sample_universe_hash": str(
            (sample_identity or {}).get("universe_hash") or ""
        ),
        "sample_design_context_hash": str(
            (sample_identity or {}).get("design_context_hash") or ""
        ),
        "sample_identity_assurance": (
            "server_derived_bound"
            if plan["schema_version"] >= 2
            else "declared_legacy"
        ),
    }


def validate_branch_binding(
    conn: sqlite3.Connection,
    *,
    owner: str,
    workspace_id: str,
    instance_id: str,
    branch_id: str,
    trial_plan_hash: str,
    trial_plan_version: int,
    trial_role: str,
    sample_identity_hash: str,
    sample_start: str,
    sample_end: str,
    sample_universe_hash: str,
    run_spec_hash: str,
) -> None:
    """Bind current plan and reject reuse of protected sample evidence."""
    row = conn.execute(
        """
        SELECT b.current_trial_plan_hash,
               (
                   SELECT MAX(r.trial_plan_version)
                   FROM research_runs AS r
                   WHERE r.owner=? AND r.graph_branch_id=?
               ) AS previous_trial_plan_version,
               (
                   SELECT COUNT(*)
                   FROM research_runs AS r
                   WHERE r.owner=?
                     AND r.sample_identity_hash<>''
                     AND r.sample_universe_hash=?
                     AND r.sample_start<=?
                     AND r.sample_end>=?
                     AND (
                         r.trial_plan_hash<>?
                         OR r.trial_role<>?
                     )
               ) AS prior_protected_sample_exposure,
               (
                   SELECT COUNT(*)
                   FROM research_runs AS r
                   WHERE r.owner=? AND r.run_spec_hash=?
                     AND r.trial_role<>?
               ) AS cross_role_runspec_reuse
        FROM research_graph_instances AS i
        JOIN research_graph_branches AS b
          ON b.instance_id=i.instance_id
        WHERE i.instance_id=? AND b.branch_id=?
          AND i.owner=? AND i.workspace_id=?
        """,
        (
            owner,
            branch_id,
            owner,
            sample_universe_hash,
            sample_end,
            sample_start,
            trial_plan_hash,
            trial_role,
            owner,
            run_spec_hash,
            trial_role,
            instance_id,
            branch_id,
            owner,
            workspace_id,
        ),
    ).fetchone()
    if row is None:
        raise ValueError("owned hypothesis branch not found in workspace")
    if str(row["current_trial_plan_hash"]) != trial_plan_hash:
        raise ValueError(
            "TrialPlan is not the current plan for the hypothesis branch"
        )
    previous_version = int(row["previous_trial_plan_version"] or 0)
    if previous_version > int(trial_plan_version):
        raise ValueError("TrialPlan version regresses bound run history")
    protected = trial_role in {"confirmation", "holdout", "validation"}
    if protected and not sample_identity_hash:
        raise ValueError(
            "protected sample role requires server-derived sample identity"
        )
    if protected and int(row["prior_protected_sample_exposure"] or 0):
        raise ValueError(
            "sample identity was already exposed outside the frozen plan"
        )
    if int(row["cross_role_runspec_reuse"] or 0):
        raise ValueError("RunSpec was already opened under another role")
