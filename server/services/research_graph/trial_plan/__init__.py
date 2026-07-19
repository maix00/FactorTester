"""Immutable TrialPlan contracts and bindings."""

from .binding import (
    normalize_run_binding,
    validate_branch_binding,
)
from .contract import (
    TRIAL_PLAN_SCHEMA_VERSION,
    canonical_trial_plan,
    trial_plan_hash,
)
from .retention import trial_plan_trace_retention
from .stage_projection import (
    agent_trial_stage_summary,
    advance_trial_stage,
    project_trial_plan_stage,
    trial_stage_guard_facts,
    validate_trial_stage_projection,
)
from .transition import (
    prepare_trial_plan_evidence,
    validate_trial_plan_cycle_binding,
    validate_trial_plan_transition,
)

__all__ = [
    "TRIAL_PLAN_SCHEMA_VERSION",
    "agent_trial_stage_summary",
    "advance_trial_stage",
    "canonical_trial_plan",
    "normalize_run_binding",
    "prepare_trial_plan_evidence",
    "project_trial_plan_stage",
    "trial_plan_hash",
    "trial_plan_trace_retention",
    "trial_stage_guard_facts",
    "validate_branch_binding",
    "validate_trial_plan_cycle_binding",
    "validate_trial_plan_transition",
    "validate_trial_stage_projection",
]
