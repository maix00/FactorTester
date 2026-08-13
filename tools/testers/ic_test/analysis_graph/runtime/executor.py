"""Execute requested IC analysis nodes through registered runtime adapters."""

from __future__ import annotations

from tools.testers.analysis_graph import AnalysisTypeDefinition
from ..model import ICAnalysisGraph, ICAnalysisNode
from ..registry import ic_analysis_graph_definition
from .adapters import builtin_runtime_adapters
from .contracts import ICAnalysisResultStore, ICAnalysisRuntimeAdapter


def execute_ic_analysis_nodes(
    graph: ICAnalysisGraph,
    requested_node_ids: tuple[str, ...],
    store: ICAnalysisResultStore,
) -> tuple[str, ...]:
    graph.validate()
    nodes = {node.node_id: node for node in graph.analyses}
    unknown = sorted(set(requested_node_ids) - set(nodes))
    if unknown:
        raise ValueError(f"unknown requested IC analysis nodes: {unknown}")
    adapters = builtin_runtime_adapters()
    executed: list[str] = []

    def execute(node: ICAnalysisNode) -> None:
        definition = ic_analysis_graph_definition().type_by_key(node.analysis_type)
        if store.contains(node.node_id, definition.output_kind):
            return
        for target_ref in node.target_refs:
            if target_ref in nodes:
                execute(nodes[target_ref])
        adapter = adapters.get(node.analysis_type)
        if adapter is None:
            raise ValueError(
                f"analysis type {node.analysis_type} has no runtime adapter"
            )
        _validate_adapter(definition, adapter)
        inputs = tuple({
            kind: store.require(target_ref, kind)
            for kind in adapter.input_kinds
        } for target_ref in node.target_refs)
        store.publish(
            node.node_id,
            adapter.output_kind,
            adapter.execute(inputs, node.parameters),
        )
        executed.append(node.node_id)

    for node_id in requested_node_ids:
        execute(nodes[node_id])
    return tuple(executed)


def _validate_adapter(
    definition: AnalysisTypeDefinition,
    adapter: ICAnalysisRuntimeAdapter,
) -> None:
    if adapter.output_kind != definition.output_kind:
        raise ValueError(
            f"runtime adapter output {adapter.output_kind} does not match "
            f"registered output {definition.output_kind}"
        )
    accepted = set(definition.input_contract.accepted_kinds)
    supplied = set(adapter.input_kinds)
    if not supplied or not supplied <= accepted:
        raise ValueError(
            f"runtime adapter inputs {sorted(supplied)} do not match "
            f"registered inputs {sorted(accepted)}"
        )


__all__ = ["execute_ic_analysis_nodes"]
