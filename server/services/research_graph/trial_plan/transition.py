"""TrialPlan freeze rules applied by graph branch transitions."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .contract import canonical_trial_plan, trial_plan_hash


def prepare_trial_plan_evidence(
    evidence: dict[str, Any],
) -> tuple[dict[str, Any], str, bool]:
    """Canonicalize an optional plan before opening the graph transaction."""
    value = deepcopy(evidence)
    has_body = "trial_plan" in value
    supplied_hash = str(value.get("trial_plan_hash") or "").removeprefix(
        "sha256:"
    )
    if not has_body:
        return value, supplied_hash, False
    plan = canonical_trial_plan(value["trial_plan"])
    actual_hash = trial_plan_hash(plan)
    if supplied_hash and supplied_hash != actual_hash:
        raise ValueError("trial_plan_hash does not match TrialPlan body")
    value["trial_plan"] = plan
    value["trial_plan_hash"] = actual_hash
    return value, actual_hash, True


def validate_trial_plan_transition(
    *,
    current_hash: str,
    proposed_hash: str,
    has_body: bool,
) -> str:
    """Require one body when freezing and hashes only for later references."""
    if has_body:
        if proposed_hash == current_hash:
            raise ValueError(
                "current TrialPlan body is immutable and already persisted"
            )
        return proposed_hash
    if proposed_hash:
        if not current_hash:
            raise ValueError(
                "TrialPlan body is required when establishing a plan"
            )
        if proposed_hash != current_hash:
            raise ValueError(
                "changing TrialPlan hash requires a new immutable body"
            )
    return current_hash
