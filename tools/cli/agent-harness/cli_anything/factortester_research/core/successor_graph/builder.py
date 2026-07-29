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
    """Return the validated v10 candidate without activating it."""
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
        "version": 10,
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
        "summary_zh": (
            "移除全局 PIT 布尔门槛；数据可用性按实际底层频率收窄，"
            "因果时点由运行时信号与成交事件对齐；能力绕行保持单一"
            "恢复位置，并由服务端声明报告容器。"
        ),
        "changes": [
            {
                "change_id": "change.remove-global-pit-gate",
                "change_kind": "contract",
                "subject_ref": "data-contract:source-availability",
                "impact_zh": (
                    "数据源不再以 point_in_time 字段或 capability 阻断研究；"
                    "未解决的数据问题仍以明确义务记录。"
                ),
            },
            {
                "change_id": "change.frequency-scoped-availability",
                "change_kind": "contract",
                "subject_ref": "data-availability-request:frequencies",
                "impact_zh": "可用性证据必须绑定实际底层频率，DAY1 信号通常检查 MIN1。",
            },
            {
                "change_id": "change.temporal-alignment-language",
                "change_kind": "requirement",
                "subject_ref": "data.temporal_alignment",
                "impact_zh": "将数据时间问题表达为逐输入事件与下一可成交时点的对齐，不再使用全局标签。",
            },
            {
                "change_id": "change.capability-detour-resume",
                "change_kind": "contract",
                "subject_ref": "graph:factor-research#capability-detour",
                "impact_zh": "能力绕行保留原始被中断节点，修复后只能显式返回该位置。",
            },
            {
                "change_id": "change.report-container-routing",
                "change_kind": "reporting",
                "subject_ref": "report:graph-transition-container",
                "impact_zh": "章、特殊小节及其父级由服务端逐 trace 投影，CLI 不再猜测节点类型。",
            },
        ],
    }
