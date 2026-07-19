"""Transition declarations for the product-neutral Draft Graph."""

from __future__ import annotations

from typing import Any

def edge(
    edge_id: str,
    from_node: str,
    to_node: str,
    *,
    edge_type: str = "conditional",
    guard: dict[str, Any] | None = None,
    risk_level: str = "L1",
    required_research_evidence: list[str] | None = None,
    required_transition_facts: list[str] | None = None,
    counterexamples: list[str] | None = None,
) -> dict[str, Any]:
    research_evidence = required_research_evidence or []
    transition_facts = required_transition_facts or []
    return {
        "edge_id": edge_id,
        "from_node": from_node,
        "to_node": to_node,
        "edge_type": edge_type,
        "guard": guard or {},
        "required_evidence": [*research_evidence, *transition_facts],
        "required_research_evidence": research_evidence,
        "required_transition_facts": transition_facts,
        "counterexamples": counterexamples or [],
        "risk_level": risk_level,
    }

def build_draft_edges() -> list[dict[str, Any]]:
    """Return the audited transition topology."""
    return [
        edge(
            "any_node__capability_gap",
            "*",
            "capability_gap",
            edge_type="failure",
            guard={"mandatory_binding_missing": True},
            risk_level="L2",
            required_transition_facts=[
                "target node and missing capability ids",
            ],
        ),
        edge(
            "hypothesis__capability_resolution",
            "hypothesis_preregistration",
            "capability_resolution",
            edge_type="recommended",
            guard={
                "hypothesis_frozen": True,
                "obligation_discovery_checkpoint_fresh": True,
            },
        ),
        edge(
            "capability_resolution__data_contract",
            "capability_resolution",
            "data_contract",
            guard={"mandatory_bindings_resolved": True},
        ),
        edge(
            "capability_resolution__capability_gap",
            "capability_resolution",
            "capability_gap",
            edge_type="failure",
            guard={"mandatory_binding_missing": True},
            risk_level="L2",
            required_transition_facts=[
                "missing capability ids and attempted bindings",
            ],
        ),
        edge(
            "data_contract__factor_semantics",
            "data_contract",
            "factor_semantics",
            guard={
                "point_in_time_contract_valid": True,
                "data_availability_profile_bound": True,
                "data_availability_constraints_satisfied": True,
                "material_data_obligations_adjudicated_or_not_triggered": True,
            },
        ),
        edge(
            "factor_semantics__validation_design",
            "factor_semantics",
            "validation_design",
            guard={
                "causal_semantics_valid": True,
                "semantic_discovery_fresh_or_not_triggered": True,
            },
        ),
        edge(
            "validation_design__cheap_diagnostics",
            "validation_design",
            "cheap_factor_diagnostics",
            guard={
                "selection_and_trial_plan_frozen": True,
                "actionable_obligations_planned_or_bounded": True,
            },
        ),
        edge(
            "cheap_diagnostics__backtest",
            "cheap_factor_diagnostics",
            "authoritative_backtest",
            guard={
                "preregistered_execution_eligibility_satisfied": True,
                "current_trial_stage_executable": True,
            },
        ),
        edge(
            "cheap_diagnostics__result_audit",
            "cheap_factor_diagnostics",
            "result_audit",
            guard={
                "diagnostic_evidence_complete": True,
                "further_execution_eligible": False,
            },
            risk_level="L2",
            required_research_evidence=[
                "frozen diagnostic specification and factual evidence",
            ],
        ),
        edge(
            "backtest__statistical_robustness",
            "authoritative_backtest",
            "statistical_robustness",
            guard={
                "terminal_job_evidence_retained": True,
                "net_return_series_available": True,
            },
        ),
        edge(
            "statistical_robustness__result_audit",
            "statistical_robustness",
            "result_audit",
            guard={"uncertainty_evidence_complete": True},
            risk_level="L2",
            required_research_evidence=[
                "predeclared uncertainty method and factual evidence",
            ],
        ),
        edge(
            "result_audit__factor_improvement",
            "result_audit",
            "factor_improvement_required",
            edge_type="recovery",
            guard={
                "audit_complete": True,
                "no_unresolved_evidence_integrity_or_capability_gap": True,
                "adjudication_applied_or_explicit_noop": True,
                "adjudication_route_bound": True,
                "factor_revision_authorized": True,
                "next_trial_stage_required": False,
                "current_trial_stage_allows_revision": True,
                "new_falsifiable_hypothesis_proposed": True,
                "protected_sample_reuse_forbidden": True,
                "remaining_revision_budget_positive": True,
            },
            risk_level="L2",
            required_transition_facts=[
                "accepted adjudication, new falsifiable mechanism, and "
                "remaining revision budget",
            ],
        ),
        edge(
            "result_audit__validation_design",
            "result_audit",
            "validation_design",
            edge_type="recovery",
            guard={
                "audit_complete": True,
                "adjudication_applied_or_explicit_noop": True,
                "adjudication_route_bound": True,
                "next_trial_stage_required": True,
                "trial_stage_advance_authorized": True,
            },
            risk_level="L2",
            required_transition_facts=[
                "accepted adjudication and server-derived next stage",
            ],
        ),
        edge(
            "result_audit__research_decision",
            "result_audit",
            "research_decision",
            guard={
                "audit_complete": True,
                "no_unresolved_evidence_integrity_or_capability_gap": True,
                "adjudication_applied_or_explicit_noop": True,
                "adjudication_route_bound": True,
                "closure_discovery_fresh_or_not_requested": True,
                "factor_revision_authorized": False,
                "next_trial_stage_required": False,
            },
            risk_level="L2",
        ),
        edge(
            "factor_improvement__hypothesis",
            "factor_improvement_required",
            "hypothesis_preregistration",
            edge_type="recovery",
            guard={
                "new_hypothesis_version_recorded": True,
                "trial_ledger_incremented": True,
                "holdout_status_recorded": True,
                "factor_change_retained": True,
            },
            risk_level="L2",
            required_transition_facts=[
                "new hypothesis version, trial-ledger delta, and holdout status",
            ],
        ),
        edge(
            "capability_gap__capability_resolution",
            "capability_gap",
            "capability_resolution",
            edge_type="recovery",
            guard={"approved_binding_now_available": True},
            risk_level="L2",
        ),
        edge(
            "capability_gap__skill_review",
            "capability_gap",
            "skill_candidate_review",
            guard={"reusable_skill_candidate": True},
            risk_level="L3",
        ),
        edge(
            "capability_gap__code_improvement",
            "capability_gap",
            "code_improvement_required",
            guard={"authoritative_backend_change_required": True},
            risk_level="L3",
        ),
        edge(
            "skill_review__capability_resolution",
            "skill_candidate_review",
            "capability_resolution",
            edge_type="recovery",
            guard={"skill_execution_approved": True},
            risk_level="L3",
            required_transition_facts=[
                "grill audit and implementation validation",
            ],
        ),
        edge(
            "code_improvement__capability_resolution",
            "code_improvement_required",
            "capability_resolution",
            edge_type="recovery",
            guard={"platform_change_approved_and_verified": True},
            risk_level="L3",
        ),
    ]
