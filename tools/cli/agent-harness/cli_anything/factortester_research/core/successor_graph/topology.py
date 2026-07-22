"""Business-state topology for the schema-v2 successor Graph."""

from __future__ import annotations

from typing import Any


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
        "hypothesis_validity.mechanism_chain",
        "hypothesis_validity.falsifiable_predictions",
        "hypothesis_validity.alternative_explanations",
        "hypothesis_validity.boundary_conditions",
    ],
    "capability_resolution": ["other.unclassified_material_question"],
    "data_contract": [
        "data.product_source_availability",
        "data.trial_window_coverage",
        "data.point_in_time_integrity",
    ],
    "factor_semantics": [
        "factor_semantics.observable_meaning_and_direction",
        "factor_semantics.expression_validity",
        "factor_semantics.causal_timing",
        "factor_semantics.expression_parameterization",
    ],
    "validation_design": [
        "trial_design_validity.target_contrast",
        "trial_design_validity.controlled_variable_isolation",
        "trial_design_validity.information_partition",
        "trial_design_validity.adaptation_and_ledger",
        "trial_design_validity.stop_and_reopen_rule",
        "statistical_validity.estimand_and_metric",
        "statistical_validity.method_assumptions",
    ],
    "trial_execution": [
        "trial_design_validity.controlled_variable_isolation",
        "market_execution_accounting.backtest_live_consistency",
    ],
    "result_audit": [
        "statistical_validity.uncertainty_and_effect_size",
        "statistical_validity.selection_and_multiplicity",
        "statistical_validity.sensitivity_and_falsification",
        "other.unclassified_material_question",
    ],
    "research_decision": [
        "hypothesis_validity.falsifiable_predictions",
        "other.unclassified_material_question",
    ],
    "capability_gap": ["other.unclassified_material_question"],
    "skill_candidate_review": ["other.unclassified_material_question"],
    "code_improvement_required": ["other.unclassified_material_question"],
    "factor_improvement_required": [
        "hypothesis_validity.derived_incremental_mechanism",
        "factor_semantics.derived_comparability",
        "trial_design_validity.adaptation_and_ledger",
    ],
}


EDGE_SPECS = [
    ("hypothesis__data_contract", "hypothesis_preregistration", "data_contract", "hypothesis_validity.falsifiable_predictions"),
    ("hypothesis__capability_resolution", "hypothesis_preregistration", "capability_resolution", "other.unclassified_material_question"),
    ("data_contract__factor_semantics", "data_contract", "factor_semantics", "data.trial_window_coverage"),
    ("factor_semantics__data_contract", "factor_semantics", "data_contract", "data.trial_window_coverage"),
    ("factor_semantics__validation_design", "factor_semantics", "validation_design", "factor_semantics.causal_timing"),
    ("validation_design__trial_execution", "validation_design", "trial_execution", "trial_design_validity.target_contrast"),
    ("trial_execution__result_audit", "trial_execution", "result_audit", "statistical_validity.estimand_and_metric"),
    ("result_audit__trial_execution", "result_audit", "trial_execution", "trial_design_validity.stop_and_reopen_rule"),
    ("result_audit__validation_design", "result_audit", "validation_design", "trial_design_validity.adaptation_and_ledger"),
    ("result_audit__research_decision", "result_audit", "research_decision", "statistical_validity.uncertainty_and_effect_size"),
    ("result_audit__factor_improvement", "result_audit", "factor_improvement_required", "hypothesis_validity.derived_incremental_mechanism"),
    ("research_decision__validation_design", "research_decision", "validation_design", "trial_design_validity.stop_and_reopen_rule"),
    ("research_decision__factor_improvement", "research_decision", "factor_improvement_required", "hypothesis_validity.derived_incremental_mechanism"),
    ("factor_improvement__hypothesis", "factor_improvement_required", "hypothesis_preregistration", "factor_semantics.derived_comparability"),
    ("any_node__capability_gap", "*", "capability_gap", "other.unclassified_material_question"),
    ("capability_gap__capability_resolution", "capability_gap", "capability_resolution", "other.unclassified_material_question"),
    ("capability_resolution__capability_gap", "capability_resolution", "capability_gap", "other.unclassified_material_question"),
    ("data_contract__capability_gap", "data_contract", "capability_gap", "data.product_source_availability"),
    ("capability_gap__data_contract", "capability_gap", "data_contract", "data.product_source_availability"),
    ("capability_gap__blocked_closure", "capability_gap", "capability_gap", "other.unclassified_material_question"),
    ("capability_resolution__data_contract", "capability_resolution", "data_contract", "data.product_source_availability"),
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
    return [
        {
            "node_id": node_id,
            "purpose": purpose,
            "enforcement": "deterministic",
            "required_capabilities": [],
            "conditional_capabilities": [],
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
