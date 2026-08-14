"""Orchestrate one-way flat-settings migration into the typed DAG."""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from tools.testers.ic_test.analysis_graph import ICAnalysisNode
from tools.testers.ic_test.core import ICCoreTest

from .portfolio import migrate_portfolio_analysis_nodes
from .sequence import migrate_sequence_analysis_nodes


def migrate_analysis_nodes(
    settings: Mapping[str, Any],
    core_tests: Iterable[ICCoreTest],
    *,
    primary_core_refs: Iterable[str] = (),
) -> tuple[ICAnalysisNode, ...]:
    cores = tuple(core_tests)
    primary_refs = frozenset(primary_core_refs)
    primary_cores = tuple(
        core for core in cores if core.core_test_ref in primary_refs
    )
    nodes = (
        *migrate_sequence_analysis_nodes(settings, cores, primary_cores),
        *migrate_portfolio_analysis_nodes(settings, cores),
    )
    return tuple(sorted(nodes, key=lambda item: item.node_id))


__all__ = ["migrate_analysis_nodes"]
