"""Canonical TrialPlan stage-policy semantics."""

from __future__ import annotations

from typing import Any

from .fields import identifier_field, identifier_list, object_field


STAGE_RANK = {
    "selection": 0,
    "validation": 1,
    "confirmation": 2,
    "holdout": 2,
}
TERMINAL_STAGES = frozenset({"confirmation", "holdout"})


def canonical_stage_policy(value: Any) -> dict[str, Any]:
    policy = object_field(
        value,
        "trial_plan.stage_policy",
        fields=frozenset({
            "ordered_stages",
            "entry_stage",
            "entry_basis_ref",
        }),
    )
    stages = canonical_stage_order(
        policy.get("ordered_stages"),
        field="trial_plan.stage_policy.ordered_stages",
    )
    entry_stage = identifier_field(
        policy.get("entry_stage"),
        "trial_plan.stage_policy.entry_stage",
    )
    if entry_stage != stages[0]:
        raise ValueError("TrialPlan entry_stage must be the first stage")
    return {
        "ordered_stages": stages,
        "entry_stage": entry_stage,
        "entry_basis_ref": identifier_field(
            policy.get("entry_basis_ref"),
            "trial_plan.stage_policy.entry_basis_ref",
        ),
    }


def canonical_stage_order(value: Any, *, field: str) -> list[str]:
    stages = identifier_list(value, field, allow_empty=False)
    if any(stage not in STAGE_RANK for stage in stages):
        raise ValueError(f"{field} contains an unsupported stage")
    ranks = [STAGE_RANK[stage] for stage in stages]
    if ranks != sorted(ranks) or len(ranks) != len(set(ranks)):
        raise ValueError("TrialPlan stages must follow canonical stage order")
    return stages


def validate_stage_samples(
    *,
    policy: dict[str, Any],
    sample_roles: list[dict[str, Any]],
) -> None:
    planned_roles = {str(item["role"]) for item in sample_roles}
    expected_roles = set(policy["ordered_stages"])
    if planned_roles != expected_roles:
        raise ValueError(
            "TrialPlan v4 sample roles must match ordered stages"
        )
