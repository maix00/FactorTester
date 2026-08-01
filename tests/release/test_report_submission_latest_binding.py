from __future__ import annotations

import pytest

from tools.cli.release.research_reporting.authoring.submission import (
    build_report_submission,
    select_report_submission,
)
from tools.cli.commands.research_graph_node_advance import prepare_evidence


def _component(component_id: str, created_at: float) -> dict[str, object]:
    return {
        "component_id": component_id,
        "title": component_id,
        "body": "",
        "content": None,
        "display_kind": "",
        "created_at": created_at,
    }


def _binding(component_id: str, item_hash: str) -> dict[str, object]:
    return {
        "component_id": component_id,
        "kind": "report_requirement",
        "target_ref": "report.requirement.material_question",
        "data": {
            "subject_ref": "requirement:material_question",
            "content_kind": "list",
            "report_item_ref": f"report-item:sha256:{item_hash}",
        },
    }


def test_report_submission_uses_latest_historical_binding_per_subject() -> None:
    snapshot = {
        "components": [
            _component("gap-assessment", 1.0),
            _component("resolution-assessment", 2.0),
        ],
        "bindings": [
            _binding("gap-assessment", "a" * 64),
            _binding("resolution-assessment", "b" * 64),
        ],
    }

    submission = build_report_submission(snapshot)

    assert submission["items"] == [{
        "report_requirement_id": "report.requirement.material_question",
        "subject_ref": "requirement:material_question",
        "content_kind": "list",
        "item_hash": "b" * 64,
    }]


def test_report_submission_rejects_ambiguous_latest_binding() -> None:
    snapshot = {
        "components": [
            _component("assessment-a", 2.0),
            _component("assessment-b", 2.0),
        ],
        "bindings": [
            _binding("assessment-a", "a" * 64),
            _binding("assessment-b", "b" * 64),
        ],
    }

    with pytest.raises(
        ValueError,
        match="report submission has ambiguous latest bindings",
    ):
        build_report_submission(snapshot)


def test_report_submission_selects_only_current_transition_requirements() -> None:
    submission = {
        "schema_version": 1,
        "fragment_hash": "stale-full-report-hash",
        "items": [
            {
                "report_requirement_id": "report.node.previous.action",
                "subject_ref": "node:previous",
                "content_kind": "sentence",
                "item_hash": "a" * 64,
            },
            {
                "report_requirement_id": "report.node.current.action",
                "subject_ref": "node:current",
                "content_kind": "sentence",
                "item_hash": "b" * 64,
            },
            {
                "report_requirement_id": "report.edge.selected",
                "subject_ref": "graph-edge:selected",
                "content_kind": "sentence",
                "item_hash": "c" * 64,
            },
        ],
    }

    selected = select_report_submission(
        submission,
        requirement_ids={
            "report.node.current.action",
            "report.edge.selected",
        },
    )

    assert [
        item["report_requirement_id"] for item in selected["items"]
    ] == [
        "report.edge.selected",
        "report.node.current.action",
    ]
    assert selected["fragment_hash"] != "stale-full-report-hash"


def test_current_report_replaces_stale_assessment_report_projection(
    tmp_path,
) -> None:
    evidence_file = tmp_path / "evidence.json"
    evidence_file.write_text("{}", encoding="utf-8")
    assessment_file = tmp_path / "assessment.json"
    assessment_file.write_text(
        """{
          "entry_requirement_assessments": [],
          "report_submission": {
            "schema_version": 1,
            "fragment_hash": "stale",
            "items": [{
              "report_requirement_id": "report.requirement.data.depth",
              "subject_ref": "obligation:data-contract",
              "content_kind": "list",
              "item_hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
            }]
          }
        }""",
        encoding="utf-8",
    )
    current = {
        "schema_version": 1,
        "fragment_hash": "current",
        "items": [{
            "report_requirement_id": "report.requirement.data.depth",
            "subject_ref": "obligation:data-contract",
            "content_kind": "list",
            "item_hash": "b" * 64,
        }],
    }

    prepared = prepare_evidence(
        evidence_file=evidence_file,
        entry_assessment_file=assessment_file,
        target_capability_resolution_file=None,
        report_submission=current,
    )

    assert prepared["report_submission"] == current
