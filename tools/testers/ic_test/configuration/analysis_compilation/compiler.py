"""Thin orchestration for flat-settings migration into the typed DAG."""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from tools.testers.ic_test.analysis_graph import ICAnalysisNode
from tools.testers.ic_test.core import ICCoreTest

from .portfolio import compile_portfolio_analyses
from .sequence import compile_sequence_analyses


def analysis_nodes_from_settings(
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
        *compile_sequence_analyses(settings, cores, primary_cores),
        *compile_portfolio_analyses(settings, cores),
    )
    return tuple(sorted(nodes, key=lambda item: item.node_id))


__all__ = ["analysis_nodes_from_settings"]
