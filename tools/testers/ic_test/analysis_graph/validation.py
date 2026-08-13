"""Validation for normalized IC auxiliary-analysis graphs."""

from __future__ import annotations

from typing import TYPE_CHECKING

from tools.testers.analysis_graph import AnalysisTargetOrigin, AnalysisTypeDefinition
from tools.testers.ic_test.core import ICCoreTest

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
        _validate_node(node, definition, cores, nodes)


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
    node: ICAnalysisNode,
    definition: AnalysisTypeDefinition,
    cores: dict[str, ICCoreTest],
    nodes: dict[str, ICAnalysisNode],
) -> None:
    contract = definition.input_contract
    target_count = len(node.target_refs)
    if target_count < contract.minimum_targets or (
        contract.maximum_targets is not None
        and target_count > contract.maximum_targets
    ):
        raise ValueError(
            f"analysis {node.node_id} target count {target_count} violates "
            f"{contract.minimum_targets}..{contract.maximum_targets}"
        )

    origins = {
        AnalysisTargetOrigin.CORE if target in cores else AnalysisTargetOrigin.ANALYSIS
        for target in node.target_refs
    }
    unsupported = origins - set(contract.target_origins)
    if unsupported:
        if contract.target_origins == (AnalysisTargetOrigin.CORE,):
            raise ValueError(f"analysis {node.node_id} only accepts core targets")
        raise ValueError(f"analysis {node.node_id} has unsupported target origins")

    for target in node.target_refs:
        kinds = _target_output_kinds(target, cores, nodes)
        if set(contract.accepted_kinds).isdisjoint(kinds):
            raise ValueError(
                f"analysis {node.node_id} cannot consume target {target}: "
                f"expected {sorted(contract.accepted_kinds)}, got {sorted(kinds)}"
            )

    core_targets = [cores[target] for target in node.target_refs if target in cores]
    if core_targets:
        _validate_core_axes(node, contract.same_axes, contract.varying_axes, core_targets)
        missing_inputs = set(definition.required_core_inputs) - set.intersection(
            *(set(target.output_kinds) for target in core_targets)
        )
        if missing_inputs:
            raise ValueError(
                f"analysis {node.node_id} requires unavailable core inputs: "
                f"{sorted(missing_inputs)}"
            )

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
        raise ValueError(f"analysis {node.node_id} is missing parameters: {sorted(missing)}")


def _target_output_kinds(
    target: str,
    cores: dict[str, ICCoreTest],
    nodes: dict[str, ICAnalysisNode],
) -> frozenset[str]:
    if target in cores:
        return cores[target].output_kinds
    output = ic_analysis_graph_definition().type_by_key(
        nodes[target].analysis_type,
    ).output_kind
    return frozenset((output,))


def _validate_core_axes(
    node: ICAnalysisNode,
    same_axes: tuple[str, ...],
    varying_axes: tuple[str, ...],
    targets: list[ICCoreTest],
) -> None:
    for axis in same_axes:
        if len({item.axis_value(axis) for item in targets}) != 1:
            raise ValueError(f"analysis {node.node_id} requires the same {axis}")
    for axis in varying_axes:
        if len({item.axis_value(axis) for item in targets}) < 2:
            raise ValueError(f"analysis {node.node_id} requires varying {axis}")


__all__ = ["validate_ic_analysis_graph"]
