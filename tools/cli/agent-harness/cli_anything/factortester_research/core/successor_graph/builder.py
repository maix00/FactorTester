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


def _change_manifest() -> dict[str, Any]:
    return {
        "parent_version": 8,
        "draft_revision": {
            "replaces_content_hash": (
                "4c74378667f1bba06689af7e4ef07f6f"
                "3a1e233c82eaf4c48705437e92011d29"
            ),
            "reason_code": "runtime_budget_profile_decoupling",
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
