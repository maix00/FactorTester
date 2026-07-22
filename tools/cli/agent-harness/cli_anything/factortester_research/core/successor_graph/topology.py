"""Business-state topology for the schema-v2 successor Graph."""

from __future__ import annotations

from typing import Any

from ..draft_graph_cycle import (
    node_conditional_operations,
    node_required_operations,
)


NODE_SPECS = {
    "hypothesis_preregistration": (
        "research",
        "Freeze the economic hypothesis, selection boundary, trial family, and rejection criteria.",
    ),
    "capability_resolution": (
        "capability",
        "Resolve semantic requirements to approved implementations for the selected product group.",
    ),
    "data_contract": (
        "validation",
        "Establish point-in-time data provenance and causal availability.",
    ),
    "factor_semantics": (
        "validation",
        "Reconcile the financial mechanism with factor source or AST, expression operators, numerical invariants, and signal timing.",
    ),
    "validation_design": ("validation", "冻结义务、对照、信息边界和 Evidence Actions。"),
    "trial_execution": ("execution", "一次只执行当前获准的 Evidence Action。"),
    "result_audit": ("audit", "裁决 admitted Evidence 对义务、Claim 和目标的影响。"),
    "research_decision": ("decision", "决定下一试验、修订或有边界暂停。"),
    "capability_gap": (
        "capability_gap",
        "Classify a missing or unsuitable capability without turning it into a factor conclusion.",
    ),
    "skill_candidate_review": (
        "audit",
        "Discover or design a quarantined skill candidate and subject it to grill audit before any installation or execution.",
    ),
    "code_improvement_required": (
        "capability_gap",
        "Pause only affected branches while an approved platform change is implemented and verified.",
    ),
    "factor_improvement_required": ("research", "修订或派生因子并登记比较义务。"),
}


NODE_REQUIREMENTS = {
    "hypothesis_preregistration": [
        "factor_semantics.risk_transfer_and_fundamentals",
        "factor_semantics.behavioral_mechanism",
        "factor_semantics.participant_ecology",
        "factor_semantics.alternatives_and_falsifiers",
        "factor_semantics.boundary_conditions",
    ],
    "capability_resolution": ["other.unclassified_material_question"],
    "data_contract": [
        "data.source_availability",
        "data.temporal_coverage",
        "data.granularity_and_depth",
        "data.required_fields",
        "data.point_in_time_semantics",
        "data.provenance_permission_version",
    ],
    "factor_semantics": [
        "factor_semantics.expression_identity",
        "factor_semantics.observable_meaning_direction_units",
        "factor_semantics.timing_and_causality",
        "factor_semantics.alternatives_and_falsifiers",
        "factor_semantics.parameterization_and_derivation",
        "factor_semantics.conditioning_semantics",
    ],
    "validation_design": [
        "trial_design.objective_and_estimand",
        "trial_design.baseline_control_ablation",
        "trial_design.temporal_validation",
        "trial_design.market_instrument_blocks",
        "trial_design.leakage_purge_embargo",
        "trial_design.search_ledger_stopping",
        "trial_design.strategy_freeze",
        "trading_strategy.signal_schedule",
    ],
    "trial_execution": [
        "trial_design.strategy_freeze",
        "trading_strategy.signal_schedule",
        "market_rules_accounting.sessions_and_trade_date",
        "market_rules_accounting.rule_versioning",
    ],
    "result_audit": [
        "statistical_validity.effect_and_uncertainty",
        "statistical_validity.dependence_robustness",
        "statistical_validity.multiple_testing",
        "statistical_validity.conflicts_and_negative_results",
        "other.unclassified_material_question",
    ],
    "research_decision": [
        "factor_semantics.alternatives_and_falsifiers",
        "statistical_validity.external_oos_consistency",
        "other.unclassified_material_question",
    ],
    "capability_gap": ["other.unclassified_material_question"],
    "skill_candidate_review": ["other.unclassified_material_question"],
    "code_improvement_required": ["other.unclassified_material_question"],
    "factor_improvement_required": [
        "factor_semantics.parameterization_and_derivation",
        "factor_semantics.derived_comparability",
        "trial_design.search_ledger_stopping",
    ],
}


EDGE_SPECS = [
    ("hypothesis__data_contract", "hypothesis_preregistration", "data_contract", "factor_semantics.alternatives_and_falsifiers"),
    ("hypothesis__capability_resolution", "hypothesis_preregistration", "capability_resolution", "other.unclassified_material_question"),
    ("data_contract__factor_semantics", "data_contract", "factor_semantics", "data.temporal_coverage"),
    ("factor_semantics__data_contract", "factor_semantics", "data_contract", "data.required_fields"),
    ("factor_semantics__validation_design", "factor_semantics", "validation_design", "factor_semantics.timing_and_causality"),
    ("validation_design__trial_execution", "validation_design", "trial_execution", "trial_design.objective_and_estimand"),
    ("trial_execution__result_audit", "trial_execution", "result_audit", "statistical_validity.effect_and_uncertainty"),
    ("result_audit__trial_execution", "result_audit", "trial_execution", "trial_design.search_ledger_stopping"),
    ("result_audit__validation_design", "result_audit", "validation_design", "trial_design.search_ledger_stopping"),
    ("result_audit__research_decision", "result_audit", "research_decision", "statistical_validity.effect_and_uncertainty"),
    ("result_audit__factor_improvement", "result_audit", "factor_improvement_required", "factor_semantics.parameterization_and_derivation"),
    ("research_decision__validation_design", "research_decision", "validation_design", "trial_design.search_ledger_stopping"),
    ("research_decision__factor_improvement", "research_decision", "factor_improvement_required", "factor_semantics.parameterization_and_derivation"),
    ("factor_improvement__hypothesis", "factor_improvement_required", "hypothesis_preregistration", "factor_semantics.derived_comparability"),
    ("any_node__capability_gap", "*", "capability_gap", "other.unclassified_material_question"),
    ("capability_gap__capability_resolution", "capability_gap", "capability_resolution", "other.unclassified_material_question"),
    ("capability_resolution__capability_gap", "capability_resolution", "capability_gap", "other.unclassified_material_question"),
    ("data_contract__capability_gap", "data_contract", "capability_gap", "data.source_availability"),
    ("capability_gap__data_contract", "capability_gap", "data_contract", "data.source_availability"),
    ("capability_gap__blocked_closure", "capability_gap", "capability_gap", "other.unclassified_material_question"),
    ("capability_resolution__data_contract", "capability_resolution", "data_contract", "data.source_availability"),
    ("capability_gap__skill_review", "capability_gap", "skill_candidate_review", "other.unclassified_material_question"),
    ("capability_gap__code_improvement", "capability_gap", "code_improvement_required", "other.unclassified_material_question"),
    ("skill_review__capability_resolution", "skill_candidate_review", "capability_resolution", "other.unclassified_material_question"),
    ("code_improvement__capability_resolution", "code_improvement_required", "capability_resolution", "other.unclassified_material_question"),
]


EDGE_SERVER_ACTIONS = {
    "data_contract__factor_semantics": "bind_data_availability",
    "data_contract__capability_gap": "bind_data_availability",
    "capability_gap__data_contract": "bind_data_availability",
    "factor_semantics__validation_design": "bind_factor_semantics",
}


EDGE_TYPES = {
    "hypothesis__capability_resolution": "recommended",
    "any_node__capability_gap": "failure",
    "capability_resolution__capability_gap": "failure",
    "data_contract__capability_gap": "failure",
    "capability_gap__capability_resolution": "recovery",
    "capability_gap__data_contract": "recovery",
    "capability_gap__blocked_closure": "recovery",
    "skill_review__capability_resolution": "recovery",
    "code_improvement__capability_resolution": "recovery",
}


def build_nodes() -> list[dict[str, Any]]:
    required_operations = node_required_operations()
    conditional_operations = node_conditional_operations()
    return [
        {
            "node_id": node_id,
            "purpose": purpose,
            "enforcement": "deterministic",
            "required_capabilities": required_operations.get(node_id, []),
            "conditional_capabilities": conditional_operations.get(node_id, []),
            "entry_requirement_refs": NODE_REQUIREMENTS[node_id],
            "entry_report_refs": [f"report.node.{node_id}.entry"],
            "node_report_refs": [f"report.node.{node_id}.action"],
        }
        for node_id, (_, purpose) in NODE_SPECS.items()
    ]


def build_edges() -> list[dict[str, Any]]:
    values = []
    for edge_id, from_node, to_node, _ in EDGE_SPECS:
        values.append({
            "edge_id": edge_id,
            "from_node": from_node,
            "to_node": to_node,
            "edge_type": EDGE_TYPES.get(edge_id, "conditional"),
            "guard": {},
            "required_evidence": [],
            "required_research_evidence": [],
            "required_transition_facts": [],
            "risk_level": "L2" if "capability" in edge_id or "improvement" in edge_id else "L1",
            "report_requirement_refs": [f"report.edge.{edge_id}"],
        })
        if edge_id in EDGE_SERVER_ACTIONS:
            values[-1]["server_action"] = EDGE_SERVER_ACTIONS[edge_id]
    return values
