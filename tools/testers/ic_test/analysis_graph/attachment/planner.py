"""Plan and apply one typed IC analysis attachment operation."""

from __future__ import annotations

from typing import Any, Mapping

from ..model import ICAnalysisGraph
from ..node_factory import analysis_node
from ..registry import ic_analysis_graph_definition
from .contracts import AnalysisAttachmentIssue, AnalysisAttachmentPlan
from .evaluator import assess_analysis_selection
from .grouping import normalize_target_refs, target_groups
from .parameters import freeze_analysis_parameters


def plan_analysis_attachment(
    graph: ICAnalysisGraph,
    analysis_type: str,
    target_refs: tuple[str, ...],
    *,
    parameters: Mapping[str, Any] | None = None,
) -> AnalysisAttachmentPlan:
    definition = ic_analysis_graph_definition().type_by_key(analysis_type)
    normalized_targets, duplicate_count = normalize_target_refs(target_refs)
    frozen, parameter_issues = freeze_analysis_parameters(definition, parameters)
    if not normalized_targets:
        parameter_issues = (
            AnalysisAttachmentIssue(
                "target_count",
                "所选目标数量不符合该分析的输入基数",
                {
                    "minimum": definition.input_contract.minimum_targets,
                    "maximum": definition.input_contract.maximum_targets,
                    "actual": 0,
                },
            ),
            *parameter_issues,
        )
    groups = target_groups(definition.input_contract.mapping, normalized_targets)
    assessment = assess_analysis_selection(
        graph, analysis_type, normalized_targets,
    )
    issues = assessment.issues + parameter_issues
    if issues:
        return AnalysisAttachmentPlan(
            analysis_type,
            definition.input_contract.mapping.value,
            normalized_targets,
            frozen,
            issues=issues,
            duplicate_target_count=duplicate_count,
        )
    candidates = tuple(
        analysis_node(analysis_type, group, frozen) for group in groups
    )
    existing_ids = {node.node_id for node in graph.analyses}
    return AnalysisAttachmentPlan(
        analysis_type,
        definition.input_contract.mapping.value,
        normalized_targets,
        frozen,
        nodes=tuple(node for node in candidates if node.node_id not in existing_ids),
        existing_node_ids=tuple(
            node.node_id for node in candidates if node.node_id in existing_ids
        ),
        duplicate_target_count=duplicate_count,
    )


def apply_analysis_attachment(
    graph: ICAnalysisGraph,
    plan: AnalysisAttachmentPlan,
) -> ICAnalysisGraph:
    if not plan.compatible:
        raise ValueError("cannot apply incompatible IC analysis attachment")
    nodes = {node.node_id: node for node in graph.analyses}
    nodes.update({node.node_id: node for node in plan.nodes})
    return ICAnalysisGraph(
        graph.core_tests,
        tuple(nodes[key] for key in sorted(nodes)),
    ).validate()
__all__ = ["apply_analysis_attachment", "plan_analysis_attachment"]
