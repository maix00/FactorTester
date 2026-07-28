"""ResearchRun binding validation for one frozen TrialPlan."""

from __future__ import annotations

import sqlite3
from typing import Any

import orjson

from .contract import canonical_trial_plan, trial_plan_hash
from .run_action_binding import (
    normalize_v5_run_binding,
    validate_v5_action_release,
)
from .stage_projection import validate_trial_stage_projection


def normalize_run_binding(
    *,
    trial_plan: dict[str, Any],
    expected_hash: str,
    expected_version: int,
    run_spec_hash: str,
    trial_role: str,
    comparison_id: str,
    sample_identity: dict[str, Any] | None = None,
    evidence_action_id: str = "",
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
    if plan["schema_version"] == 5:
        action_binding = normalize_v5_run_binding(
            plan=plan,
            run_spec_hash=normalized_run_hash,
            trial_role=trial_role,
            comparison_id=comparison_id,
            sample_identity=sample_identity,
            evidence_action_id=evidence_action_id,
        )
        return {
            "trial_plan_id": str(plan["trial_plan_id"]),
            "trial_plan_hash": actual_hash,
            "trial_plan_schema_version": 5,
            "trial_plan_version": int(plan["version"]),
            "decision_contract_hash": str(plan["decision_contract_hash"]),
            "methodology_hash": str(plan["methodology_hash"]),
            **action_binding,
            **_sample_identity_fields(sample_identity),
        }
    if evidence_action_id:
        raise ValueError("legacy TrialPlan cannot bind an Evidence Action")
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
        "trial_plan_schema_version": int(plan["schema_version"]),
        "trial_plan_version": int(plan["version"]),
        "decision_contract_hash": str(
            plan.get("decision_contract_hash") or ""
        ),
        "methodology_hash": str(plan.get("methodology_hash") or ""),
        "trial_role": str(trial_role),
        "trial_stage": trial_stage,
        "comparison_id": str(comparison_id),
        "sample_ref": str(sample["sample_ref"]),
        "sample_hash": str(sample["sample_hash"]),
        **_sample_identity_fields(sample_identity),
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
    trial_plan_schema_version: int,
    trial_plan_version: int,
    trial_role: str,
    trial_stage: str,
    sample_identity_hash: str,
    sample_start: str,
    sample_end: str,
    sample_universe_hash: str,
    run_spec_hash: str,
    evidence_action_id: str = "",
    action_input_hash: str = "",
    expected_checkpoint_hash: str = "",
    expected_latest_trace_id: str = "",
    trial_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Bind current plan and reject reuse of protected sample evidence."""
    row = conn.execute(
        """
        SELECT b.branch_id, b.instance_id, b.current_trial_plan_hash,
               b.current_node, b.latest_trace_id,
               b.trial_stage_projection_json,
               w.lifecycle AS work_package_lifecycle,
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
                         OR (?<5 AND r.trial_stage<>?)
                     )
               ) AS prior_protected_sample_exposure,
               (
                   SELECT COUNT(*)
                   FROM research_runs AS r
                   WHERE r.owner=? AND r.run_spec_hash=?
                     AND r.trial_stage<>?
               ) AS cross_role_runspec_reuse,
               (
                   SELECT COUNT(*)
                   FROM research_runs AS r
                   WHERE r.owner=? AND r.graph_branch_id=?
                     AND r.trial_plan_hash=?
                     AND r.evidence_action_id=?
                     AND r.run_spec_hash=?
               ) AS duplicate_action_run
        FROM research_graph_instances AS i
        JOIN research_graph_branches AS b
          ON b.instance_id=i.instance_id
        LEFT JOIN research_work_packages AS w
          ON w.owner=i.owner
         AND w.work_package_id=COALESCE(
             NULLIF(i.work_package_id, ''), i.instance_id
         )
        WHERE i.instance_id=? AND b.branch_id=?
          AND i.owner=? AND i.workspace_id=?
          AND b.is_current_incarnation=1
        """,
        (
            owner,
            branch_id,
            owner,
            sample_universe_hash,
            sample_end,
            sample_start,
            trial_plan_hash,
            trial_plan_schema_version,
            trial_stage,
            owner,
            run_spec_hash,
            trial_stage,
            owner,
            branch_id,
            trial_plan_hash,
            evidence_action_id,
            run_spec_hash,
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
    action_snapshot: dict[str, Any] = {}
    if trial_plan_schema_version == 5:
        if trial_plan is None:
            raise ValueError("TrialPlan schema v5 requires the canonical plan")
        if str(row["work_package_lifecycle"] or "") != "active":
            raise ValueError("Evidence Action requires an active Work Package")
        action_snapshot = validate_v5_action_release(
            row=row,
            plan=trial_plan,
            evidence_action_id=evidence_action_id,
            action_input_hash=action_input_hash,
            expected_checkpoint_hash=expected_checkpoint_hash,
            expected_latest_trace_id=expected_latest_trace_id,
        )
        projection_value = {}
    else:
        projection_value = orjson.loads(
            str(row["trial_stage_projection_json"]) or "{}"
        )
    if trial_plan_schema_version == 4 and not projection_value:
        raise ValueError(
            "TrialPlan schema v4 requires a bound stage projection"
        )
    if projection_value:
        projection = validate_trial_stage_projection(projection_value)
        if projection["current_stage"] != trial_stage:
            raise ValueError(
                "RunSpec sample role is not the current TrialPlan stage"
            )
        if (
            not projection["execution_node"]
            or projection["execution_node"] != str(row["current_node"])
        ):
            raise ValueError(
                "ResearchRun is not at the TrialPlan execution node"
            )
    previous_version = int(row["previous_trial_plan_version"] or 0)
    if previous_version > int(trial_plan_version):
        raise ValueError("TrialPlan version regresses bound run history")
    protected = trial_stage in {"confirmation", "holdout", "validation"}
    if protected and not sample_identity_hash:
        raise ValueError(
            "protected sample role requires server-derived sample identity"
        )
    if protected and int(row["prior_protected_sample_exposure"] or 0):
        raise ValueError(
            "sample identity was already exposed outside the frozen plan"
        )
    if int(row["cross_role_runspec_reuse"] or 0):
        raise ValueError("RunSpec was already opened under another stage")
    if evidence_action_id and int(row["duplicate_action_run"] or 0):
        raise ValueError("Evidence Action already has this ResearchRun")
    # The branch can advance after a Job is submitted.  Preserve the node that
    # authorized this Run inside the same transaction that validates the
    # TrialPlan, rather than inferring a later attachment target from a moving
    # branch head.
    action_snapshot["execution_node"] = str(row["current_node"])
    return action_snapshot


def _sample_identity_fields(
    sample_identity: dict[str, Any] | None,
) -> dict[str, str]:
    value = sample_identity or {}
    return {
        "sample_identity_hash": str(value.get("sample_hash") or ""),
        "sample_start": str(value.get("sample_start") or ""),
        "sample_end": str(value.get("sample_end") or ""),
        "sample_universe_hash": str(value.get("universe_hash") or ""),
        "sample_design_context_hash": str(
            value.get("design_context_hash") or ""
        ),
    }
