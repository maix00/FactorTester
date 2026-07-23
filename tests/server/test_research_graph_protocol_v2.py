from __future__ import annotations

import pytest

from server.services.research_graph.protocol import validate_graph


def _minimal_graph_v2() -> dict:
    requirement_id = "data.product_source_availability"
    entry_report = "report.data.entry"
    action_report = "report.data.action"
    gate_report = "report.evidence.admission"
    return {
        "schema_version": 2,
        "graph_id": "factor-research",
        "version": 9,
        "parent_version": 8,
        "lifecycle": "draft",
        "research_semantics": "product_neutral",
        "entry_node": "data_contract",
        "nodes": [{
            "node_id": "data_contract",
            "enforcement": "deterministic",
            "required_capabilities": [],
            "conditional_capabilities": [],
            "entry_requirement_refs": [requirement_id],
            "entry_report_refs": [entry_report],
            "node_report_refs": [action_report],
        }],
        "edges": [],
        "research_cycle_operations": [],
        "maintenance_operations": [],
        "review_policy": {},
        "capability_descriptors": {
            "data.availability.resolve": {
                "capability_description": "Resolve bounded data availability facts.",
                "descriptor_hash": "1" * 64,
            },
        },
        "change_manifest": {
            "parent_version": 8,
            "summary_zh": "增加可验证的研究合同。",
            "changes": [{
                "change_id": "change.contract-v2",
                "change_kind": "schema",
                "subject_ref": "graph:factor-research@9",
                "impact_zh": "图发布前验证义务、报告和系统门。",
            }],
        },
        "requirement_catalog": {
            "catalog_revision": 1,
            "categories": [{
                "category_id": "data",
                "title_zh": "数据",
                "description_zh": "数据是否真实可得并适合当前试验。",
            }],
            "requirements": [{
                "requirement_id": requirement_id,
                "category_id": "data",
                "revision": 1,
                "gate_policy": "plan_before_exit",
                "title_zh": "产品数据源",
                "question_zh": "目标产品是否有可用数据源？",
                "select_when_zh": "进入数据契约时。",
                "evidence_expected_zh": ["数据源 availability receipt"],
                "not_sufficient_zh": ["只配置了 connector"],
                "industry_principle_zh": "数据存在、权限和适用范围必须分别验证。",
                "industry_basis_refs": ["S-DATA-PROVENANCE"],
                "resolver_capability_ids": ["data.availability.resolve"],
                "cli_invocation_templates": [
                    "factortester research data availability --json"
                ],
                "resolver_output_schema": {"type": "object"},
                "fallback_route": "capability_gap",
                "report_requirement_refs": [entry_report, action_report],
            }],
        },
        "report_method_descriptors": {
            "inventory": {
                "description_zh": "逐项列出事实和引用。",
                "allowed_content": ["list", "table"],
                "descriptor_hash": "2" * 64,
            },
        },
        "report_requirements": [
            {
                "report_requirement_id": entry_report,
                "anchor_kind": "node_entry",
                "anchor_ref": "data_contract",
                "method_ref": "inventory",
                "title_zh": "数据入口检查",
                "subject_selector": {"kind": "current_scope"},
                "requirement_ref": requirement_id,
            },
            {
                "report_requirement_id": action_report,
                "anchor_kind": "node_action",
                "anchor_ref": "data_contract",
                "method_ref": "inventory",
                "title_zh": "数据事实清单",
                "subject_selector": {"kind": "data_source"},
                "requirement_ref": requirement_id,
            },
            {
                "report_requirement_id": gate_report,
                "anchor_kind": "system_gate",
                "anchor_ref": "evidence_admission",
                "method_ref": "inventory",
                "title_zh": "证据准入",
                "subject_selector": {"kind": "evidence_envelope"},
                "coordination_ref": "evidence_qualification",
            },
        ],
        "system_transition_policies": [{
            "policy_id": "policy.evidence_admission",
            "policy_kind": "evidence_admission",
            "report_requirement_refs": [gate_report],
        }],
    }


def test_server_accepts_the_shared_schema_v2_graph_contract() -> None:
    first = validate_graph(_minimal_graph_v2())
    second = validate_graph(_minimal_graph_v2())

    assert first["content_hash"] == second["content_hash"]
    assert len(first["content_hash"]) == 64


def test_server_rejects_schema_v2_graph_embedded_runtime_budget() -> None:
    graph = _minimal_graph_v2()
    graph["agent_packet_budget"] = {
        "schema_version": 2,
        "protocol_hard_ceiling_bytes": 6400,
    }

    with pytest.raises(
        ValueError,
        match="schema-v2 Graph must not embed agent_packet_budget",
    ):
        validate_graph(graph)


def test_server_rejects_a_schema_v2_report_without_semantic_binding() -> None:
    graph = _minimal_graph_v2()
    graph["report_requirements"][0].pop("requirement_ref")

    with pytest.raises(ValueError, match="exactly one semantic binding"):
        validate_graph(graph)
