"""Schema-v5 TrialPlan metadata and Evidence Action assembly."""

from __future__ import annotations

from typing import Any

from .evidence_actions import canonical_evidence_actions
from .fields import identifier_field, identifier_list, sha256_field


MAX_SECONDARY_OBLIGATIONS = 31
MAX_DESIGN_REFS = 16


def canonical_v5_metadata(
    plan: dict[str, Any],
    *,
    stage_policy: dict[str, Any],
) -> dict[str, Any]:
    primary = identifier_field(
        plan.get("primary_obligation_ref"),
        "trial_plan.primary_obligation_ref",
    )
    secondary = identifier_list(
        plan.get("secondary_obligation_refs"),
        "trial_plan.secondary_obligation_refs",
    )
    if primary in secondary:
        raise ValueError("primary obligation cannot also be secondary")
    if len(secondary) > MAX_SECONDARY_OBLIGATIONS:
        raise ValueError(
            "trial_plan.secondary_obligation_refs must contain at most 31 items"
        )
    design_refs = _bounded_refs(
        plan.get("design_evidence_refs"),
        "trial_plan.design_evidence_refs",
    )
    reopen_refs = _bounded_refs(
        plan.get("reopen_predicate_refs"),
        "trial_plan.reopen_predicate_refs",
    )
    obligation_refs = {primary, *secondary}
    return {
        "decision_contract_hash": sha256_field(
            plan.get("decision_contract_hash"),
            "trial_plan.decision_contract_hash",
        ),
        "methodology_hash": sha256_field(
            plan.get("methodology_hash"),
            "trial_plan.methodology_hash",
        ),
        "parent_trial_plan_hash": (
            None
            if plan.get("parent_trial_plan_hash") is None
            else sha256_field(
                plan.get("parent_trial_plan_hash"),
                "trial_plan.parent_trial_plan_hash",
            )
        ),
        "stage_policy": stage_policy,
        "primary_obligation_ref": primary,
        "secondary_obligation_refs": secondary,
        "design_evidence_refs": design_refs,
        "trial_ledger_ref": identifier_field(
            plan.get("trial_ledger_ref"),
            "trial_plan.trial_ledger_ref",
        ),
        "holdout_access_ledger_ref": identifier_field(
            plan.get("holdout_access_ledger_ref"),
            "trial_plan.holdout_access_ledger_ref",
        ),
        "reopen_predicate_refs": reopen_refs,
        "evidence_actions": canonical_evidence_actions(
            plan.get("evidence_actions"),
            obligation_refs=obligation_refs,
            stage_ids=set(stage_policy["ordered_stage_ids"]),
        ),
    }


def _bounded_refs(value: Any, path: str) -> list[str]:
    refs = identifier_list(value, path, allow_empty=False)
    if len(refs) > MAX_DESIGN_REFS:
        raise ValueError(f"{path} must contain at most {MAX_DESIGN_REFS} items")
    return refs
