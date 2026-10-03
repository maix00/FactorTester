"""Graph-independent TrialPlan bindings for direct Agent experiments."""

from __future__ import annotations

import re
from typing import Any

from server.services.trial_plan import (
    canonical_trial_plan,
    trial_plan_hash,
)


_HASH = re.compile(r"^[0-9a-f]{64}$")


def create_binding(
    *,
    trial_plan: dict[str, Any],
    run_spec_hash: str,
    trial_role: str,
    comparison_id: str,
) -> dict[str, Any]:
    """Validate one direct plan member and return its immutable Run binding."""
    if not isinstance(trial_plan, dict):
        raise ValueError("trial_plan must be an object")
    if int(trial_plan.get("schema_version") or 0) == 5:
        raise ValueError(
            "TrialPlan schema v5 is unsupported by the direct experiment workflow"
        )
    plan = canonical_trial_plan(trial_plan)
    normalized_hash = str(run_spec_hash).removeprefix("sha256:")
    if not _HASH.fullmatch(normalized_hash):
        raise ValueError("run_spec_hash must be lowercase sha256")
    role = str(trial_role or "").strip()
    comparison = str(comparison_id or "").strip()
    if not role or not comparison:
        raise ValueError("trial_role and comparison_id are required")
    selected = next((
        item for item in plan["comparisons"]
        if item["comparison_id"] == comparison
    ), None)
    if selected is None:
        raise ValueError("comparison_id is not declared by TrialPlan")
    if not any(
        item["run_spec_hash"] == normalized_hash
        and item["trial_role"] == role
        for item in selected["members"]
    ):
        raise ValueError(
            "RunSpec hash and trial_role are not a planned comparison member"
        )
    digest = trial_plan_hash(plan)
    return {
        "binding_origin": "agent_direct",
        "trial_plan": plan,
        "trial_plan_hash": digest,
        "trial_plan_ref": f"trial-plan:sha256:{digest}",
        "trial_plan_version": int(plan["version"]),
        "trial_role": role,
        "comparison_id": comparison,
    }
