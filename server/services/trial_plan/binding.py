"""Bind one direct TrialPlan member to an immutable ResearchRun."""

from __future__ import annotations

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
    evidence_action_id: str = "",
) -> dict[str, Any]:
    """Validate one planned RunSpec without any graph or branch identity."""
    if evidence_action_id:
        raise ValueError("Evidence Actions are not part of direct TrialPlans")
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
    run_hash = str(run_spec_hash).removeprefix("sha256:")
    role = str(trial_role or "").strip()
    comparison_id = str(comparison_id or "").strip()
    comparison = next((
        item for item in plan["comparisons"]
        if item["comparison_id"] == comparison_id
    ), None)
    if comparison is None:
        raise ValueError("comparison_id is not declared by TrialPlan")
    if not any(
        member["run_spec_hash"] == run_hash
        and member["trial_role"] == role
        for member in comparison["members"]
    ):
        raise ValueError(
            "RunSpec hash and trial_role are not a planned comparison member"
        )
    sample = next((
        item for item in plan["sample_roles"]
        if run_hash in item["run_spec_hashes"]
    ), None)
    if sample is None:
        raise ValueError("TrialPlan has no sample role for the RunSpec")
    trial_stage = str(sample["role"])
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
        "binding_origin": "agent_direct",
        "trial_plan": plan,
        "trial_plan_id": str(plan["trial_plan_id"]),
        "trial_plan_hash": actual_hash,
        "trial_plan_schema_version": int(plan["schema_version"]),
        "trial_plan_version": int(plan["version"]),
        "decision_contract_hash": "",
        "methodology_hash": "",
        "trial_role": role,
        "trial_stage": trial_stage,
        "comparison_id": comparison_id,
        "sample_ref": str(sample["sample_ref"]),
        "sample_hash": str(sample["sample_hash"]),
        **_sample_identity_fields(sample_identity),
        "sample_identity_assurance": (
            "server_derived_bound"
            if plan["schema_version"] >= 2
            else "declared_legacy"
        ),
    }


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
