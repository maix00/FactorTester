"""Evaluate candidate attachments solely from the registered graph contract."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .checks import (
    check_axes,
    check_core_inputs,
    check_count,
    check_cycle,
    check_kinds,
    check_origins,
    check_refs,
)
from .contracts import AnalysisAttachmentAssessment, AnalysisAttachmentIssue
from .grouping import normalize_target_refs, target_groups

if TYPE_CHECKING:
    from tools.testers.ic_test.analysis_graph import ICAnalysisGraph


def list_analysis_attachment_candidates(
    graph: ICAnalysisGraph,
    target_refs: tuple[str, ...],
    *,
    editing_node_id: str = "",
) -> tuple[AnalysisAttachmentAssessment, ...]:
    """Return every registered analysis with explicit compatibility reasons."""
    from ..registry import ic_analysis_graph_definition

    definitions = ic_analysis_graph_definition().analysis_types
    return tuple(
        assess_analysis_selection(
            graph, definition.key, target_refs,
            editing_node_id=editing_node_id,
        )
        for definition in sorted(definitions, key=lambda item: item.order)
    )


def assess_analysis_attachment(
    graph: ICAnalysisGraph,
    analysis_type: str,
    target_refs: tuple[str, ...],
    *,
    editing_node_id: str = "",
) -> AnalysisAttachmentAssessment:
    """Assess a proposed edge set without mutating or guessing UI state."""
    from ..registry import ic_analysis_graph_definition

    definition = ic_analysis_graph_definition().type_by_key(analysis_type)
    refs = tuple(str(ref or "").strip() for ref in target_refs)
    cores = {item.core_test_ref: item for item in graph.core_tests}
    nodes = {item.node_id: item for item in graph.analyses}
    issues: list[AnalysisAttachmentIssue] = []
    check_refs(refs, cores, nodes, issues)
    check_count(definition, refs, issues)
    known = tuple(ref for ref in refs if ref in cores or ref in nodes)
    check_origins(definition, known, cores, issues)
    check_kinds(definition, known, cores, nodes, issues)
    check_axes(definition, known, cores, issues)
    check_core_inputs(definition, known, cores, issues)
    check_cycle(editing_node_id, known, nodes, issues)
    return AnalysisAttachmentAssessment(analysis_type, refs, tuple(issues))


def assess_analysis_selection(
    graph: ICAnalysisGraph,
    analysis_type: str,
    target_refs: tuple[str, ...],
    *,
    editing_node_id: str = "",
) -> AnalysisAttachmentAssessment:
    """Assess a UI selection according to the type's map/combine contract."""
    from ..registry import ic_analysis_graph_definition

    definition = ic_analysis_graph_definition().type_by_key(analysis_type)
    refs, _ = normalize_target_refs(target_refs)
    groups = target_groups(definition.input_contract.mapping, refs)
    assessments = tuple(
        assess_analysis_attachment(
            graph,
            analysis_type,
            group,
            editing_node_id=editing_node_id,
        )
        for group in groups
    )
    issues = tuple(
        _selection_issue(issue, group, len(groups))
        for group, assessment in zip(groups, assessments, strict=True)
        for issue in assessment.issues
    )
    return AnalysisAttachmentAssessment(analysis_type, refs, issues)


def _selection_issue(
    issue: AnalysisAttachmentIssue,
    group: tuple[str, ...],
    group_count: int,
) -> AnalysisAttachmentIssue:
    if group_count == 1:
        return issue
    return AnalysisAttachmentIssue(
        issue.code,
        issue.message,
        {**issue.details, "target_refs": list(group)},
    )


__all__ = [
    "assess_analysis_attachment",
    "assess_analysis_selection",
    "list_analysis_attachment_candidates",
]
