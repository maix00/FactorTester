"""Partition a frozen IC graph into independently executable Jobs."""

from __future__ import annotations

from tools.testers.ic_test.configuration import CompiledICRunConfiguration

from .model import ICJobExecutionPlan


def plan_ic_jobs(
    configuration: CompiledICRunConfiguration,
) -> tuple[ICJobExecutionPlan, ...]:
    frozen = CompiledICRunConfiguration.from_dict(configuration.to_dict())
    graph = frozen.analysis_graph
    cores = {item.core_test_ref: item for item in graph.core_tests}
    nodes = {item.node_id: item for item in graph.analyses}
    node_scopes = _analysis_scopes(cores, nodes)
    ordered_nodes = _topological_node_ids(nodes)
    plans: list[ICJobExecutionPlan] = []
    for scope, core_refs in sorted(frozen.job_partitions.items()):
        mismatched = [
            ref for ref in core_refs if cores[ref].product_scope_ref != scope
        ]
        if mismatched:
            raise ValueError("partition scope does not match its frozen core tests")
        analyses = tuple(
            node_id for node_id in ordered_nodes if node_scopes[node_id] == scope
        )
        plans.append(ICJobExecutionPlan(
            configuration_ref=frozen.configuration_ref,
            product_scope_ref=scope,
            core_test_refs=core_refs,
            primary_core_refs=tuple(
                ref for ref in frozen.primary_core_refs if ref in core_refs
            ),
            analysis_node_ids=analyses,
            factor_subject_refs=frozen.factor_subject_refs,
            output_requests=frozen.output_requests,
        ))
    return tuple(plans)


def _analysis_scopes(cores: dict, nodes: dict) -> dict[str, str]:
    cache: dict[str, str] = {}

    def resolve(node_id: str) -> str:
        if node_id in cache:
            return cache[node_id]
        scopes = {
            cores[target].product_scope_ref if target in cores else resolve(target)
            for target in nodes[node_id].target_refs
        }
        if len(scopes) != 1:
            raise ValueError(
                f"analysis {node_id} spans product scopes; use a derived Job"
            )
        cache[node_id] = scopes.pop()
        return cache[node_id]

    for node_id in sorted(nodes):
        resolve(node_id)
    return cache


def _topological_node_ids(nodes: dict) -> tuple[str, ...]:
    ordered: list[str] = []
    visited: set[str] = set()

    def visit(node_id: str) -> None:
        if node_id in visited:
            return
        for target in nodes[node_id].target_refs:
            if target in nodes:
                visit(target)
        visited.add(node_id)
        ordered.append(node_id)

    for node_id in sorted(nodes):
        visit(node_id)
    return tuple(ordered)


__all__ = ["plan_ic_jobs"]
