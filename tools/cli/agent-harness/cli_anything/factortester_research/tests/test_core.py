from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
from cli_anything.factortester_research.core.backend_evidence import (
    extract_job_attempt,
)
from cli_anything.factortester_research.core.capabilities import (
    evaluate_capability_predicate,
    load_builtin_capability_registry,
    resolve_graph_capabilities,
)
from cli_anything.factortester_research.core.capability_sources import (
    source_manifest_sha256,
)
from cli_anything.factortester_research.core.cycle import (
    validate_next_packet,
    validate_transition_evidence,
)
from cli_anything.factortester_research.core.evidence import (
    persist_command_evidence,
    validate_evidence_envelope,
)
from cli_anything.factortester_research.core.external_factor import (
    validate_dataset_manifest,
    validate_factor_manifest,
    validate_handoff_manifest,
    vibe_pipeline_plan,
)
from cli_anything.factortester_research.core.graph import (
    build_draft_graph,
    build_observed_graph,
    graph_content_hash,
    validate_graph,
)
from cli_anything.factortester_research.core.plan import (
    build_factor_research_plan,
    validation_checklist,
)
from cli_anything.factortester_research.core.replay import replay_graph_trace
from cli_anything.factortester_research.core.server_guards import (
    derive_server_guard_facts,
)
from cli_anything.factortester_research.core.service import (
    ManagedWorktree,
    select_worktree,
)
from cli_anything.factortester_research.core.session import (
    ResearchSession,
    record_gap,
    record_skill_usage,
    resolve_gap,
)
from cli_anything.factortester_research.core.slices import (
    default_factor_validation_plan,
)

HARNESS_ROOT = Path(__file__).resolve().parents[3]
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _schema_v2_graph() -> dict:
    graph = build_draft_graph()
    graph.pop("content_hash", None)
    graph["schema_version"] = 2
    capability_id = sorted(graph["capability_descriptors"])[0]
    report_requirements = []
    for node in graph["nodes"]:
        node_id = node["node_id"]
        entry_id = f"report.node.{node_id}.entry"
        action_id = f"report.node.{node_id}.action"
        report_requirements.extend([
            {
                "report_requirement_id": entry_id,
                "anchor_kind": "node_entry",
                "anchor_ref": node_id,
                "method_ref": "inventory",
                "title_zh": f"进入 {node_id}",
                "subject_selector": {"kind": "current_branch"},
                "requirement_ref": "hypothesis_validity.mechanism_chain",
            },
            {
                "report_requirement_id": action_id,
                "anchor_kind": "node_action",
                "anchor_ref": node_id,
                "method_ref": "explain",
                "title_zh": f"处理 {node_id}",
                "subject_selector": {"kind": "current_branch"},
                "requirement_ref": "hypothesis_validity.mechanism_chain",
            },
        ])
        node["entry_requirement_refs"] = [
            "hypothesis_validity.mechanism_chain"
        ]
        node["entry_report_refs"] = [entry_id]
        node["node_report_refs"] = [action_id]
    for edge in graph["edges"]:
        edge_id = edge["edge_id"]
        report_id = f"report.edge.{edge_id}"
        edge["report_requirement_refs"] = [report_id]
        edge["obligation_requirement_refs"] = [
            "hypothesis_validity.mechanism_chain"
        ]
        report_requirements.append({
            "report_requirement_id": report_id,
            "anchor_kind": "edge",
            "anchor_ref": edge_id,
            "method_ref": "explain_transition",
            "title_zh": f"经过 {edge_id}",
            "subject_selector": {"kind": "transition"},
            "requirement_ref": "hypothesis_validity.mechanism_chain",
        })
    gate_report_id = "report.gate.evidence_admission"
    report_requirements.append({
        "report_requirement_id": gate_report_id,
        "anchor_kind": "system_gate",
        "anchor_ref": "evidence_admission",
        "method_ref": "inventory",
        "title_zh": "证据准入",
        "subject_selector": {"kind": "evidence_envelope"},
        "coordination_ref": "evidence_qualification",
    })
    all_requirement_reports = [
        item["report_requirement_id"]
        for item in report_requirements
        if item.get("requirement_ref")
    ]
    graph.update({
        "change_manifest": {
            "parent_version": graph["parent_version"],
            "summary_zh": "验证后继图定义协议",
            "changes": [{
                "change_id": "change.contracts",
                "change_kind": "schema",
                "subject_ref": "graph:factor-research",
                "impact_zh": "增加义务与报告合同",
            }],
        },
        "requirement_catalog": {
            "catalog_revision": 1,
            "categories": [{
                "category_id": "hypothesis_validity",
                "title_zh": "假设有效性",
                "description_zh": "判断机制、代理和预测是否可证伪。",
            }],
            "requirements": [{
                "requirement_id": "hypothesis_validity.mechanism_chain",
                "category_id": "hypothesis_validity",
                "revision": 1,
                "gate_policy": "plan_before_exit",
                "title_zh": "机制链",
                "question_zh": "机制如何从事实传导至价格？",
                "select_when_zh": "冻结研究假设前。",
                "evidence_expected_zh": ["可追溯事实"],
                "not_sufficient_zh": ["仅有回测表现"],
                "industry_principle_zh": "机制与可证伪预测应分开陈述。",
                "industry_basis_refs": ["S-FIRST-PRINCIPLES"],
                "resolver_capability_ids": [capability_id],
                "cli_invocation_templates": [
                    "factortester research requirements resolve --json"
                ],
                "resolver_output_schema": {"type": "object"},
                "fallback_route": "capability_gap",
                "report_requirement_refs": all_requirement_reports,
            }],
        },
        "report_method_descriptors": {
            "inventory": {
                "description_zh": "逐项列出事实和引用。",
                "allowed_content": ["list", "table"],
                "descriptor_hash": "a" * 64,
            },
            "explain": {
                "description_zh": "解释机制和限制。",
                "allowed_content": ["sentence", "list"],
                "descriptor_hash": "b" * 64,
            },
            "explain_transition": {
                "description_zh": "解释转移理由。",
                "allowed_content": ["sentence", "list", "table"],
                "descriptor_hash": "c" * 64,
            },
        },
        "report_requirements": report_requirements,
        "system_transition_policies": [{
            "policy_id": "policy.evidence_admission",
            "policy_kind": "evidence_admission",
            "report_requirement_refs": [gate_report_id],
        }],
    })
    return graph


def _research_cycle_discovery_proposal() -> dict:
    return {
        "schema_version": 1,
        "proposal_id": "proposal-discovery",
        "proposer_invocation_id": "agent-invocation-proposal-discovery",
        "contract_hash": "1" * 64,
        "trial_plan_hash": "2" * 64,
        "methodology_hash": "3" * 64,
        "evidence_refs": ["trace:first-principles-review"],
        "claim_evidence_delta": [],
        "claim_delta_noop_reason": "question is not empirical support",
        "obligation_delta": [{
            "obligation_id": "obligation-roll",
            "from_state": "absent",
            "to_state": "open",
            "criterion_ref": "methodology:roll-window",
            "obligation": {
                "schema_version": 1,
                "obligation_id": "obligation-roll",
                "contract_hash": "1" * 64,
                "claim_ids": ["claim-1"],
                "obligation_kind": "roll_window_artifact",
                "title_zh": "换月窗口伪影",
                "epistemic_question": "Does roll proximity explain it?",
                "scope": {"product_group": "china_futures"},
                "discharge_criterion": {"method": "window exclusion"},
                "status": "open",
                "materiality": "decision_blocking",
                "methodology_hash": "3" * 64,
                "created_event_ref": "trace:first-principles-review",
            },
        }],
        "decision_warrant": {
            "finding_refs": ["trace:first-principles-review"],
            "rule_refs": ["methodology:obligation-discovery"],
            "inference_type": "semantic",
            "preregistered": False,
            "alternative_refs": [],
            "limitation_refs": [],
            "reentry_predicates": [],
            "required_authority": "independent_reviewer",
        },
    }


def test_observed_graph_distinguishes_advisory_plan_from_enforced_gap_state() -> None:
    plan = build_factor_research_plan(
        factor_families=["SgCCS"],
        products=["A.DCE"],
        sources=["Local"],
        configuration_file="configuration.json",
    )
    graph = build_observed_graph(plan)

    assert graph["lifecycle"] == "observed"
    nodes = {item["node_id"]: item for item in graph["nodes"]}
    assert nodes["inspect_factor_expr_dsl"]["enforcement"] == "advisory"
    assert nodes["code_improvement_required"]["enforcement"] == "deterministic"
    assert {
        (item["from_node"], item["to_node"], item["edge_type"])
        for item in graph["edges"]
    } >= {
        ("inspect_factor_expr_dsl", "prepare_factor_workspace", "recommended"),
        ("research_ready", "code_improvement_required", "failure"),
        ("code_improvement_required", "research_ready", "recovery"),
    }


def test_observed_graph_content_hash_is_stable() -> None:
    plan = build_factor_research_plan(
        factor_families=["SgCCS"],
        products=["A.DCE"],
        sources=["Local"],
        configuration_file="configuration.json",
    )
    first = build_observed_graph(plan)
    second = build_observed_graph(plan)

    assert graph_content_hash(first) == graph_content_hash(second)
    assert len(graph_content_hash(first)) == 64


def test_graph_validation_rejects_a_dangling_edge() -> None:
    graph = build_observed_graph(build_factor_research_plan(
        factor_families=["SgCCS"],
        products=["A.DCE"],
        sources=["Local"],
        configuration_file="configuration.json",
    ))
    graph["edges"][0]["to_node"] = "missing-node"

    with pytest.raises(ValueError, match="unknown node"):
        validate_graph(graph)


def test_graph_validation_rejects_an_unknown_server_action() -> None:
    graph = build_draft_graph()
    graph["edges"][0]["server_action"] = "client_defined_mutation"

    with pytest.raises(ValueError, match="invalid server_action"):
        validate_graph(graph)


def test_schema_v2_graph_validates_catalog_reports_and_system_gates() -> None:
    graph = _schema_v2_graph()

    validated = validate_graph(graph)

    assert validated["schema_version"] == 2
    assert validated["system_transition_policies"][0]["policy_kind"] == (
        "evidence_admission"
    )


def test_schema_v2_graph_rejects_an_unknown_report_reference() -> None:
    graph = _schema_v2_graph()
    graph["nodes"][0]["entry_report_refs"] = ["report.missing"]

    with pytest.raises(ValueError, match="references unknown ids"):
        validate_graph(graph)


def test_schema_v2_graph_rejects_a_requirement_without_resolver() -> None:
    graph = _schema_v2_graph()
    requirement = graph["requirement_catalog"]["requirements"][0]
    requirement["resolver_capability_ids"] = []

    with pytest.raises(ValueError, match="resolver capability is required"):
        validate_graph(graph)


def test_schema_v2_graph_requires_a_real_or_coordination_report_binding() -> None:
    graph = _schema_v2_graph()
    gate_report = graph["report_requirements"][-1]
    gate_report.pop("coordination_ref")

    with pytest.raises(ValueError, match="exactly one semantic binding"):
        validate_graph(graph)


def test_capability_resolution_reports_available_bindings_and_gaps() -> None:
    graph = build_observed_graph(build_factor_research_plan(
        factor_families=["SgCCS"],
        products=["A.DCE"],
        sources=["Local"],
        configuration_file="configuration.json",
    ))
    registry = {
        "schema_version": 1,
        "catalog_id": "factor-research-capabilities",
        "capabilities": [{
            "capability_id": "factor-expr.operator-registry.inspect",
            "industry_semantics": (
                "Verify operator availability and causal semantics before "
                "factor evaluation."
            ),
            "when_to_use": ["before evaluating a factor expression"],
            "preconditions": [],
            "prohibitions": [],
            "implementations": [{
                "implementation_id": "factortester.custom-factors.operators",
                "provider": "factortester",
                "kind": "cli",
                "approval_status": "approved",
                "execution_mode": "real_backend",
                "product_scopes": ["china_futures"],
            }],
        }],
    }

    result = resolve_graph_capabilities(
        graph,
        registry,
        product_group="china_futures",
        include_all=True,
    )

    assert result["bindings"][0]["capability_id"] == (
        "factor-expr.operator-registry.inspect"
    )
    assert result["bindings"][0]["implementation_id"] == (
        "factortester.custom-factors.operators"
    )
    assert "factor-workspace.prepare" in {
        item["capability_id"] for item in result["gaps"]
    }


def test_builtin_registry_distinguishes_backend_guidance_and_product_gaps() -> None:
    registry = load_builtin_capability_registry()
    capabilities = {
        item["capability_id"]: item for item in registry["capabilities"]
    }
    skill_implementations = [
        implementation
        for capability in registry["capabilities"]
        for implementation in capability.get("implementations") or []
        if implementation.get("kind") == "skill"
    ]
    assert skill_implementations
    assert all(
        implementation.get("requires_execution_approval") is True
        for implementation in skill_implementations
    )

    factor_ic = capabilities["factor-validation.cross-sectional-ic"]
    implementations = {
        item["implementation_id"]: item
        for item in factor_ic["implementations"]
    }
    assert implementations["factortester.analysis.ic"]["execution_mode"] == (
        "real_backend"
    )
    assert implementations["vibe.factor-research"]["execution_mode"] == (
        "guidance_only"
    )
    assert implementations["vibe.factor-research"]["approval_status"] == (
        "quarantined"
    )

    futures_accounting = capabilities["market-accounting.replay"]
    assert futures_accounting["prohibitions"]
    assert any(
        item["implementation_id"] == "vibe.china-futures-engine"
        and item["approval_status"] == "quarantined"
        for item in futures_accounting["implementations"]
    )

    assert "data-provenance.point-in-time" not in capabilities
    assert "factor-timing.causal-align" in capabilities


def test_draft_graph_exposes_adaptive_research_and_capability_gap_branches() -> None:
    graph = build_draft_graph()
    edges = {item["edge_id"]: item for item in graph["edges"]}
    assert graph["version"] == 8
    assert graph["parent_version"] == 7
    nodes = {item["node_id"]: item for item in graph["nodes"]}

    assert graph["lifecycle"] == "draft"
    assert graph["version"] == 8
    assert graph["parent_version"] == 7
    assert {
        item["capability_id"]
        for item in graph["research_cycle_operations"]
    } == {
        "research-obligation.discover",
        "research-trial.synthesize",
        "research-evidence.adjudicate",
        "research-exhaustion.assess",
    }
    assert graph["maintenance_operations"] == [{
        "capability_id": "research-methodology.impact",
        "trigger_predicate": {
            "field": "maintenance.semantic_change_proposed",
            "equals": True,
        },
        "output_kind": "MethodologyChangeProposal",
        "authority": "maintenance_case_and_human_audit",
    }]
    operation_ids = {
        item["capability_id"]
        for item in [
            *graph["research_cycle_operations"],
            *graph["maintenance_operations"],
        ]
    }
    assert not any(
        edge["edge_id"] in operation_ids
        or edge["from_node"] in operation_ids
        or edge["to_node"] in operation_ids
        for edge in graph["edges"]
    )
    assert "research-obligation.discover" in nodes[
        "hypothesis_preregistration"
    ]["required_capabilities"]
    assert "research-trial.synthesize" in nodes[
        "validation_design"
    ]["required_capabilities"]
    assert "research-evidence.adjudicate" in nodes[
        "result_audit"
    ]["required_capabilities"]
    decision_conditionals = {
        item["capability_id"]: item["predicate"]
        for item in nodes["research_decision"]["conditional_capabilities"]
    }
    assert decision_conditionals["research-exhaustion.assess"] == {
        "field": "research.closure_requested",
        "equals": True,
    }
    assert nodes["cheap_factor_diagnostics"]["required_capabilities"] == [
        "factor-validation.cross-sectional-ic",
        "factor-validation.quantile-monotonicity",
    ]
    assert edges["cheap_diagnostics__backtest"]["guard"] == {
        "preregistered_execution_eligibility_satisfied": True,
        "current_trial_stage_executable": True,
    }
    assert nodes["job_evidence_ready"]["required_capabilities"] == []
    assert edges["backtest__job_evidence_ready"]["guard"] == {
        "terminal_job_evidence_retained": True,
        "terminal_job_trusted": True,
        "net_return_series_available": True,
    }
    assert (
        edges["backtest__job_evidence_ready"]["server_action"]
        == "bind_job_attempt"
    )
    assert edges["job_evidence_ready__statistical_robustness"]["guard"] == {
        "mandatory_bindings_resolved": True,
    }
    assert edges["job_evidence_ready__capability_gap"]["guard"] == {
        "mandatory_binding_missing": True,
    }
    assert edges["capability_gap__job_evidence_ready"]["guard"] == {
        "approved_binding_now_available": True,
        "gap_origin_edge_id": "job_evidence_ready__capability_gap",
    }
    assert edges["capability_gap__blocked_closure"]["guard"] == {
        "bounded_closure_disposition": "blocked",
        "research_cycle_delta_applied": True,
    }
    assert "backtest__statistical_robustness" not in edges
    assert edges["statistical_robustness__result_audit"]["guard"] == {
        "uncertainty_evidence_complete": True,
    }
    assert "cheap_diagnostics__statistical_robustness" not in edges
    assert "statistical_robustness__backtest" not in edges
    assert "backtest__result_audit" not in edges
    assert edges["cheap_diagnostics__result_audit"]["guard"] == {
        "diagnostic_evidence_complete": True,
        "further_execution_eligible": False,
    }
    assert edges["cheap_diagnostics__result_audit"][
        "required_research_evidence"
    ] == ["frozen diagnostic specification and factual evidence"]
    assert edges["cheap_diagnostics__result_audit"][
        "required_transition_facts"
    ] == []
    assert "cheap_diagnostics__factor_improvement" not in edges
    assert "statistical_robustness__result_audit_reject" not in edges
    assert "statistical_robustness__factor_improvement" not in edges
    assert edges["result_audit__factor_improvement"]["guard"] == {
        "audit_complete": True,
        "no_unresolved_evidence_integrity_or_capability_gap": True,
        "adjudication_applied_or_explicit_noop": True,
        "adjudication_route_bound": True,
        "factor_revision_authorized": True,
        "next_trial_stage_required": False,
        "new_hypothesis_lineage_allowed": True,
        "new_falsifiable_hypothesis_proposed": True,
        "protected_sample_reuse_forbidden": True,
        "remaining_revision_budget_positive": True,
    }
    assert edges["result_audit__factor_improvement"][
        "required_research_evidence"
    ] == []
    assert edges["result_audit__factor_improvement"][
        "required_transition_facts"
    ] == [
        "accepted adjudication, new falsifiable mechanism, and remaining "
        "revision budget",
    ]
    assert edges["result_audit__validation_design"]["guard"] == {
        "audit_complete": True,
        "adjudication_applied_or_explicit_noop": True,
        "adjudication_route_bound": True,
        "next_trial_stage_required": True,
        "trial_stage_advance_authorized": True,
    }
    assert edges["result_audit__research_decision"]["guard"][
        "next_trial_stage_required"
    ] is False
    assert edges["result_audit__research_decision"]["guard"][
        "factor_revision_authorized"
    ] is False
    assert "unresolved_material_gap" not in edges[
        "result_audit__research_decision"
    ]["guard"]
    assert "result_audit__statistical_robustness" not in edges
    assert edges["factor_improvement__hypothesis"]["guard"] == {
        "new_hypothesis_version_recorded": True,
        "trial_ledger_incremented": True,
        "holdout_status_recorded": True,
        "factor_change_retained": True,
    }
    assert edges["factor_improvement__hypothesis"]["server_action"] == (
        "start_new_hypothesis_lineage"
    )
    assert edges["hypothesis__capability_resolution"]["guard"][
        "obligation_discovery_checkpoint_fresh"
    ] is True
    assert edges["data_contract__factor_semantics"]["guard"][
        "data_availability_profile_bound"
    ] is True
    assert "point_in_time_contract_valid" not in edges[
        "data_contract__factor_semantics"
    ]["guard"]
    assert edges["data_contract__factor_semantics"]["guard"][
        "requested_product_availability_present"
    ] is True
    assert edges["data_contract__factor_semantics"]["server_action"] == (
        "bind_data_availability"
    )
    assert edges["data_contract__factor_semantics"]["guard"][
        "material_data_obligations_adjudicated_or_not_triggered"
    ] is True
    assert edges["data_contract__capability_gap"]["guard"] == {
        "data_availability_profile_bound": True,
        "requested_product_availability_present": False,
    }
    assert edges["data_contract__capability_gap"]["server_action"] == (
        "bind_data_availability"
    )
    assert edges["capability_gap__data_contract"]["guard"] == {
        "data_availability_profile_bound": True,
        "requested_product_availability_present": True,
    }
    assert edges["capability_gap__data_contract"]["server_action"] == (
        "bind_data_availability"
    )
    assert nodes["data_contract"]["conditional_capabilities"] == []
    assert edges["factor_semantics__validation_design"]["guard"][
        "semantic_discovery_fresh_or_not_triggered"
    ] is True
    assert edges["factor_semantics__validation_design"]["guard"][
        "frozen_factor_formulas_bound"
    ] is True
    assert edges["factor_semantics__validation_design"]["guard"][
        "selected_factor_semantics_resolved"
    ] is True
    assert edges["factor_semantics__validation_design"]["server_action"] == (
        "bind_factor_semantics"
    )
    assert edges["factor_semantics__factor_improvement"] == {
        "edge_id": "factor_semantics__factor_improvement",
        "from_node": "factor_semantics",
        "to_node": "factor_improvement_required",
        "edge_type": "recovery",
        "guard": {
            "adjudication_route_bound": True,
            "factor_revision_authorized": True,
            "next_trial_stage_required": False,
        },
        "required_evidence": [
            "accepted factor-revision adjudication and material semantic "
            "obligation",
        ],
        "required_research_evidence": [],
        "required_transition_facts": [
            "accepted factor-revision adjudication and material semantic "
            "obligation",
        ],
        "counterexamples": [],
        "risk_level": "L2",
    }
    assert edges["validation_design__factor_improvement"] == {
        "edge_id": "validation_design__factor_improvement",
        "from_node": "validation_design",
        "to_node": "factor_improvement_required",
        "edge_type": "recovery",
        "guard": {
            "adjudication_route_bound": True,
            "factor_revision_authorized": True,
            "next_trial_stage_required": False,
        },
        "required_evidence": [
            "accepted factor-revision adjudication for a late semantic "
            "obligation",
        ],
        "required_research_evidence": [],
        "required_transition_facts": [
            "accepted factor-revision adjudication for a late semantic "
            "obligation",
        ],
        "counterexamples": [],
        "risk_level": "L2",
    }
    assert edges["validation_design__cheap_diagnostics"]["guard"][
        "actionable_obligations_planned_or_bounded"
    ] is True
    assert edges["result_audit__research_decision"]["guard"][
        "adjudication_applied_or_explicit_noop"
    ] is True
    assert edges["research_decision__cycle_event"]["from_node"] == (
        "research_decision"
    )
    assert edges["research_decision__cycle_event"]["to_node"] == (
        "research_decision"
    )
    assert edges["research_decision__cycle_event"]["guard"] == {
        "research_cycle_delta_applied": True,
    }
    assert edges["any_node__capability_gap"]["from_node"] == "*"
    assert nodes["capability_gap"]["required_capabilities"] == [
        "capability-gap.classify"
    ]
    conditional = {
        item["capability_id"]
        for item in nodes["factor_semantics"]["conditional_capabilities"]
    }
    assert conditional == {
        "market-microstructure.intraday-diagnose",
        "factor-combination.multi-factor",
        "research-obligation.discover",
    }
    semantic_discovery = next(
        item
        for item in nodes["factor_semantics"]["conditional_capabilities"]
        if item["capability_id"] == "research-obligation.discover"
    )
    assert semantic_discovery["predicate"] == {"any": [
        {
            "field": "research.semantic_discovery_stale",
            "equals": True,
        },
        {
            "field": "research.semantic_inspection_exposed_material_question",
            "equals": True,
        },
    ]}
    validation_required = set(
        nodes["validation_design"]["required_capabilities"]
    )
    validation_conditional = {
        item["capability_id"]: item["predicate"]
        for item in nodes["validation_design"]["conditional_capabilities"]
    }
    robustness_required = set(
        nodes["statistical_robustness"]["required_capabilities"]
    )
    robustness_conditional = {
        item["capability_id"]: item["predicate"]
        for item in nodes["statistical_robustness"]["conditional_capabilities"]
    }
    assert "multiple-testing.false-discovery-control" not in validation_required
    assert validation_conditional[
        "multiple-testing.false-discovery-control"
    ] == {"field": "research.trial_count", "greater_than": 1}
    assert robustness_required == {"performance.bootstrap-sharpe"}
    assert robustness_conditional["performance.deflated-sharpe"] == {
        "field": "research.trial_count",
        "greater_than": 1,
    }
    assert robustness_conditional[
        "performance.backtest-overfit-probability"
    ] == {
        "all": [
            {"field": "research.trial_count", "greater_than": 1},
            {
                "field": "selection.complete_candidate_return_matrix",
                "equals": True,
            },
        ],
    }
    assert "provisional local memory" in nodes["research_decision"]["purpose"]
    assert nodes["factor_semantics"]["exit_evidence"] == [
        "hypothesis hash and factor source or AST hash",
        "financial mechanism to implementation alignment",
        "numerical examples and semantic invariant checks",
    ]
    assert nodes["research_decision"]["exit_evidence"] == [
        "provisional local memory reference containing hypothesis, code, data, "
        "RunSpec, trial ledger, result, failure cause, and decision",
    ]


def test_graph_rejects_mismatched_typed_edge_requirements() -> None:
    graph = build_draft_graph()
    graph["edges"][0]["required_transition_facts"] = []
    graph["content_hash"] = graph_content_hash(graph)

    with pytest.raises(ValueError, match="typed edge requirements"):
        validate_graph(graph)


def test_numeric_capability_predicates_fail_closed() -> None:
    predicate = {"field": "research.trial_count", "greater_than": 1}

    assert evaluate_capability_predicate(
        predicate,
        {"research": {"trial_count": 2}},
    ) is True
    assert evaluate_capability_predicate(
        predicate,
        {"research": {"trial_count": 1}},
    ) is False
    assert evaluate_capability_predicate(predicate, {}) is None
    with pytest.raises(ValueError, match="numeric"):
        evaluate_capability_predicate(
            predicate,
            {"research": {"trial_count": "many"}},
        )


def test_trial_family_capabilities_are_triggered_only_when_applicable() -> None:
    graph = build_draft_graph()
    registry = load_builtin_capability_registry()
    single = resolve_graph_capabilities(
        graph,
        registry,
        product_group="china_futures",
        node_id="statistical_robustness",
        facts={
            "research": {"trial_count": 1},
            "selection": {"complete_candidate_return_matrix": False},
        },
    )
    family = resolve_graph_capabilities(
        graph,
        registry,
        product_group="china_futures",
        node_id="statistical_robustness",
        facts={
            "research": {"trial_count": 4},
            "selection": {"complete_candidate_return_matrix": True},
        },
    )

    assert single["triggered_conditional_gaps"] == []
    assert {
        item["capability_id"]
        for item in family["triggered_conditional_gaps"]
    } == {
        "performance.deflated-sharpe",
        "performance.backtest-overfit-probability",
    }


def test_skill_binding_does_not_self_authorize_execution() -> None:
    graph = build_draft_graph()
    graph["nodes"] = [{
        "node_id": "commodity_hypothesis",
        "kind": "research",
        "purpose": "generate a commodity hypothesis",
        "enforcement": "audited",
        "required_capabilities": ["hypothesis.commodity-structure"],
        "entry_evidence": [],
        "exit_evidence": [],
    }]
    graph["edges"] = []
    registry = load_builtin_capability_registry()

    resolved = resolve_graph_capabilities(
        graph,
        registry,
        product_group="china_futures",
        node_id="commodity_hypothesis",
    )
    granted = resolve_graph_capabilities(
        graph,
        registry,
        product_group="china_futures",
        approved_implementation_ids={"vibe.commodity-analysis"},
        node_id="commodity_hypothesis",
    )

    assert resolved["gaps"] == []
    assert resolved["bindings"][0]["implementation_id"] == (
        "vibe.commodity-analysis"
    )
    assert resolved["bindings"][0]["execution_approval_granted"] is False
    assert resolved["bindings"][0]["local_execution_approval_required"] is True
    assert resolved["bindings"][0]["execution_approval_source"] == "none"
    assert granted["bindings"][0]["implementation_id"] == (
        "vibe.commodity-analysis"
    )
    assert granted["bindings"][0]["execution_approval_source"] == (
        "explicit_grant"
    )


def test_microstructure_resolution_is_product_specific() -> None:
    graph = build_draft_graph()
    facts = {
        "signal": {"frequency": "MIN1"},
        "hypothesis": {"features": ["intraday_volume"]},
        "factor": {"is_multi": False},
    }

    futures = resolve_graph_capabilities(
        graph,
        load_builtin_capability_registry(),
        product_group="china_futures",
        node_id="factor_semantics",
        facts=facts,
    )
    equities = resolve_graph_capabilities(
        graph,
        load_builtin_capability_registry(),
        product_group="equities",
        node_id="factor_semantics",
        facts=facts,
    )

    futures_binding = futures["triggered_conditional_bindings"][0]
    equities_binding = equities["triggered_conditional_bindings"][0]
    assert futures_binding["implementation_id"] == (
        "factortester-harness.china-futures-microstructure"
    )
    assert equities_binding["implementation_id"] == (
        "vibe.market-microstructure"
    )


def test_validation_design_has_builtin_trial_ledger() -> None:
    resolution = resolve_graph_capabilities(
        build_draft_graph(),
        load_builtin_capability_registry(),
        product_group="china_futures",
        node_id="validation_design",
        facts={"research": {"trial_count": 1}},
    )

    assert resolution["gaps"] == []
    assert {
        item["capability_id"] for item in resolution["bindings"]
    } == {
        "multiple-testing.trial-ledger",
        "research-validation.slice-plan",
        "research-trial.synthesize",
    }


def test_validation_design_binds_reviewed_false_discovery_guidance() -> None:
    resolution = resolve_graph_capabilities(
        build_draft_graph(),
        load_builtin_capability_registry(),
        product_group="china_futures",
        node_id="validation_design",
        facts={"research": {"trial_count": 10}},
    )

    assert resolution["triggered_conditional_gaps"] == []
    binding = resolution["triggered_conditional_bindings"][0]
    assert binding["capability_id"] == (
        "multiple-testing.false-discovery-control"
    )
    assert binding["implementation_id"] == "local.quantitative-research"
    assert binding["execution_approval_granted"] is False
    assert binding["local_execution_approval_required"] is True
    assert len(binding["source_fingerprint"]) == 64


def test_capability_resolution_keeps_conditional_skills_out_of_mandatory_gaps() -> None:
    graph = build_draft_graph()
    not_triggered = resolve_graph_capabilities(
        graph,
        load_builtin_capability_registry(),
        product_group="china_futures",
        facts={
            "hypothesis": {"origin": "native", "features": ["momentum"]},
            "research": {"needs_prior_art_dedup": False},
        },
    )
    triggered = resolve_graph_capabilities(
        build_draft_graph(),
        load_builtin_capability_registry(),
        product_group="china_futures",
        facts={
            "hypothesis": {
                "origin": "native",
                "features": ["inventory", "term_structure"],
            },
            "research": {"needs_prior_art_dedup": False},
        },
    )

    assert not_triggered["triggered_conditional_bindings"] == []
    assert not_triggered["triggered_conditional_gaps"] == []
    triggered_ids = {
        item["capability_id"]
        for item in triggered["triggered_conditional_bindings"]
    }
    assert triggered_ids == {"hypothesis.commodity-structure"}


def test_same_local_resolution_uses_content_addressed_cache() -> None:
    kwargs = {
        "product_group": "china_futures",
        "node_id": "factor_semantics",
        "facts": {
            "signal": {"frequency": "DAY1"},
            "hypothesis": {"features": ["momentum"]},
            "factor": {"is_multi": False},
        },
    }
    first = resolve_graph_capabilities(
        build_draft_graph(),
        load_builtin_capability_registry(),
        **kwargs,
    )
    second = resolve_graph_capabilities(
        build_draft_graph(),
        load_builtin_capability_registry(),
        **kwargs,
    )

    assert first["cache"]["hit"] is False
    assert second["cache"] == {
        "key": first["cache"]["key"],
        "hit": True,
        "scope": "process",
    }


def test_external_provider_change_invalidates_cache_and_fails_closed(
    tmp_path: Path,
) -> None:
    source = tmp_path / "SKILL.md"
    source.write_text("# Approved skill\n", encoding="utf-8")
    approved_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    graph = {
        "entry_node": "research",
        "nodes": [{
            "node_id": "research",
            "required_capabilities": ["research.external"],
        }],
        "edges": [],
    }
    registry = {
        "schema_version": 1,
        "catalog_id": "provider-fingerprint-test",
        "capabilities": [{
            "capability_id": "research.external",
            "industry_semantics": "Use an approved external research method.",
            "when_to_use": ["when the capability is required"],
            "preconditions": [],
            "prohibitions": [],
            "implementations": [{
                "implementation_id": "external.skill",
                "provider": "external",
                "kind": "skill",
                "approval_status": "approved",
                "execution_mode": "guidance_only",
                "product_scopes": ["all"],
                "source_path": str(source),
                "approved_source_sha256": approved_hash,
            }],
        }],
    }

    approved = resolve_graph_capabilities(
        graph,
        registry,
        product_group="equities",
    )
    source.write_text("# Provider changed the skill\n", encoding="utf-8")
    changed = resolve_graph_capabilities(
        graph,
        registry,
        product_group="equities",
    )

    assert approved["bindings"][0]["source_fingerprint"] == approved_hash
    assert approved["cache"]["hit"] is False
    assert changed["cache"]["hit"] is False
    assert changed["cache"]["key"] != approved["cache"]["key"]
    assert changed["bindings"] == []
    assert changed["gaps"][0]["reason"] == "provider_fingerprint_mismatch"
    assert changed["gaps"][0]["expected_sha256"] == approved_hash


def test_reference_cycle_skill_reuses_exact_approved_manifest() -> None:
    graph = {
        "entry_node": "discover",
        "nodes": [{
            "node_id": "discover",
            "required_capabilities": ["research-obligation.discover"],
        }],
        "edges": [],
    }
    registry = load_builtin_capability_registry()

    reused = resolve_graph_capabilities(
        graph,
        registry,
        product_group="china_futures",
    )
    approved = resolve_graph_capabilities(
        graph,
        registry,
        product_group="china_futures",
        approved_implementation_ids={"local.research-obligation-cycle"},
    )

    assert reused["gaps"] == []
    assert reused["bindings"][0]["execution_approval_granted"] is False
    assert reused["bindings"][0]["local_execution_approval_required"] is True
    assert approved["gaps"] == []
    assert approved["bindings"][0]["execution_approval_granted"] is True
    assert approved["bindings"][0]["source_fingerprint"] == (
        registry["provider_lock"]["implementations"]
        ["local.research-obligation-cycle"]["sha256"]
    )


def test_obligation_skill_guides_temporal_product_and_event_transfer() -> None:
    skill_root = (
        Path(__file__).parents[1] / "skills" / "research-obligation-cycle"
    )
    discovery = (
        skill_root / "references" / "obligation-discovery.md"
    ).read_text(encoding="utf-8")
    synthesis = (
        skill_root / "references" / "trial-synthesis.md"
    ).read_text(encoding="utf-8")
    event_search = (
        skill_root / "references" / "market-context-event-search.md"
    ).read_text(encoding="utf-8")

    assert "time, market state, or instruments" in discovery
    assert "interval-specific events" in discovery
    assert "Do not generate the Cartesian product" in discovery
    assert "Do not load" in discovery
    assert "search the web for ordinary stable windows" in discovery
    assert "factortester custom_factors describe <factor-ref>" in discovery
    assert "self-discovery, a grill, or an external audit" in discovery
    assert "match an existing obligation category" in discovery
    assert "explicitly unclassified" in discovery
    assert "`column_refs` contains only fixed `ColumnRef`" in discovery
    assert "Do not create an obligation\nfor every fixed column" in discovery
    assert "Use a two-stage gate" in discovery
    assert "fallback_unadjusted" in discovery
    assert "strictly generalizes its parent" in discovery
    assert "old job evidence, sample exposure" in discovery
    assert "TrialPlan schema version 5" in synthesis
    assert "ordered `evidence_actions` list" in synthesis
    assert "Do not use legacy v4 aliases" in synthesis
    assert "expanding or rolling" in synthesis
    assert "2024 for selection and seal 2025 as holdout" in synthesis
    assert "month- or day-scale stages" in synthesis
    assert "purge or embargo" in synthesis
    assert "latest feasible interval or prospective stream" in synthesis
    assert "unseen product is not out-of-sample" in synthesis
    assert "event-source cutoff" in synthesis
    assert "historical_adaptive_evidence" in synthesis
    assert "live_execution_evidence" in synthesis
    assert "forward_shadow_evidence" in synthesis
    assert "latency_class=delayed" in synthesis
    assert "historical_simulation_evidence" in synthesis
    assert "publicly_available_at" in event_search
    assert "at most three distinguishable" in event_search
    assert "one event-research sub-agent only" in event_search
    assert "bounded_unknown" in event_search
    assert "`co_occurrence`" in event_search
    assert "`mechanism_hypothesis`" in event_search
    assert "`causal_evidence`" in event_search
    assert "Never promote `co_occurrence` directly to `caused_by`" in (
        event_search
    )
    assert "`performance_transportability`" in discovery
    assert "`market_context_heterogeneity`" in discovery


def test_reference_change_invalidates_whole_skill_manifest(
    tmp_path: Path,
) -> None:
    (tmp_path / "SKILL.md").write_text("# Router\n", encoding="utf-8")
    (tmp_path / "mode.md").write_text("# Mode v1\n", encoding="utf-8")
    paths = ["SKILL.md", "mode.md"]
    before = source_manifest_sha256(tmp_path, paths)
    graph = {
        "entry_node": "research",
        "nodes": [{
            "node_id": "research",
            "required_capabilities": ["research.bundle"],
        }],
        "edges": [],
    }
    registry = {
        "schema_version": 1,
        "catalog_id": "bundle-fingerprint-test",
        "capabilities": [{
            "capability_id": "research.bundle",
            "industry_semantics": "Use one approved research bundle.",
            "when_to_use": ["when requested"],
            "preconditions": [],
            "prohibitions": [],
            "implementations": [{
                "implementation_id": "bundle.skill",
                "provider": "bundle",
                "kind": "skill",
                "approval_status": "approved",
                "execution_mode": "guidance_only",
                "requires_execution_approval": True,
                "product_scopes": ["all"],
                "source_path": "SKILL.md",
            }],
        }],
        "provider_lock": {
            "schema_version": 1,
            "providers": {
                "bundle": {"root_hint": str(tmp_path)},
            },
            "implementations": {
                "bundle.skill": {
                    "source_paths": paths,
                    "sha256": before,
                },
            },
        },
    }
    unapproved = resolve_graph_capabilities(
        graph,
        registry,
        product_group="equities",
    )
    approved = resolve_graph_capabilities(
        graph,
        registry,
        product_group="equities",
        approved_implementation_ids={"bundle.skill"},
    )

    (tmp_path / "mode.md").write_text("# Mode v2\n", encoding="utf-8")
    changed = resolve_graph_capabilities(
        graph,
        registry,
        product_group="equities",
        approved_implementation_ids={"bundle.skill"},
    )

    assert unapproved["gaps"] == []
    assert unapproved["bindings"][0]["execution_approval_granted"] is False
    assert unapproved["bindings"][0]["local_execution_approval_required"] is True
    assert approved["bindings"][0]["source_fingerprint"] == before
    assert approved["bindings"][0]["execution_approval_granted"] is True
    assert approved["bindings"][0][
        "local_execution_approval_required"
    ] is False
    assert approved["bindings"][0]["execution_approval_source"] == (
        "explicit_grant"
    )
    assert changed["bindings"] == []
    assert changed["gaps"][0]["reason"] == "provider_fingerprint_mismatch"


def test_cycle_evidence_validation_is_local_and_rejects_skill_identity() -> None:
    evidence = {
        "research_cycle": {
            "schema_version": 1,
            "events": [{
                "event_type": "adjudication_proposed",
                "proposal": _research_cycle_discovery_proposal(),
            }],
        },
    }

    validated = validate_transition_evidence(evidence)

    assert validated["proposal_count"] == 1
    assert validated["proposal_kinds"] == ["obligation_discovery"]
    evidence["research_cycle"]["events"][0]["proposal"]["skill_name"] = (
        "must-stay-local"
    )
    with pytest.raises(ValueError, match="Skill identity"):
        validate_transition_evidence(evidence)


def test_cycle_evidence_rejects_non_object_reentry_predicates() -> None:
    proposal = _research_cycle_discovery_proposal()
    proposal["decision_warrant"]["reentry_predicates"] = [
        "factor version changes"
    ]
    evidence = {
        "research_cycle": {
            "schema_version": 1,
            "events": [{
                "event_type": "adjudication_proposed",
                "proposal": proposal,
            }],
        },
    }

    with pytest.raises(
        ValueError,
        match="reentry_predicates must be an object array",
    ):
        validate_transition_evidence(evidence)


def test_obligation_proposal_budget_is_independent_of_context_packet(
    tmp_path: Path,
) -> None:
    proposal = _research_cycle_discovery_proposal()
    proposal["obligation_delta"][0]["obligation"][
        "discharge_criterion"
    ] = {
        "method": "semantic and deterministic equivalence review",
        "checks": [
            f"check-{index:02d}:" + "x" * 180
            for index in range(35)
        ],
    }
    proposal_path = tmp_path / "proposal.json"
    proposal_path.write_text(
        json.dumps(proposal, ensure_ascii=False),
        encoding="utf-8",
    )
    assert proposal_path.stat().st_size > 6000
    script = (
        Path(__file__).resolve().parents[1]
        / "skills"
        / "research-obligation-cycle"
        / "scripts"
        / "validate-obligation-proposal.py"
    )

    result = subprocess.run(
        [sys.executable, str(script), "--input", str(proposal_path)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    validated = json.loads(result.stdout)
    assert validated["valid"] is True
    assert validated["bytes"] > 6000


def test_cycle_next_packet_rejects_full_graph_and_raw_output() -> None:
    packet = {
        "graph": "factor-research@v2",
        "node": {"node_id": "factor_semantics"},
        "candidate_edges": [{
            "edge_id": "factor_semantics__validation_design",
            "required_research_evidence": ["factor semantics evidence"],
            "required_transition_facts": ["semantic discovery is fresh"],
        }],
    }
    assert validate_next_packet(packet) == packet
    with pytest.raises(ValueError, match="routine packet field"):
        validate_next_packet({**packet, "stdout": "large raw output"})
    with pytest.raises(ValueError, match="graph must be a reference"):
        validate_next_packet({**packet, "graph": {"nodes": []}})
    with pytest.raises(ValueError, match="routine packet field"):
        validate_next_packet({
            **packet,
            "candidate_edges": [{
                "required_evidence": ["ambiguous requirement"],
                "required_research_evidence": [],
                "required_transition_facts": [],
            }],
        })


def test_model_identity_does_not_change_deterministic_resolution() -> None:
    graph = build_draft_graph()
    registry = load_builtin_capability_registry()
    first = resolve_graph_capabilities(
        graph,
        registry,
        product_group="china_futures",
        facts={"runtime": {"model_id": "model-a"}},
    )
    second = resolve_graph_capabilities(
        graph,
        registry,
        product_group="china_futures",
        facts={"runtime": {"model_id": "model-b"}},
    )

    assert first["semantic_cache_key"] == second["semantic_cache_key"]
    assert first["bindings"] == second["bindings"]
    assert first["gaps"] == second["gaps"]


def test_historical_preflight_replay_requires_v4_discovery_reentry() -> None:
    trace = json.loads(
        (FIXTURES / "historical_preflight_2026_07_16.json").read_text()
    )
    before = json.dumps(trace, sort_keys=True)

    report = replay_graph_trace(build_draft_graph(), trace)

    assert json.dumps(trace, sort_keys=True) == before
    assert report["external_mutations"] == 0
    assert report["status"] == "failed"
    assert report["branches"]["primary"]["current_node"] == (
        "hypothesis_preregistration"
    )
    assert report["branches"]["primary"]["status"] == "running"
    assert report["source"]["stale_historical_evidence"] is True
    assert report["coverage"]["edge_ids"] == []
    assert report["errors"] == [
        "event 0: unsatisfied guards: "
        "obligation_discovery_checkpoint_fresh"
    ]


def test_replay_rejects_an_unsatisfied_guard_without_running_work() -> None:
    report = replay_graph_trace(build_draft_graph(), {
        "schema_version": 1,
        "source": {"expected_outcome": "complete"},
        "events": [{
            "type": "transition",
            "branch_id": "primary",
            "edge_id": "hypothesis__capability_resolution",
            "evidence": {"hypothesis_frozen": False},
        }],
    })

    assert report["status"] == "failed"
    assert report["external_mutations"] == 0
    assert "hypothesis_frozen" in report["errors"][0]


def test_replay_derives_data_guards_from_server_evidence() -> None:
    graph = build_draft_graph()
    graph["entry_node"] = "data_contract"
    graph["content_hash"] = graph_content_hash(graph)
    envelope = validate_evidence_envelope({
        "schema_version": 2,
        "envelope_id": "availability-replay",
        "evidence_kind": "data_availability",
        "source_refs": ["data-availability-profile:" + "a" * 64],
        "identity_refs": {
            "contract_hash": "1" * 64,
            "methodology_hash": "2" * 64,
        },
        "facts": {
            "profile_ref": "data-availability-profile:sha256:" + "a" * 64,
            "profile_as_of": "2026-07-20T00:00:00+00:00",
            "request": {
                "products": ["A.DCE"],
                "sources": ["Local"],
                "frequencies": ["MIN1"],
                "probe": False,
                "expanded": False,
            },
            "product_status": [{
                "product": "A.DCE",
                "available": True,
            }],
            "requested_product_availability_present": True,
        },
        "metric_refs": [],
        "artifact_refs": [],
        "hypotheses_tested": 0,
        "stop_condition": None,
        "limitations": [],
        "conflicts": [],
    })
    provenance = validate_evidence_envelope({
        "schema_version": 2,
        "envelope_id": "provenance-replay",
        "evidence_kind": "data_contract",
        "source_refs": ["data-availability-profile:sha256:" + "a" * 64],
        "identity_refs": {
            "contract_hash": "1" * 64,
            "methodology_hash": "2" * 64,
        },
        "facts": {
            "profile_ref": "data-availability-profile:sha256:" + "a" * 64,
            "snapshot_status": "recorded",
            "requested_product_availability_present": True,
            "replayable": True,
            "recorded_dimensions": ["coverage"],
            "unresolved_dimensions": ["availability_time"],
        },
        "metric_refs": [],
        "artifact_refs": [],
        "hypotheses_tested": 0,
        "stop_condition": None,
        "limitations": [],
        "conflicts": [],
    })
    checkpoint = {
        "obligations": [{
            "requirement_refs": ["data-availability.scope"],
            "materiality": "decision_blocking",
            "status": "bounded",
        }],
    }
    evidence = {
        "research_cycle_checkpoint": checkpoint,
        "server_evidence": {
            "data_availability": envelope,
            "data_provenance": provenance,
        },
    }

    report = replay_graph_trace(graph, {
        "schema_version": 1,
        "events": [{
            "type": "transition",
            "edge_id": "data_contract__factor_semantics",
            "evidence": evidence,
        }],
    })

    assert report["status"] == "complete"
    assert report["branches"]["primary"]["current_node"] == "factor_semantics"


def test_bounded_data_obligation_does_not_forge_profile_availability() -> None:
    envelope = validate_evidence_envelope({
        "schema_version": 2,
        "envelope_id": "availability-bounded-gap",
        "evidence_kind": "data_availability",
        "source_refs": ["data-availability-profile:" + "a" * 64],
        "identity_refs": {
            "contract_hash": "1" * 64,
            "methodology_hash": "2" * 64,
        },
        "facts": {
            "profile_ref": "data-availability-profile:sha256:" + "a" * 64,
            "request": {
                "products": ["A.DCE"],
                "sources": ["Local"],
                "frequencies": ["MIN1"],
            },
            "product_status": [{"product": "A.DCE", "available": False}],
            "requested_product_availability_present": False,
        },
        "metric_refs": [],
        "artifact_refs": [],
        "hypotheses_tested": 0,
        "stop_condition": None,
        "limitations": [],
        "conflicts": [],
    })
    evidence = {
        "research_cycle_checkpoint": {
            "obligations": [{
                "requirement_refs": ["data.source_availability"],
                "obligation_kind": "data_feasibility",
                "materiality": "decision_blocking",
                "status": "bounded",
            }],
        },
        "server_evidence": {"data_availability": envelope},
    }

    normal = derive_server_guard_facts(
        {
            "server_action": "bind_data_availability",
            "to_node": "factor_semantics",
        },
        evidence,
    )
    gap = derive_server_guard_facts(
        {
            "server_action": "bind_data_availability",
            "to_node": "capability_gap",
        },
        evidence,
    )

    assert normal["requested_product_availability_present"] is True
    assert normal[
        "material_data_obligations_adjudicated_or_not_triggered"
    ] is True
    assert gap["requested_product_availability_present"] is False


def test_replay_does_not_require_a_global_timing_flag() -> None:
    graph = build_draft_graph()
    graph["entry_node"] = "data_contract"
    graph["content_hash"] = graph_content_hash(graph)
    availability = validate_evidence_envelope({
        "schema_version": 2,
        "envelope_id": "availability-replay-missing-debt",
        "evidence_kind": "data_availability",
        "source_refs": ["data-availability-profile:sha256:" + "a" * 64],
        "identity_refs": {
            "contract_hash": "1" * 64,
            "methodology_hash": "2" * 64,
        },
        "facts": {
            "profile_ref": "data-availability-profile:sha256:" + "a" * 64,
            "request": {
                "products": ["A.DCE"],
                "sources": ["Local"],
                "frequencies": ["MIN1"],
            },
            "product_status": [{"product": "A.DCE", "available": True}],
            "requested_product_availability_present": True,
        },
        "metric_refs": [], "artifact_refs": [], "hypotheses_tested": 0,
        "stop_condition": None, "limitations": [], "conflicts": [],
    })
    provenance = validate_evidence_envelope({
        "schema_version": 2,
        "envelope_id": "provenance-replay-missing-debt",
        "evidence_kind": "data_contract",
        "source_refs": ["data-availability-profile:sha256:" + "a" * 64],
        "identity_refs": {
            "contract_hash": "1" * 64,
            "methodology_hash": "2" * 64,
        },
        "facts": {
            "profile_ref": "data-availability-profile:sha256:" + "a" * 64,
            "snapshot_status": "recorded",
            "requested_product_availability_present": True,
            "replayable": True,
            "recorded_dimensions": ["coverage"],
            "unresolved_dimensions": ["availability_time"],
        },
        "metric_refs": [], "artifact_refs": [], "hypotheses_tested": 0,
        "stop_condition": None,
        "limitations": [],
        "conflicts": [],
    })

    report = replay_graph_trace(graph, {
        "schema_version": 1,
        "events": [{
            "type": "transition",
            "edge_id": "data_contract__factor_semantics",
            "evidence": {
                "research_cycle_checkpoint": {"obligations": []},
                "server_evidence": {
                    "data_availability": availability,
                    "data_provenance": provenance,
                },
            },
        }],
    })

    assert report["status"] == "complete"


def test_transition_validation_rejects_client_server_evidence() -> None:
    with pytest.raises(ValueError, match="server_evidence is server-owned"):
        validate_transition_evidence({
            "server_evidence": {
                "data_availability": {"forged": True},
            },
        })


def test_transition_validation_rejects_client_entry_resolution_delta() -> None:
    with pytest.raises(ValueError, match="entry_resolution_delta is server-owned"):
        validate_transition_evidence({
            "entry_resolution_delta": {
                "reused_requirement_ids": ["data.required_fields"],
            },
        })


def test_replay_derives_factor_semantics_guards_from_server_evidence() -> None:
    envelope = validate_evidence_envelope({
        "schema_version": 2,
        "envelope_id": "factor-semantics-replay",
        "evidence_kind": "factor_semantics",
        "source_refs": ["factor-revision:" + "a" * 64],
        "identity_refs": {
            "contract_hash": "1" * 64,
            "methodology_hash": "2" * 64,
        },
        "facts": {
            "factor_revision_refs": [{
                "manifest_hash": "a" * 64,
                "resolution_status": "resolved",
            }],
        },
        "metric_refs": [],
        "artifact_refs": [],
        "hypotheses_tested": 0,
        "stop_condition": None,
        "limitations": [],
        "conflicts": [],
    })

    facts = derive_server_guard_facts(
        {"server_action": "bind_factor_semantics"},
        {"server_evidence": {"factor_semantics": envelope}},
    )

    assert facts == {
        "frozen_factor_formulas_bound": True,
        "selected_factor_semantics_resolved": True,
    }


def test_replay_derives_trusted_job_guards_from_server_evidence() -> None:
    net_return_ref = "artifact:net_returns:sha256:" + "a" * 64
    envelope = validate_evidence_envelope({
        "schema_version": 2,
        "envelope_id": "job-attempt:job-1",
        "evidence_kind": "job_attempt",
        "source_refs": ["research-job:job-1", "research-run:run-1"],
        "identity_refs": {
            "contract_hash": "1" * 64,
            "methodology_hash": "2" * 64,
            "trial_plan_hash": "3" * 64,
            "run_spec_hash": "4" * 64,
        },
        "facts": {
            "status": "succeeded",
            "net_return_series_available": True,
            "net_return_series_ref": net_return_ref,
            "assurance": {
                "disposition": "trusted",
                "anomaly_codes": [],
            },
        },
        "metric_refs": [],
        "artifact_refs": [net_return_ref],
        "hypotheses_tested": 0,
        "stop_condition": None,
        "limitations": [],
        "conflicts": [],
    })

    facts = derive_server_guard_facts(
        {"server_action": "bind_job_attempt"},
        {"server_evidence": {"job_attempt": envelope}},
    )
    assert facts == {
        "terminal_job_evidence_retained": True,
        "terminal_job_trusted": True,
        "net_return_series_available": True,
    }

    envelope["facts"]["assurance"]["disposition"] = "maintenance_required"
    envelope["facts"]["assurance"]["anomaly_codes"] = ["worker_crashed"]
    envelope.pop("envelope_hash")
    facts = derive_server_guard_facts(
        {"server_action": "bind_job_attempt"},
        {"server_evidence": {"job_attempt": envelope}},
    )
    assert facts["terminal_job_trusted"] is False


def test_plan_uses_one_workspace_run_job_contract() -> None:
    plan = build_factor_research_plan(
        factor_families=["SgCCS", "MmRet"],
        factors=["SgCCS=SgCCS|P:CA|N:10d", "MmRet=MmRet|P:CA|N:5d"],
        products=["A.DCE", "RB.SHF"],
        sources=["Local"],
        configuration_file="run spec.json",
        analyses=["ic", "factor_type_analysis", "backtest"],
    )
    commands = "\n".join(item["command"] for item in plan)
    phases = [item["phase"] for item in plan]
    assert phases[0] == "inspect_data_availability"
    assert phases.index("inspect_data_availability") < phases.index("design_trial_plan")
    assert phases.index("understand_factor_source") < phases.index("submit_run")
    assert (
        "products availability --product A.DCE --product RB.SHF "
        "--source Local --frequency MIN1 --probe --json"
    ) in commands
    assert "slice-plan" not in commands
    assert "2024-01-01" not in commands
    assert "2026-01-01" not in commands
    trial_design = next(
        item for item in plan if item["phase"] == "design_trial_plan"
    )
    assert set(trial_design["required_inputs"]) >= {
        "confirmed_product_scope",
        "data_availability_profile_ref",
        "decision_contract_ref",
        "actionable_obligation_refs",
        "factor_semantics_ref",
        "signal_timing_ref",
        "product_accounting_ref",
        "trial_ledger_ref",
        "sample_role_and_freeze_policy",
    }
    assert trial_design["conditional_inputs"] == [{
        "input": "material_data_obligation_refs",
        "when": "material_data_question_triggered",
    }]
    assert "availability payload" not in json.dumps(plan)
    assert "workspace create --factor-family SgCCS --factor-family MmRet" in commands
    assert "--factor 'SgCCS=SgCCS|P:CA|N:10d'" in commands
    assert "workspace update --file 'run spec.json'" in commands
    assert "run submit --analysis ic --analysis factor_type_analysis --analysis backtest" in commands
    assert "job watch <job_id>" in commands
    assert "single_factor_test" not in commands
    assert "ic_test grid" not in commands
    assert "backtest compare" not in commands


def test_plan_treats_factor_families_as_values() -> None:
    plan = build_factor_research_plan(
        factor_families=["MyCustomFamily", "AnotherFamily"],
        products=["A.DCE"],
        sources=["Local"],
        configuration_file="configuration.json",
    )
    commands = "\n".join(item["command"] for item in plan)
    assert "--factor-family MyCustomFamily" in commands
    assert "--factor-family AnotherFamily" in commands
    assert "SgCCS" not in commands


def test_plan_requires_explicit_product_and_source_scope() -> None:
    with pytest.raises(ValueError, match="at least one product"):
        build_factor_research_plan(
            factor_families=["SgCCS"],
            products=[],
            sources=["Local"],
            configuration_file="configuration.json",
        )
    with pytest.raises(ValueError, match="at least one data source"):
        build_factor_research_plan(
            factor_families=["SgCCS"],
            products=["A.DCE"],
            sources=[],
            configuration_file="configuration.json",
        )


def test_validation_checklist_encodes_durable_and_quant_contracts() -> None:
    text = "\n".join(validation_checklist())
    for required in (
        "RunSpec", "ranking universe", "product mask", "多重检验", "未来函数",
        "费用", "TrialPlan", "untouched/prospective holdout", "traceback",
        "TTL", "retry_of",
        "page_uuid",
    ):
        assert required in text


def test_gap_state_machine_blocks_and_resumes_research() -> None:
    session = ResearchSession(status="research_ready")
    gap = record_gap(session, "missing IC decay", "backend did not return decay")
    assert gap["id"] == "gap-1"
    assert session.status == "code_improvement_required"
    resolve_gap(session, "gap-1", note="implemented")
    assert session.status == "research_ready"


def test_local_skill_usage_ledger_records_identity_and_reuse_without_server() -> None:
    session = ResearchSession()
    common = {
        "capability_description": "Challenge a graph change.",
        "descriptor_hash": "a" * 64,
        "skill_name": "grill-me",
        "skill_description": "Challenge a plan through structured questions.",
        "provider": "local",
        "version": "1",
        "source_fingerprint": "b" * 64,
        "approval_ref": "audit:skill-execution:17",
        "matching_rationale": "The capability requires adversarial review.",
    }
    loaded = record_skill_usage(
        session,
        **common,
        load_mode="loaded",
        skill_document_tokens=120,
    )
    reused = record_skill_usage(
        session,
        **common,
        load_mode="reused",
        cache_read_tokens=80,
    )

    assert loaded["record_hash"]
    assert reused["previous_record_hash"] == loaded["record_hash"]
    assert reused["skill_document_tokens"] == 0
    assert session.to_dict()["skill_usage"][1]["skill_name"] == "grill-me"


def test_local_evidence_envelope_keeps_output_behind_hashed_refs(
    tmp_path: Path,
) -> None:
    session_path = tmp_path / "research.json"
    envelope = persist_command_evidence(
        session_path=str(session_path),
        envelope_id="command-1",
        argv=["factortester", "job", "show", "job-1"],
        returncode=0,
        stdout='{"status":"complete"}\n',
        stderr="",
        hypotheses_tested=3,
        stop_condition=None,
    )

    assert validate_evidence_envelope(envelope)["schema_version"] == 2
    assert "decision" not in envelope
    assert envelope["evidence_kind"] == "control_command"
    assert envelope["identity_refs"] == {}
    assert envelope["command"]["stdout_ref"].startswith("local-artifact:")
    assert '{"status"' not in json.dumps(envelope)
    assert len(envelope["envelope_hash"]) == 64

    tampered = {**envelope, "envelope_hash": "0" * 64}
    with pytest.raises(ValueError, match="envelope_hash mismatch"):
        validate_evidence_envelope(tampered)

    run_evidence = {
        **envelope,
        "evidence_kind": "job_attempt",
    }
    with pytest.raises(
        ValueError,
        match="job_attempt evidence requires identity_refs.contract_hash",
    ):
        validate_evidence_envelope(run_evidence)


def test_job_evidence_adapter_rejects_assurance_identity_mismatch() -> None:
    envelope = validate_evidence_envelope({
        "schema_version": 2,
        "envelope_id": "job-attempt:job-1",
        "evidence_kind": "job_attempt",
        "source_refs": ["research-job:job-1"],
        "identity_refs": {
            "contract_hash": "1" * 64,
            "methodology_hash": "2" * 64,
            "trial_plan_hash": "3" * 64,
            "run_spec_hash": "4" * 64,
        },
        "facts": {
            "job_id": "job-1",
            "status": "succeeded",
            "assurance": {
                "policy_hash": "7" * 64,
                "backend_revision": "backend-1",
                "disposition": "trusted",
                "anomaly_codes": [],
            },
        },
        "metric_refs": ["result-summary:sha256:" + "5" * 64],
        "artifact_refs": ["artifact-manifest:sha256:" + "6" * 64],
        "hypotheses_tested": 0,
        "stop_condition": None,
        "limitations": [],
        "conflicts": [],
    })
    payload = {
        "job_id": "job-1",
        "status": "succeeded",
        "evidence": {
            "job_attempt": envelope,
            "terminal_assurance": {
                "run_spec_hash": "8" * 64,
                "result_summary_hash": "5" * 64,
                "artifact_manifest_hash": "6" * 64,
                "policy_hash": "7" * 64,
                "backend_revision": "backend-1",
                "disposition": "trusted",
                "anomaly_codes": [],
            },
        },
    }

    with pytest.raises(ValueError, match="terminal run_spec_hash"):
        extract_job_attempt(payload)


def test_agent_session_view_hides_legacy_evidence_but_persistence_retains_it(
) -> None:
    legacy = {
        "schema_version": 1,
        "envelope_id": "legacy-1",
        "envelope_hash": "a" * 64,
        "decision": "continue",
        "metric_refs": ["metric:private"],
        "artifact_refs": ["artifact:private"],
    }
    session = ResearchSession.from_dict({
        "evidence_envelopes": [legacy],
        "events": [{
            "event": "historical_decision",
            "evidence": legacy,
        }],
    })

    agent_view = session.to_dict()
    persisted = session.to_persisted_dict()

    assert agent_view["evidence_envelopes"] == []
    assert agent_view["legacy_evidence_unavailable_count"] == 1
    assert "metric:private" not in json.dumps(agent_view)
    assert agent_view["events"][0]["evidence"] == {
        "legacy_evidence_unavailable": True,
    }
    assert persisted["evidence_envelopes"] == [legacy]
    assert persisted["events"][0]["evidence"] == legacy

    with pytest.raises(ValueError, match="legacy evidence is unavailable"):
        validate_evidence_envelope({
            "schema_version": 1,
            "envelope_id": "minimal-legacy",
            "envelope_hash": "b" * 64,
        })


def test_service_target_selection_requires_unambiguous_worktree() -> None:
    worktrees = [
        ManagedWorktree("worktree-feat", "feat", "feat", 7999, False, False),
        ManagedWorktree(
            "worktree-issue-123", "fix/issue-123", "fix/issue-123",
            8123, True, True,
        ),
    ]
    assert select_worktree(worktrees, target_port=8123).branch == "fix/issue-123"
    assert select_worktree(
        worktrees, instance_id="worktree-issue-123"
    ).port == 8123


def test_explicit_legacy_validation_plan_separates_selection_from_holdout() -> None:
    payload = default_factor_validation_plan(
        in_sample_start="2024-01-01",
        in_sample_end="2025-12-31",
        oos_start="2026-01-01",
        oos_end="2026-12-31",
    ).to_dict()
    assert payload["in_sample_end"] == "2025-12-31"
    assert payload["oos_start"] == "2026-01-01"
    all_slices = [item for group in payload["slice_sets"] for item in group["slices"]]
    assert any(item["kind"] == "rolling" for item in all_slices)
    assert not any(
        item["purpose"] in {"selection", "validation"} and item["start"].startswith("2026")
        for item in all_slices
    )


def test_packaging_and_docs_record_durable_remote_contract() -> None:
    packaging = (HARNESS_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    readme = (HARNESS_ROOT / "cli_anything/factortester_research/README.md").read_text(encoding="utf-8")
    skill = (HARNESS_ROOT / "cli_anything/factortester_research/skills/SKILL.md").read_text(encoding="utf-8")
    assert 'requires-python = ">=3.11"' in packaging
    for text in (readme, skill):
        assert "workspace" in text
        assert "RunSpec" in text
        assert "job_id" in text
        assert "page_uuid" in text


def test_installed_skill_uses_local_discovery_identity_and_hides_derived_fields() -> None:
    skill = (
        HARNESS_ROOT / "cli_anything/factortester_research/skills/SKILL.md"
    ).read_text(encoding="utf-8")
    assert "name: factortester-research-skill" in skill
    assert "Do not copy a command from a server `next_actions` field" in skill
    assert "The Agent never writes `expected_base_hash`" in skill
    assert "complete\n`obligation_coverage_submission`" in skill
    assert "stop and report" in skill
    assert "platform-contract defect" in skill
    normalized = " ".join(skill.split())
    assert "Apply typed-reference rules to every Markdown-bearing location" in normalized
    assert "do not use inline code as a fallback" in normalized
    assert "A mathematical variable, relation, or formula uses inline" in normalized
    assert "A literal field, function, CLI parameter" in normalized


def test_installed_skill_discloses_job_output_workflow() -> None:
    skill = (
        HARNESS_ROOT / "cli_anything/factortester_research/skills/SKILL.md"
    ).read_text(encoding="utf-8")
    normalized = " ".join(skill.split())

    assert "factortester job output-capabilities --json" in skill
    assert "IC sequence and statistics" in normalized
    assert "factortester job generate <job-id>" in skill
    assert "do not replace Job artifacts with terminal summaries" in normalized


def test_canonical_and_packaged_skill_copies_match() -> None:
    """Fail packaging when the installed progressive-disclosure guide drifts."""
    packaged = Path(__file__).resolve().parents[1] / "skills" / "SKILL.md"
    repository = next(
        parent
        for parent in Path(__file__).resolve().parents
        if (
            parent
            / "skills"
            / "cli-anything-factortester-research"
            / "SKILL.md"
        ).is_file()
    )
    canonical = (
        repository
        / "skills"
        / "cli-anything-factortester-research"
        / "SKILL.md"
    )

    assert packaged.read_bytes() == canonical.read_bytes()


def test_installed_skill_distinguishes_structure_nodes_from_content() -> None:
    skill = (
        Path(__file__).resolve().parents[1] / "skills" / "SKILL.md"
    ).read_text(encoding="utf-8")
    normalized = " ".join(skill.split())

    assert "Structure nodes organize and nest the report" in normalized
    assert "require a meaningful `--title`" in normalized
    assert "Content components carry the report material" in normalized
    assert "never carry `--title`" in normalized
    assert "never use `正文`, `表格`, or `列表` as a structure title" in normalized
    assert "English placeholders `Body`, `Table`, and `List`" in normalized


def test_installed_skill_keeps_typed_reference_authoring_with_the_agent() -> None:
    """The shipped guide must not delegate object inference to the CLI."""
    skill = (
        Path(__file__).resolve().parents[1] / "skills" / "SKILL.md"
    ).read_text(encoding="utf-8")
    normalized = " ".join(skill.split())

    assert "Agent alone decides whether prose denotes a domain object" in normalized
    assert "complete typed Markdown link" in normalized
    assert "`kind`, exact `target_ref`, and display label" in normalized
    assert "CLI never generates or rewrites these links" in normalized
    assert "never scans surrounding prose to infer an object" in normalized
    assert (
        "[工业硅](factortester://product/"
        "Product%2FFutures%2FCNFutures%2F_products%2FSI.GFE)"
    ) in skill
    assert "bf7ae6d94a7c35d2280107d332dbaf04c4f50b07" in skill
    assert "1aa9a9908b8f1f034973ebfe5819115e13c16cde" in skill
    assert "1111111111111111111111111111111111111111" not in skill
    assert "--submission-sequence <sequence>" in normalized
    assert (
        "Do not submit a different report change while it is pending"
        in normalized
    )
    assert "report show --json" in normalized
    assert "next target report generation" in normalized
    assert "report reference" not in skill


def test_installed_skill_defines_non_nested_continuation_order() -> None:
    skill = (
        Path(__file__).resolve().parents[1] / "skills" / "SKILL.md"
    ).read_text(encoding="utf-8")
    normalized = " ".join(skill.split())
    lower = normalized.lower()

    assert "Graph version changes and local continuation" in skill
    assert "download it explicitly and inspect its local topology" in normalized
    assert "there is no server-side continuation preview" in lower
    assert "local continuation event" in normalized
    assert "do not ask a manager to manufacture the next edge" in lower


def test_installed_skill_keeps_entry_resolution_and_reporting_orthogonal() -> None:
    skill = (
        Path(__file__).resolve().parents[1] / "skills" / "SKILL.md"
    ).read_text(encoding="utf-8")
    normalized = " ".join(skill.split())

    assert "Entry Requirement, obligation, and report invariants" in skill
    assert "stable, coarse Verification Obligation category" in normalized
    assert "versioned Entry Requirement subclass" in normalized
    assert "branch-local Verification Obligation" in normalized
    assert "server issues an eligible or limited receipt" in normalized
    assert "Report Requirement is an independent output contract" in normalized
    assert (
        "completed report item" not in normalized
        or "does not infer obligation coverage" in normalized
    )


def test_harness_production_modules_stay_below_500_lines() -> None:
    package = Path(__file__).resolve().parents[1]
    oversized = {
        str(path.relative_to(package)): len(
            path.read_text(encoding="utf-8").splitlines()
        )
        for path in package.rglob("*.py")
        if "tests" not in path.parts
        and len(path.read_text(encoding="utf-8").splitlines()) >= 500
    }

    assert oversized == {}


def test_vibe_pipeline_includes_daily_minute_and_server_handoff(tmp_path: Path) -> None:
    steps = vibe_pipeline_plan(
        integration_root=str(tmp_path / "integration"),
        data_root=str(tmp_path / "LocalCNFutures"),
        alpha_id="academic_carhart_mom",
    )
    phases = [item["phase"] for item in steps]
    assert phases[:4] == [
        "run_versioned_pipeline", "build_daily_panel", "build_minute_panel",
        "compute_vibe_daily_factor",
    ]
    assert steps[-1]["status"] == "ready_for_server_validation"
    assert "external-factor validate" in steps[-1]["reason"]


def test_external_manifests_require_next_bar_and_experimental_status(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset.json"
    dataset.write_text(
        '{"schema_version":1,"rows":10,"symbols":2,'
        '"frequency":"1min","timing":{"earliest_execution":"next_bar"}}',
        encoding="utf-8",
    )
    factor = tmp_path / "factor.json"
    factor.write_text(
        '{"schema_version":1,"alpha_id":"x",'
        '"research_status":"experimental_unvalidated","input":{},'
        '"output":{"finite_observations":8},'
        '"timing":{"earliest_execution":"next_bar"}}',
        encoding="utf-8",
    )
    dataset_result = validate_dataset_manifest(str(dataset))
    assert dataset_result["frequency"] == "1min"
    assert "point_in_time_eligible" not in dataset_result
    assert validate_factor_manifest(str(factor))["alpha_id"] == "x"


def test_handoff_manifest_keeps_import_boundary_explicit(tmp_path: Path) -> None:
    factor = tmp_path / "factor.parquet"
    factor.write_bytes(b"PAR1")
    handoff = tmp_path / "handoff.json"
    handoff.write_text(json.dumps({
        "schema_version": 1,
        "status": "ready_for_gtht_import_contract",
        "alpha_id": "x",
        "factor": {"path": str(factor), "sha256": "unused"},
        "universe": {},
        "timing": {
            "execution": "next_bar", "same_close_execution_forbidden": True,
        },
        "research": {"status": "experimental_unvalidated"},
        "gtht": {
            "factor_mode": "precomputed", "import_contract_available": False,
        },
    }), encoding="utf-8")
    result = validate_handoff_manifest(str(handoff))
    assert result["kind"] == "gtht_handoff"
    assert result["import_contract_available"] is False
