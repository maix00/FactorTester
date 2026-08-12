from __future__ import annotations

from tools.cli.commands.research_graph_local_report_projection import (
    apply_local_report_coverage,
)


def test_local_report_coverage_replaces_missing_status_without_server_write() -> None:
    packet = {
        "report_requirements": {
            "enforcement": "required",
            "current_node": {
                "on_entry": [],
                "on_exit": [
                    {
                        "report_requirement_id": (
                            "report.requirement.data.granularity_and_depth"
                        ),
                        "status": "missing",
                    },
                    {
                        "report_requirement_id": "report.node.data.action",
                        "status": "missing",
                    },
                ],
            },
            "candidate_edges": {},
        }
    }
    submission = {
        "schema_version": 1,
        "fragment_hash": "f" * 64,
        "items": [
            {
                "report_requirement_id": (
                    "report.requirement.data.granularity_and_depth"
                ),
                "subject_ref": "obligation:data-contract",
                "content_kind": "list",
                "item_hash": "a" * 64,
            },
            {
                "report_requirement_id": "report.node.data.action",
                "subject_ref": "node:data",
                "content_kind": "list",
                "item_hash": "b" * 64,
            },
        ],
    }

    projected = apply_local_report_coverage(packet, submission)

    assert [
        item["status"]
        for item in projected["report_requirements"]["current_node"]["on_exit"]
    ] == ["satisfied", "satisfied"]
    assert projected["local_report_projection"] == {
        "status": "pending_server_checkpoint",
        "fragment_hash": "f" * 64,
        "covered_requirement_count": 2,
    }
    assert packet["report_requirements"]["current_node"]["on_exit"][0][
        "status"
    ] == "missing"
