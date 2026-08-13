"""Validation for normalized IC auxiliary-analysis graphs."""

from __future__ import annotations

from typing import TYPE_CHECKING

from tools.testers.analysis_graph import AnalysisTypeDefinition
from tools.testers.ic_test.core import ICCoreTest

from .attachment import assess_analysis_attachment
from .attachment.parameters import freeze_analysis_parameters
from .registry import ic_analysis_graph_definition

if TYPE_CHECKING:
    from .model import ICAnalysisGraph, ICAnalysisNode


def validate_ic_analysis_graph(graph: ICAnalysisGraph) -> None:
    cores = {item.core_test_ref: item for item in graph.core_tests}
    if len(cores) != len(graph.core_tests):
        raise ValueError("IC analysis graph contains duplicate core tests")
    nodes = {item.node_id: item for item in graph.analyses}
    if len(nodes) != len(graph.analyses):
        raise ValueError("IC analysis graph contains duplicate analysis node ids")
    collision = set(cores) & set(nodes)
    if collision:
        raise ValueError(f"analysis node id collides with a core test ref: {collision}")

    _validate_dependencies(nodes, cores)
    definitions = ic_analysis_graph_definition()
    for node in graph.analyses:
        definition = definitions.type_by_key(node.analysis_type)
        _validate_node(graph, node, definition)


def _validate_dependencies(
    nodes: dict[str, ICAnalysisNode],
    cores: dict[str, ICCoreTest],
) -> None:
    unknown = {
        target
        for node in nodes.values()
        for target in node.target_refs
        if target not in nodes and target not in cores
    }
    if unknown:
        raise ValueError(f"IC analysis graph contains unknown targets: {sorted(unknown)}")

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node_id: str) -> None:
        if node_id in visited:
            return
        if node_id in visiting:
            raise ValueError("IC analysis graph contains a cycle")
        visiting.add(node_id)
        for target in nodes[node_id].target_refs:
            if target in nodes:
                visit(target)
        visiting.remove(node_id)
        visited.add(node_id)

    for node_id in nodes:
        visit(node_id)


def _validate_node(
    graph: ICAnalysisGraph,
    node: ICAnalysisNode,
    definition: AnalysisTypeDefinition,
) -> None:
    assessment = assess_analysis_attachment(
        graph,
        node.analysis_type,
        node.target_refs,
    )
    if assessment.issues:
        reasons = "; ".join(
            f"{issue.code}: {issue.message}" for issue in assessment.issues
        )
        raise ValueError(f"analysis {node.node_id} is incompatible: {reasons}")

    allowed_parameters = {item.key for item in definition.parameters}
    unknown_parameters = set(node.parameters) - allowed_parameters
    if unknown_parameters:
        raise ValueError(
            f"analysis {node.node_id} has unknown parameters: "
            f"{sorted(unknown_parameters)}"
        )
    missing = {
        item.key
        for item in definition.parameters
        if item.required and item.key not in node.parameters
    }
    if missing:
        raise ValueError(
            f"analysis {node.node_id} is missing parameters: {sorted(missing)}"
        )
    _, parameter_issues = freeze_analysis_parameters(definition, node.parameters)
    if parameter_issues:
        reasons = "; ".join(
            f"{issue.code}: {issue.message}" for issue in parameter_issues
        )
        raise ValueError(f"analysis {node.node_id} is incompatible: {reasons}")


__all__ = ["validate_ic_analysis_graph"]
