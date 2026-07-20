"""Observed projection of the existing fixed Harness workflow."""

from __future__ import annotations

from typing import Any

from .graph_protocol import validate_graph

_KIND_BY_PHASE = {
    "inspect_data_availability": "validation",
    "inspect_factor_expr_dsl": "validation",
    "prepare_factor_workspace": "research",
    "understand_factor_source": "research",
    "design_trial_plan": "validation",
    "create_research_workspace": "execution",
    "freeze_configuration": "execution",
    "submit_run": "execution",
    "observe_jobs": "execution",
    "control_jobs": "execution",
    "audit_results": "audit",
}

_CAPABILITY_BY_PHASE = {
    "inspect_data_availability": "data-availability.inspect",
    "inspect_factor_expr_dsl": "factor-expr.operator-registry.inspect",
    "prepare_factor_workspace": "factor-workspace.prepare",
    "understand_factor_source": "factor-workspace.source.inspect",
    "design_trial_plan": "research-trial.synthesize",
    "create_research_workspace": "research-workspace.create",
    "freeze_configuration": "research-configuration.freeze",
    "submit_run": "research-run.submit",
    "observe_jobs": "research-job.observe",
    "control_jobs": "research-job.control",
    "audit_results": "research-result.audit",
}

def build_observed_graph(plan: list[dict[str, Any]]) -> dict[str, Any]:
    """Project today's advisory plan and persisted session states into a graph.

    This is deliberately descriptive. It does not claim that the recommended
    phase order is currently enforced by the Harness.
    """
    phases = [
        item for item in plan
        if str(item.get("phase") or "") != "platform_gap_loop"
    ]
    phase_ids = [str(item.get("phase") or "").strip() for item in phases]
    if any(not phase_id for phase_id in phase_ids):
        raise ValueError("every observed plan phase requires a non-empty id")
    if len(set(phase_ids)) != len(phase_ids):
        raise ValueError("observed plan phase ids must be unique")

    nodes = [
        {
            "node_id": phase_id,
            "kind": _KIND_BY_PHASE.get(phase_id, "research"),
            "purpose": str(item.get("purpose") or ""),
            "enforcement": "advisory",
            "required_capabilities": (
                [_CAPABILITY_BY_PHASE[phase_id]]
                if phase_id in _CAPABILITY_BY_PHASE else []
            ),
            "entry_evidence": [],
            "exit_evidence": [],
        }
        for phase_id, item in zip(phase_ids, phases, strict=True)
    ]
    nodes.extend([
        {
            "node_id": "research_ready",
            "kind": "research",
            "purpose": "The local Harness permits research commands.",
            "enforcement": "deterministic",
            "required_capabilities": [],
            "entry_evidence": [],
            "exit_evidence": [],
        },
        {
            "node_id": "code_improvement_required",
            "kind": "capability_gap",
            "purpose": "An observed CLI or backend gap blocks further research.",
            "enforcement": "deterministic",
            "required_capabilities": [],
            "entry_evidence": ["open platform gap"],
            "exit_evidence": ["all platform gaps resolved"],
        },
        {
            "node_id": "factor_improvement_required",
            "kind": "research",
            "purpose": "A recorded poor result requires factor-source revision.",
            "enforcement": "deterministic",
            "required_capabilities": ["factor-workspace.source.modify"],
            "entry_evidence": ["explicit poor-result decision"],
            "exit_evidence": ["factor source changed and diagnostics rerun"],
        },
    ])

    edges = [
        {
            "edge_id": f"{left}__{right}",
            "from_node": left,
            "to_node": right,
            "edge_type": "recommended",
            "guard": {},
            "required_evidence": [],
            "counterexamples": [],
            "risk_level": "L1",
        }
        for left, right in zip(phase_ids, phase_ids[1:])
    ]
    edges.extend([
        {
            "edge_id": "research_ready__code_improvement_required",
            "from_node": "research_ready",
            "to_node": "code_improvement_required",
            "edge_type": "failure",
            "guard": {"platform_gap_detected": True},
            "required_evidence": ["failed command and stderr/stdout"],
            "counterexamples": ["research conclusion without platform failure"],
            "risk_level": "L2",
        },
        {
            "edge_id": "code_improvement_required__research_ready",
            "from_node": "code_improvement_required",
            "to_node": "research_ready",
            "edge_type": "recovery",
            "guard": {"open_platform_gaps": 0},
            "required_evidence": ["gap resolution note"],
            "counterexamples": ["another platform gap remains open"],
            "risk_level": "L2",
        },
        {
            "edge_id": "audit_results__factor_improvement_required",
            "from_node": "audit_results",
            "to_node": "factor_improvement_required",
            "edge_type": "conditional",
            "guard": {"poor_result_decision_recorded": True},
            "required_evidence": ["poor-result reason"],
            "counterexamples": ["result failure caused by a platform gap"],
            "risk_level": "L2",
        },
        {
            "edge_id": "factor_improvement_required__inspect_factor_expr_dsl",
            "from_node": "factor_improvement_required",
            "to_node": "inspect_factor_expr_dsl",
            "edge_type": "recovery",
            "guard": {"factor_source_changed": True},
            "required_evidence": ["factor workspace diff"],
            "counterexamples": ["no source or parameter change"],
            "risk_level": "L2",
        },
    ])
    return validate_graph({
        "schema_version": 1,
        "graph_id": "factor-research",
        "version": 1,
        "lifecycle": "observed",
        "parent_version": 0,
        "research_semantics": "product_neutral",
        "entry_node": phase_ids[0] if phase_ids else "research_ready",
        "nodes": nodes,
        "edges": edges,
        "provenance": {
            "source": "cli-anything-factortester-research",
            "description": (
                "Projection of the current fixed plan and persisted local "
                "ResearchSession transitions."
            ),
        },
    })
