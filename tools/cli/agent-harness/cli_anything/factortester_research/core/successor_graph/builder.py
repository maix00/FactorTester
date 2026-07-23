"""Assemble the immutable schema-v2 successor Graph candidate."""

from __future__ import annotations

from typing import Any

from ..capabilities import capability_descriptor, load_builtin_capability_registry
from ..draft_graph_cycle import maintenance_operations, research_cycle_operations
from ..graph_protocol import graph_content_hash, validate_graph
from .catalog import (
    build_requirement_catalog,
    resolver_capability_descriptors,
)
from .reporting import (
    build_report_method_descriptors,
    build_report_requirements,
    system_transition_policies,
)
from .resolvers import build_requirement_resolver_bindings
from .topology import build_edges, build_nodes
from .sources import build_industry_basis_catalog


def build_successor_graph() -> dict[str, Any]:
    """Return the validated v9 candidate without activating it."""
    catalog = build_requirement_catalog()
    cycle_operations = research_cycle_operations()
    maintenance = maintenance_operations()
    capability_descriptors = resolver_capability_descriptors()
    registry = {
        str(item["capability_id"]): item
        for item in load_builtin_capability_registry()["capabilities"]
    }
    for item in [*cycle_operations, *maintenance]:
        capability_id = str(item["capability_id"])
        capability_descriptors[capability_id] = capability_descriptor(
            registry[capability_id]
        )
    nodes = build_nodes()
    edges = build_edges()
    transition_policies = system_transition_policies()
    graph = {
        "schema_version": 2,
        "graph_id": "factor-research",
        "version": 9,
        "parent_version": 8,
        "lifecycle": "draft",
        "research_semantics": "product_neutral",
        "entry_node": "hypothesis_preregistration",
        "nodes": nodes,
        "edges": edges,
        "research_cycle_operations": cycle_operations,
        "maintenance_operations": maintenance,
        "review_policy": {
            "routine": "deterministic gates and one primary Research Agent",
            "semantic_change": "one domain reviewer when evidence conflicts",
            "graph_or_skill_change": "grill-with-docs and human audit",
        },
        "capability_descriptors": capability_descriptors,
        "change_manifest": _change_manifest(),
        "requirement_catalog": catalog,
        "requirement_resolver_bindings": (
            build_requirement_resolver_bindings(catalog)
        ),
        "industry_basis_catalog": build_industry_basis_catalog(),
        "report_method_descriptors": build_report_method_descriptors(),
        "report_requirements": build_report_requirements(catalog),
        "report_policy": {
            "enforcement": "required",
            "submission_schema_version": 1,
            "local_body_policy": "hash_bound_local_only",
        },
        "system_transition_policies": transition_policies,
        "agent_packet_budget": _agent_packet_budget(
            nodes=nodes,
            edges=edges,
            system_gate_ids=sorted(
                str(item["policy_kind"]) for item in transition_policies
            ),
        ),
        "provenance": {
            "source": "grill-179-canonical-handoff",
            "description": (
                "Methods are TrialPlan Evidence Actions; Evidence admission "
                "and re-entry are deterministic system gates."
            ),
        },
    }
    graph = validate_graph(graph)
    graph["content_hash"] = graph_content_hash(graph)
    return graph


def _agent_packet_budget(
    *,
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    system_gate_ids: list[str],
) -> dict[str, Any]:
    """Declare what v9 calibration must prove before activation."""
    return {
        "schema_version": 2,
        "policy_ref": "agent-packet-budget@2",
        "protocol_hard_ceiling_bytes": 16 * 1024,
        "coverage": {
            "required_anchor_refs": [
                *(f"node:{item['node_id']}" for item in nodes),
                *(f"edge:{item['edge_id']}" for item in edges),
                *(f"system_gate:{item}" for item in system_gate_ids),
            ],
            "required_packet_kinds": ["context", "next"],
            "required_scenarios": ["typical", "max_legal"],
            "minimum_samples_per_case": 1,
        },
        "thresholds": {
            "minimum_byte_headroom_bytes": 512,
            "minimum_byte_headroom_ratio": 0.10,
            "minimum_token_headroom_ratio": 0.10,
            "maximum_e2e_latency_p95_ms": 5000.0,
            "maximum_truncated_rate": 0.0,
            "maximum_rejected_rate": 0.0,
            "maximum_failed_rate": 0.0,
        },
        "calibration_receipt_contract_ref": (
            "provider-verified-packet-calibration@1"
        ),
        "calibration_receipt_ref": "",
        "calibration_receipt_hash": "",
    }


def _change_manifest() -> dict[str, Any]:
    return {
        "parent_version": 8,
        "draft_revision": {
            "replaces_content_hash": (
                "dae9053ada256a60e8d1a3a69a8ad304"
                "9324d501c3da229df80c4054a47aef52"
            ),
            "reason_code": "independent_activation_review_blockers",
        },
        "summary_zh": (
            "按研究生命周期重编主路径，并加入版本化义务、逐项报告和系统门合同。"
        ),
        "changes": [
            {
                "change_id": "change.remove-method-nodes",
                "change_kind": "topology",
                "subject_ref": "graph:factor-research@9",
                "impact_zh": (
                    "删除固定 IC、bootstrap 和 Job 方法节点，改由 TrialPlan actions 选择。"
                ),
            },
            {
                "change_id": "change.trial-execution",
                "change_kind": "topology",
                "subject_ref": "node:trial_execution",
                "impact_zh": "统一同步测量、异步回测和外部观察的单项 Evidence Action。",
            },
            {
                "change_id": "change.requirement-catalog",
                "change_kind": "contract",
                "subject_ref": "requirement-catalog:3",
                "impact_zh": "加入七类研究义务、一类兜底义务及 provider-neutral resolver contract。",
            },
            {
                "change_id": "change.report-contract",
                "change_kind": "contract",
                "subject_ref": "report-contract:1",
                "impact_zh": "每个节点、边和系统门必须逐项提交中文报告。",
            },
        ],
    }
