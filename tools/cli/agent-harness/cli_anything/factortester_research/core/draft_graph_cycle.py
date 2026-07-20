"""Research Cycle operations governed by existing lifecycle nodes."""

from __future__ import annotations

from typing import Any


def research_cycle_operations() -> list[dict[str, Any]]:
    """Declare provider-neutral outputs; these are not Graph nodes or edges."""
    return [
        {
            "capability_id": "research-obligation.discover",
            "output_kind": "AdjudicationProposal",
            "freshness_owner": "research_cycle_checkpoint",
        },
        {
            "capability_id": "research-trial.synthesize",
            "output_kind": "TrialPlan",
            "freshness_owner": "trial_plan_hash",
        },
        {
            "capability_id": "research-evidence.adjudicate",
            "output_kind": "AdjudicationProposal",
            "freshness_owner": "research_cycle_checkpoint",
        },
        {
            "capability_id": "research-exhaustion.assess",
            "output_kind": "SearchExhaustionProposal",
            "freshness_owner": "research_cycle_checkpoint",
        },
    ]


def maintenance_operations() -> list[dict[str, Any]]:
    return [{
        "capability_id": "research-methodology.impact",
        "trigger_predicate": {
            "field": "maintenance.semantic_change_proposed",
            "equals": True,
        },
        "output_kind": "MethodologyChangeProposal",
        "authority": "maintenance_case_and_human_audit",
    }]


def node_required_operations() -> dict[str, list[str]]:
    return {
        "hypothesis_preregistration": ["research-obligation.discover"],
        "validation_design": ["research-trial.synthesize"],
        "result_audit": ["research-evidence.adjudicate"],
    }


def node_conditional_operations() -> dict[str, list[dict[str, Any]]]:
    return {
        "factor_semantics": [{
            "capability_id": "research-obligation.discover",
            "predicate": {"any": [
                {
                    "field": "research.semantic_discovery_stale",
                    "equals": True,
                },
                {
                    "field": (
                        "research."
                        "semantic_inspection_exposed_material_question"
                    ),
                    "equals": True,
                },
            ]},
            "explanation": (
                "factor, data, timing, product, strategy, or permitted-use "
                "semantics changed, or their inspection exposed a material "
                "unresolved research question"
            ),
        }],
        "result_audit": [{
            "capability_id": "research-obligation.discover",
            "predicate": {
                "field": "research.evidence_exposes_new_question",
                "equals": True,
            },
            "explanation": (
                "accepted evidence changes an assumption, alternative, "
                "scope, or material unknown"
            ),
        }],
        "research_decision": [
            {
                "capability_id": "research-obligation.discover",
                "predicate": {
                    "field": "research.closure_discovery_stale",
                    "equals": True,
                },
                "explanation": (
                    "bounded closure requires a fresh first-principles "
                    "discovery checkpoint"
                ),
            },
            {
                "capability_id": "research-exhaustion.assess",
                "predicate": {
                    "field": "research.closure_requested",
                    "equals": True,
                },
                "explanation": (
                    "the current Decision Contract is proposed for bounded "
                    "closure"
                ),
            },
        ],
    }


def review_policy() -> dict[str, str]:
    return {
        "routine_deterministic_transition": "none",
        "exact_preregistered_rule": "deterministic_validation_only",
        "material_semantic_or_conflicting_adjudication": (
            "one_relevant_independent_reviewer"
        ),
        "bounded_closure": "one_independent_closure_challenger",
        "unresolved_disagreement": "one_additional_reviewer",
        "graph_methodology_or_backend_policy_change": (
            "maintenance_case_documented_grill_and_human_audit"
        ),
    }
