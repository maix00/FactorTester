from __future__ import annotations

import pytest

from cli_anything.factortester_research.core.successor_graph import (
    build_successor_graph,
)
from server.services.research_graph.branch.report_coverage import (
    validate_report_submission,
)


def _parts(edge_id: str = "factor_semantics__validation_design"):
    graph = build_successor_graph()
    edge = next(item for item in graph["edges"] if item["edge_id"] == edge_id)
    source = next(
        item for item in graph["nodes"] if item["node_id"] == edge["from_node"]
    )
    target = next(
        item for item in graph["nodes"] if item["node_id"] == edge["to_node"]
    )
    assessments = [
        {
            "requirement_id": requirement_id,
            "coverage": {"obligation_refs": []},
        }
        for requirement_id in source["entry_requirement_refs"]
    ]
    return graph, source, edge, target, assessments


def _submission(graph, source, edge, target, assessments):
    reports = {
        item["report_requirement_id"]: item
        for item in graph["report_requirements"]
    }
    bindings = []
    for report_id in source["node_report_refs"]:
        subject = (
            f"requirement:{report_id.removeprefix('report.requirement.')}"
            if report_id.startswith("report.requirement.")
            else f"node:{source['node_id']}"
        )
        bindings.append((report_id, subject))
    bindings.extend(
        (report_id, f"graph-edge:{edge['edge_id']}")
        for report_id in edge["report_requirement_refs"]
    )
    bindings.extend(
        (report_id, f"node:{target['node_id']}")
        for report_id in target["entry_report_refs"]
    )
    return {
        "schema_version": 1,
        "fragment_hash": "a" * 64,
        "items": [
            {
                "report_requirement_id": report_id,
                "subject_ref": subject,
                "content_kind": reports[report_id]["subject_selector"]
                and graph["report_method_descriptors"][
                    reports[report_id]["method_ref"]
                ]["allowed_content"][0],
                "item_hash": "b" * 64,
            }
            for report_id, subject in bindings
        ],
    }


def test_successor_requires_exact_node_edge_and_target_entry_reports() -> None:
    graph, source, edge, target, assessments = _parts()
    submitted = _submission(graph, source, edge, target, assessments)

    value = validate_report_submission(
        graph=graph,
        source_node=source,
        edge=edge,
        target_node=target,
        entry_assessments=assessments,
        transition_evidence={},
        submitted=submitted,
    )

    assert value is not None
    assert len(value["items"]) == len(source["node_report_refs"]) + 2


def test_successor_report_coverage_lists_the_missing_binding() -> None:
    graph, source, edge, target, assessments = _parts()
    submitted = _submission(graph, source, edge, target, assessments)
    missing = submitted["items"].pop()

    with pytest.raises(ValueError, match=missing["report_requirement_id"]):
        validate_report_submission(
            graph=graph,
            source_node=source,
            edge=edge,
            target_node=target,
            entry_assessments=assessments,
            transition_evidence={},
            submitted=submitted,
        )


def test_v8_style_graph_does_not_require_new_report_submission() -> None:
    graph, source, edge, target, assessments = _parts()
    graph.pop("report_policy")

    assert validate_report_submission(
        graph=graph,
        source_node=source,
        edge=edge,
        target_node=target,
        entry_assessments=assessments,
        transition_evidence={},
        submitted=None,
    ) is None


def test_evidence_admission_requires_one_report_item_per_evidence() -> None:
    graph, source, edge, target, assessments = _parts(
        "trial_execution__result_audit"
    )
    submitted = _submission(graph, source, edge, target, assessments)
    submitted["items"].extend([
        {
            "report_requirement_id": "report.system.evidence_admission",
            "subject_ref": f"evidence:result-{index}",
            "content_kind": "sentence",
            "item_hash": str(index) * 64,
        }
        for index in (1, 2)
    ])

    value = validate_report_submission(
        graph=graph,
        source_node=source,
        edge=edge,
        target_node=target,
        entry_assessments=assessments,
        transition_evidence={
            "evidence_refs": ["evidence:result-1", "evidence:result-2"],
        },
        submitted=submitted,
    )

    assert value is not None
    assert sum(
        item["report_requirement_id"]
        == "report.system.evidence_admission"
        for item in value["items"]
    ) == 2
