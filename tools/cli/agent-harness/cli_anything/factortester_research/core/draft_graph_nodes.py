"""Node declarations for the product-neutral Draft Graph."""

from __future__ import annotations

from typing import Any

from .draft_graph_cycle import (
    node_conditional_operations,
    node_required_operations,
)


def build_draft_nodes() -> list[dict[str, Any]]:
    """Return audited nodes and their node-local capability requirements."""
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
            "job_evidence_ready",
            "validation",
            "Retain a trusted terminal JobAttempt evidence envelope before "
            "resolving any downstream analytical capability.",
            [],
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
    required_operations = node_required_operations()
    conditional_operations = node_conditional_operations()
    nodes = [
        {
            "node_id": node_id,
            "kind": kind,
            "purpose": purpose,
            "enforcement": "audited",
            "required_capabilities": [
                *capabilities,
                *required_operations.get(node_id, []),
            ],
            "conditional_capabilities": [
                *conditional_by_node.get(node_id, []),
                *conditional_operations.get(node_id, []),
            ],
            "entry_evidence": entry_evidence_by_node.get(node_id, []),
            "exit_evidence": exit_evidence_by_node.get(node_id, []),
        }
        for node_id, kind, purpose, capabilities in node_specs
    ]
    return nodes
