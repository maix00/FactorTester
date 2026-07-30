from __future__ import annotations

import pytest

from cli_anything.factortester_research.core.successor_graph import (
    build_successor_graph,
)
from server.services.research_graph.branch.report_coverage import (
    expected_report_bindings,
    validate_report_submission,
)
from server.services.research_graph.branch.report_requirements import (
    node_report_requirements,
)
from tools.cli.release.research_reporting.report_items import (
    report_fragment_hash,
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
    value = {
        "schema_version": 1,
        "fragment_hash": "",
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
    value["fragment_hash"] = report_fragment_hash(value["items"])
    return value


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


def test_capability_failure_edge_does_not_require_completed_source_exit() -> None:
    graph, source, edge, target, assessments = _parts(
        "data_contract__capability_gap"
    )

    bindings = expected_report_bindings(
        graph=graph,
        source_node=source,
        edge=edge,
        target_node=target,
        entry_assessments=assessments,
        transition_evidence={},
    )
    actual = {
        (item["report_requirement_id"], item["subject_ref"])
        for item in bindings
    }

    assert all(
        subject != f"node:{source['node_id']}"
        for _requirement, subject in actual
    )
    assert {
        (
            "report.edge.data_contract__capability_gap",
            "graph-edge:data_contract__capability_gap",
        ),
        (
            "report.node.capability_gap.entry",
            "node:capability_gap",
        ),
    } <= actual


def test_current_node_dynamic_requirement_uses_registered_subject() -> None:
    graph, source, edge, _target, assessments = _parts()
    submission = _submission(graph, source, edge, _target, assessments)

    value = node_report_requirements(
        graph=graph,
        node=source,
        edges=[edge],
        report_submission=submission,
    )

    dynamic = [
        item for item in value["current_node"]["on_exit"]
        if item["report_requirement_id"].startswith("report.requirement.")
    ]
    assert dynamic
    assert all(item["status"] == "satisfied" for item in dynamic)
    assert all(
        item["subject_ref"].startswith("requirement:")
        for item in dynamic
    )


def test_dense_v9_report_index_is_not_limited_by_agent_packet_budget() -> None:
    graph, source, edge, target, assessments = _parts(
        "validation_design__trial_execution"
    )
    for index, assessment in enumerate(assessments):
        assessment["coverage"]["obligation_refs"] = [
            f"obligation:dense-{index}-a",
            f"obligation:dense-{index}-b",
        ]
    bindings = expected_report_bindings(
        graph=graph,
        source_node=source,
        edge=edge,
        target_node=target,
        entry_assessments=assessments,
        transition_evidence={},
    )
    submitted = {
        "schema_version": 1,
        "fragment_hash": "",
        "items": [
            {
                "report_requirement_id": item["report_requirement_id"],
                "subject_ref": item["subject_ref"],
                "content_kind": item["allowed_content"][0],
                "item_hash": "b" * 64,
            }
            for item in bindings
        ],
    }
    submitted["fragment_hash"] = report_fragment_hash(submitted["items"])

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
    assert len(value["items"]) > 20


def test_expected_bindings_are_the_same_contract_used_by_validation() -> None:
    graph, source, edge, target, assessments = _parts()
    submitted = _submission(graph, source, edge, target, assessments)

    expected = expected_report_bindings(
        graph=graph,
        source_node=source,
        edge=edge,
        target_node=target,
        entry_assessments=assessments,
        transition_evidence={},
    )

    assert {
        (item["report_requirement_id"], item["subject_ref"])
        for item in expected
    } == {
        (item["report_requirement_id"], item["subject_ref"])
        for item in submitted["items"]
    }
    assert all(item["allowed_content"] for item in expected)


def test_successor_report_coverage_lists_the_missing_binding() -> None:
    graph, source, edge, target, assessments = _parts()
    submitted = _submission(graph, source, edge, target, assessments)
    missing = submitted["items"].pop()
    submitted["fragment_hash"] = report_fragment_hash(submitted["items"])

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
    submitted["fragment_hash"] = report_fragment_hash(submitted["items"])

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
