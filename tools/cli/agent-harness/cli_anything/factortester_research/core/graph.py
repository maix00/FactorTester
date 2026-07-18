"""Observed research-graph projection for the existing Harness workflow."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from typing import Any


_KIND_BY_PHASE = {
    "inspect_factor_expr_dsl": "validation",
    "prepare_factor_workspace": "research",
    "understand_factor_source": "research",
    "build_validation_slices": "validation",
    "create_research_workspace": "execution",
    "freeze_configuration": "execution",
    "submit_run": "execution",
    "observe_jobs": "execution",
    "control_jobs": "execution",
    "audit_results": "audit",
}

_CAPABILITY_BY_PHASE = {
    "inspect_factor_expr_dsl": "factor-expr.operator-registry.inspect",
    "prepare_factor_workspace": "factor-workspace.prepare",
    "understand_factor_source": "factor-workspace.source.inspect",
    "build_validation_slices": "research-validation.slice-plan",
    "create_research_workspace": "research-workspace.create",
    "freeze_configuration": "research-configuration.freeze",
    "submit_run": "research-run.submit",
    "observe_jobs": "research-job.observe",
    "control_jobs": "research-job.control",
    "audit_results": "research-result.audit",
}

_LIFECYCLES = {"observed", "draft", "active", "retired"}
_ENFORCEMENTS = {"advisory", "deterministic", "audited"}
_EDGE_TYPES = {"recommended", "conditional", "failure", "recovery"}
_RISK_LEVELS = {"L1", "L2", "L3", "L4"}


def graph_content_hash(graph: dict[str, Any]) -> str:
    """Return the stable SHA-256 identity of a graph without self-reference."""
    payload = deepcopy(graph)
    payload.pop("content_hash", None)
    raw = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def validate_graph(graph: dict[str, Any]) -> dict[str, Any]:
    """Validate the public graph protocol and return an isolated copy."""
    if not isinstance(graph, dict):
        raise ValueError("graph must be an object")
    if int(graph.get("schema_version") or 0) != 1:
        raise ValueError("unsupported graph schema_version")
    if str(graph.get("lifecycle") or "") not in _LIFECYCLES:
        raise ValueError("invalid graph lifecycle")
    nodes = graph.get("nodes")
    edges = graph.get("edges")
    if not isinstance(nodes, list) or not all(isinstance(item, dict) for item in nodes):
        raise ValueError("graph nodes must be an array of objects")
    if not isinstance(edges, list) or not all(isinstance(item, dict) for item in edges):
        raise ValueError("graph edges must be an array of objects")

    node_ids = [str(item.get("node_id") or "").strip() for item in nodes]
    if any(not node_id for node_id in node_ids):
        raise ValueError("every graph node requires node_id")
    if len(set(node_ids)) != len(node_ids):
        raise ValueError("graph node ids must be unique")
    for node in nodes:
        if str(node.get("enforcement") or "") not in _ENFORCEMENTS:
            raise ValueError(f"invalid node enforcement: {node.get('node_id')}")
        capabilities = node.get("required_capabilities")
        if not isinstance(capabilities, list) or not all(
            isinstance(item, str) and item.strip() for item in capabilities
        ):
            raise ValueError(
                f"required_capabilities must contain capability ids: "
                f"{node.get('node_id')}"
            )
        conditional = node.get("conditional_capabilities", [])
        if not isinstance(conditional, list) or not all(
            isinstance(item, dict)
            and isinstance(item.get("capability_id"), str)
            and bool(item["capability_id"].strip())
            and isinstance(item.get("predicate"), dict)
            and isinstance(item.get("explanation"), str)
            and bool(item["explanation"].strip())
            for item in conditional
        ):
            raise ValueError(
                "conditional_capabilities require id, predicate, explanation: "
                f"{node.get('node_id')}"
            )

    edge_ids = [str(item.get("edge_id") or "").strip() for item in edges]
    if any(not edge_id for edge_id in edge_ids):
        raise ValueError("every graph edge requires edge_id")
    if len(set(edge_ids)) != len(edge_ids):
        raise ValueError("graph edge ids must be unique")
    declared_nodes = set(node_ids)
    for edge in edges:
        edge_id = str(edge["edge_id"])
        for endpoint in ("from_node", "to_node"):
            value = str(edge.get(endpoint) or "").strip()
            if endpoint == "from_node" and value == "*":
                continue
            if value not in declared_nodes:
                raise ValueError(
                    f"edge {edge_id} references unknown node {value!r}"
                )
        if str(edge.get("edge_type") or "") not in _EDGE_TYPES:
            raise ValueError(f"invalid edge_type: {edge_id}")
        if str(edge.get("risk_level") or "") not in _RISK_LEVELS:
            raise ValueError(f"invalid risk_level: {edge_id}")
    descriptors = graph.get("capability_descriptors")
    if str(graph.get("lifecycle") or "") in {"draft", "active"}:
        if not isinstance(descriptors, dict):
            raise ValueError(
                "draft/active graph requires capability_descriptors"
            )
        used_capabilities = {
            str(capability_id)
            for node in nodes
            for capability_id in node.get("required_capabilities") or []
        } | {
            str(item["capability_id"])
            for node in nodes
            for item in node.get("conditional_capabilities") or []
        } | {
            str(capability_id)
            for edge in edges
            for capability_id in edge.get("required_capabilities") or []
        }
        missing_descriptors = sorted(
            used_capabilities - set(descriptors)
        )
        if missing_descriptors:
            raise ValueError(
                "capability descriptors missing: "
                + ", ".join(missing_descriptors)
            )
        for capability_id, descriptor in descriptors.items():
            if not isinstance(descriptor, dict):
                raise ValueError(
                    f"invalid capability descriptor: {capability_id}"
                )
            description = descriptor.get("capability_description")
            descriptor_hash = descriptor.get("descriptor_hash")
            if not isinstance(description, str) or not description.strip():
                raise ValueError(
                    f"capability description is required: {capability_id}"
                )
            if not isinstance(descriptor_hash, str) or (
                len(descriptor_hash) != 64
                or any(
                    character not in "0123456789abcdef"
                    for character in descriptor_hash
                )
            ):
                raise ValueError(
                    f"invalid capability descriptor hash: {capability_id}"
                )
    return deepcopy(graph)


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


def build_draft_graph() -> dict[str, Any]:
    """Build the product-neutral candidate for the first Active Graph.

    Product-specific accounting and data constraints are supplied by capability
    bindings and product profiles; they do not alter the core research method.
    """
    node_specs = [
        (
            "hypothesis_preregistration",
            "research",
            "Freeze the economic hypothesis, selection boundary, trial family, "
            "and rejection criteria.",
            ["research-hypothesis.preregister"],
        ),
        (
            "capability_resolution",
            "capability",
            "Resolve semantic requirements to approved implementations for the "
            "selected product group.",
            [],
        ),
        (
            "data_contract",
            "validation",
            "Establish point-in-time data provenance and causal availability.",
            ["data-provenance.point-in-time"],
        ),
        (
            "factor_semantics",
            "validation",
            "Reconcile the financial mechanism with factor source or AST, "
            "expression operators, numerical invariants, and signal timing.",
            [
                "factor-expr.operator-registry.inspect",
                "factor-workspace.source.inspect",
                "factor-timing.causal-align",
            ],
        ),
        (
            "validation_design",
            "validation",
            "Freeze selection, holdout, slice, and multiple-testing design.",
            [
                "research-validation.slice-plan",
                "multiple-testing.trial-ledger",
            ],
        ),
        (
            "cheap_factor_diagnostics",
            "analysis",
            "Run inexpensive cross-sectional diagnostics before portfolio "
            "simulation.",
            [
                "factor-validation.cross-sectional-ic",
                "factor-validation.quantile-monotonicity",
            ],
        ),
        (
            "statistical_robustness",
            "analysis",
            "Quantify uncertainty, selection bias, and degradation using only "
            "methods whose preconditions are satisfied.",
            [
                "performance.bootstrap-sharpe",
            ],
        ),
        (
            "authoritative_backtest",
            "execution",
            "Execute the surviving specification with product-appropriate "
            "accounting and immutable run provenance.",
            [
                "research-workspace.create",
                "research-configuration.freeze",
                "research-run.submit",
                "research-job.observe",
                "research-job.control",
                "market-accounting.replay",
            ],
        ),
        (
            "result_audit",
            "audit",
            "Audit causal, statistical, operational, and accounting evidence.",
            ["research-result.audit"],
        ),
        (
            "research_decision",
            "decision",
            "Record reject, revise, retain-for-more-evidence, or validated "
            "research status without self-certification by the executor, and "
            "write a provisional local memory of the mechanism, failure cause, "
            "and next-cycle constraint.",
            [],
        ),
        (
            "capability_gap",
            "capability_gap",
            "Classify a missing or unsuitable capability without turning it "
            "into a factor conclusion.",
            ["capability-gap.classify"],
        ),
        (
            "skill_candidate_review",
            "audit",
            "Discover or design a quarantined skill candidate and subject it to "
            "grill audit before any installation or execution.",
            [
                "capability-skill.discover",
                "capability-skill.create",
                "graph-change.grill-audit",
            ],
        ),
        (
            "code_improvement_required",
            "capability_gap",
            "Pause only affected branches while an approved platform change is "
            "implemented and verified.",
            [],
        ),
        (
            "factor_improvement_required",
            "research",
            "Revise the factor thesis, source, or parameters under a new trial "
            "record, then repeat semantic checks.",
            ["factor-workspace.source.modify"],
        ),
    ]
    conditional_by_node = {
        "hypothesis_preregistration": [
            {
                "capability_id": "factor-candidate.alpha-zoo.inspect",
                "predicate": {"any": [
                    {
                        "field": "hypothesis.origin",
                        "in": ["external_formula_library", "alpha_zoo"],
                    },
                    {
                        "field": "research.needs_prior_art_dedup",
                        "equals": True,
                    },
                ]},
                "explanation": (
                    "the hypothesis begins from an external formula library "
                    "or needs prior-art deduplication"
                ),
            },
            {
                "capability_id": "hypothesis.commodity-structure",
                "predicate": {
                    "field": "hypothesis.features",
                    "contains_any": [
                        "supply", "inventory", "term_structure", "carry",
                        "seasonality",
                    ],
                },
                "explanation": (
                    "the economic thesis depends on commodity supply, "
                    "inventory, curve, carry, or seasonality"
                ),
            },
            {
                "capability_id": "time-series.relationship-diagnostics",
                "predicate": {
                    "field": "hypothesis.features",
                    "contains_any": [
                        "level", "spread", "stationarity", "cointegration",
                        "predictive_lag",
                    ],
                },
                "explanation": (
                    "the thesis uses levels, spreads, stationarity, "
                    "cointegration, or predictive lag relations"
                ),
            },
        ],
        "data_contract": [{
            "capability_id": "data-source.route",
            "predicate": {
                "field": "data.requires_external_source",
                "equals": True,
            },
            "explanation": (
                "required research data is absent from the authoritative "
                "local contract or needs an external source"
            ),
        }],
        "factor_semantics": [
            {
                "capability_id": "market-microstructure.intraday-diagnose",
                "predicate": {"any": [
                    {
                        "field": "signal.frequency",
                        "in": ["MIN1", "MIN5", "MIN15", "MIN30", "HOUR1"],
                    },
                    {
                        "field": "hypothesis.features",
                        "contains_any": [
                            "spread", "depth", "order_flow", "intraday_volume",
                        ],
                    },
                ]},
                "explanation": (
                    "signal frequency is intraday or the thesis depends on "
                    "spread, depth, volume, sessions, or order flow"
                ),
            },
            {
                "capability_id": "factor-combination.multi-factor",
                "predicate": {
                    "field": "factor.is_multi",
                    "equals": True,
                },
                "explanation": "two or more factors are normalized or combined",
            },
        ],
        "validation_design": [{
            "capability_id": "multiple-testing.false-discovery-control",
            "predicate": {
                "field": "research.trial_count",
                "greater_than": 1,
            },
            "explanation": (
                "more than one factor, transform, horizon, universe, slice, "
                "parameter, or adaptive choice participates in selection"
            ),
        }],
        "statistical_robustness": [
            {
                "capability_id": "performance.deflated-sharpe",
                "predicate": {
                    "field": "research.trial_count",
                    "greater_than": 1,
                },
                "explanation": (
                    "a result was selected from more than one recorded trial"
                ),
            },
            {
                "capability_id": "performance.backtest-overfit-probability",
                "predicate": {
                    "all": [
                        {
                            "field": "research.trial_count",
                            "greater_than": 1,
                        },
                        {
                            "field": (
                                "selection.complete_candidate_return_matrix"
                            ),
                            "equals": True,
                        },
                    ],
                },
                "explanation": (
                    "a material candidate family has complete return paths "
                    "over common partitions suitable for CSCV"
                ),
            },
        ],
        "authoritative_backtest": [{
            "capability_id": "execution-cost.capacity-model",
            "predicate": {"any": [
                {
                    "field": "execution.material_cost_model",
                    "equals": True,
                },
                {
                    "field": "signal.frequency",
                    "in": ["MIN1", "MIN5", "MIN15", "MIN30", "HOUR1"],
                },
            ]},
            "explanation": (
                "turnover, participation, intraday execution, or market "
                "impact is material to the result"
            ),
        }],
        "result_audit": [
            {
                "capability_id": "performance.attribution",
                "predicate": {
                    "field": "audit.needs_attribution",
                    "equals": True,
                },
                "explanation": (
                    "net performance is viable or hidden beta, concentration, "
                    "carry, rollover, or regime dependence is suspected"
                ),
            },
            {
                "capability_id": "risk.stress-and-tail",
                "predicate": {
                    "field": "research.stage",
                    "in": ["capital_allocation", "production_readiness"],
                },
                "explanation": (
                    "a strategy reaches capital-allocation or production "
                    "readiness review"
                ),
            },
        ],
    }
    entry_evidence_by_node = {
        "hypothesis_preregistration": [
            "relevant provisional local memory references when prior "
            "experiments exist",
        ],
    }
    exit_evidence_by_node = {
        "factor_semantics": [
            "hypothesis hash and factor source or AST hash",
            "financial mechanism to implementation alignment",
            "numerical examples and semantic invariant checks",
        ],
        "research_decision": [
            "provisional local memory reference containing hypothesis, code, "
            "data, RunSpec, trial ledger, result, failure cause, and decision",
        ],
    }
    nodes = [
        {
            "node_id": node_id,
            "kind": kind,
            "purpose": purpose,
            "enforcement": "audited",
            "required_capabilities": capabilities,
            "conditional_capabilities": conditional_by_node.get(node_id, []),
            "entry_evidence": entry_evidence_by_node.get(node_id, []),
            "exit_evidence": exit_evidence_by_node.get(node_id, []),
        }
        for node_id, kind, purpose, capabilities in node_specs
    ]

    def edge(
        edge_id: str,
        from_node: str,
        to_node: str,
        *,
        edge_type: str = "conditional",
        guard: dict[str, Any] | None = None,
        risk_level: str = "L1",
        required_evidence: list[str] | None = None,
        counterexamples: list[str] | None = None,
    ) -> dict[str, Any]:
        return {
            "edge_id": edge_id,
            "from_node": from_node,
            "to_node": to_node,
            "edge_type": edge_type,
            "guard": guard or {},
            "required_evidence": required_evidence or [],
            "counterexamples": counterexamples or [],
            "risk_level": risk_level,
        }

    edges = [
        edge(
            "any_node__capability_gap",
            "*",
            "capability_gap",
            edge_type="failure",
            guard={"mandatory_binding_missing": True},
            risk_level="L2",
            required_evidence=[
                "target node and missing capability ids",
            ],
        ),
        edge(
            "hypothesis__capability_resolution",
            "hypothesis_preregistration",
            "capability_resolution",
            edge_type="recommended",
            guard={"hypothesis_frozen": True},
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
            required_evidence=["missing capability ids and attempted bindings"],
        ),
        edge(
            "data_contract__factor_semantics",
            "data_contract",
            "factor_semantics",
            guard={"point_in_time_contract_valid": True},
        ),
        edge(
            "factor_semantics__validation_design",
            "factor_semantics",
            "validation_design",
            guard={"causal_semantics_valid": True},
        ),
        edge(
            "validation_design__cheap_diagnostics",
            "validation_design",
            "cheap_factor_diagnostics",
            guard={"selection_and_trial_plan_frozen": True},
        ),
        edge(
            "cheap_diagnostics__backtest",
            "cheap_factor_diagnostics",
            "authoritative_backtest",
            guard={
                "diagnostics_viable": True,
                "selection_role": "in_sample",
            },
        ),
        edge(
            "cheap_diagnostics__factor_improvement",
            "cheap_factor_diagnostics",
            "factor_improvement_required",
            guard={
                "diagnostics_revise": True,
                "revision_reason_preregistered": True,
                "selection_holdout_not_reused": True,
                "trial_ledger_incremented": True,
                "remaining_revision_budget_positive": True,
            },
            risk_level="L2",
            counterexamples=["failure is caused by a platform or data gap"],
        ),
        edge(
            "cheap_diagnostics__result_audit",
            "cheap_factor_diagnostics",
            "result_audit",
            edge_type="failure",
            guard={"diagnostics_reject": True},
            risk_level="L2",
            required_evidence=[
                "frozen diagnostic specification and rejection evidence",
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
            guard={"uncertainty_review_passed": True},
            risk_level="L2",
        ),
        edge(
            "statistical_robustness__result_audit_reject",
            "statistical_robustness",
            "result_audit",
            edge_type="failure",
            guard={"robustness_reject": True},
            risk_level="L2",
            required_evidence=[
                "predeclared uncertainty method and rejection evidence",
            ],
        ),
        edge(
            "statistical_robustness__factor_improvement",
            "statistical_robustness",
            "factor_improvement_required",
            edge_type="recovery",
            guard={
                "robustness_revise": True,
                "new_falsifiable_hypothesis_proposed": True,
                "selection_holdout_not_reused": True,
                "remaining_revision_budget_positive": True,
            },
            risk_level="L2",
            required_evidence=[
                "new falsifiable mechanism and remaining revision budget",
            ],
        ),
        edge(
            "result_audit__research_decision",
            "result_audit",
            "research_decision",
            guard={"audit_complete": True, "unresolved_material_gap": False},
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
            required_evidence=[
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
            required_evidence=["grill audit and implementation validation"],
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
    graph = {
        "schema_version": 1,
        "graph_id": "factor-research",
        "version": 3,
        "lifecycle": "draft",
        "parent_version": 2,
        "research_semantics": "product_neutral",
        "entry_node": "hypothesis_preregistration",
        "nodes": nodes,
        "edges": edges,
        "provenance": {
            "source": "observed-harness-plus-reviewed-industry-semantics",
            "description": (
                "First candidate graph. Product support is resolved through "
                "capability bindings and does not define the graph topology."
            ),
        },
    }
    from .capabilities import (
        capability_descriptor,
        load_builtin_capability_registry,
    )
    registry = load_builtin_capability_registry()
    contracts = {
        str(item["capability_id"]): item
        for item in registry["capabilities"]
    }
    capability_ids = {
        str(capability_id)
        for node in nodes
        for capability_id in node.get("required_capabilities") or []
    } | {
        str(item["capability_id"])
        for node in nodes
        for item in node.get("conditional_capabilities") or []
    } | {
        str(capability_id)
        for item in edges
        for capability_id in item.get("required_capabilities") or []
    }
    graph["capability_descriptors"] = {
        capability_id: capability_descriptor(contracts[capability_id])
        for capability_id in sorted(capability_ids)
    }
    graph = validate_graph(graph)
    graph["content_hash"] = graph_content_hash(graph)
    return graph
