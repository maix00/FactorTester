from __future__ import annotations

import json
import sqlite3

import pytest

from server.services.research_graph.branch.capability_detour import (
    project_trace_rows,
    project_transition,
    reconstruct_from_trace,
)


def test_repeated_capability_loops_keep_first_interrupted_node() -> None:
    projection = project_transition(
        None,
        edge_id="any_node__capability_gap",
        source_node="hypothesis_preregistration",
        target_node="capability_gap",
        trace_id="trace-gap-1",
    )
    state = projection["state"]
    assert state["resume_node"] == "hypothesis_preregistration"
    assert state["origin_trace_id"] == "trace-gap-1"

    for edge_id, source, target in (
        (
            "capability_gap__capability_resolution",
            "capability_gap",
            "capability_resolution",
        ),
        (
            "capability_resolution__capability_gap",
            "capability_resolution",
            "capability_gap",
        ),
        (
            "capability_gap__skill_review",
            "capability_gap",
            "skill_candidate_review",
        ),
        (
            "skill_review__capability_resolution",
            "skill_candidate_review",
            "capability_resolution",
        ),
    ):
        projection = project_transition(
            state,
            edge_id=edge_id,
            source_node=source,
            target_node=target,
            trace_id=f"trace-{edge_id}",
        )
        state = projection["state"]
        assert state["resume_node"] == "hypothesis_preregistration"

    with pytest.raises(ValueError, match="original interrupted node"):
        project_transition(
            state,
            edge_id="capability_resolution__resume_data_contract",
            source_node="capability_resolution",
            target_node="data_contract",
            trace_id="trace-wrong-resume",
        )

    recovered = project_transition(
        state,
        edge_id=(
            "capability_resolution__resume_hypothesis_preregistration"
        ),
        source_node="capability_resolution",
        target_node="hypothesis_preregistration",
        trace_id="trace-resumed",
    )
    assert recovered["state"] is None
    assert recovered["delta"]["status"] == "resumed"


def test_historical_v8_trace_reconstructs_hypothesis_resume() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE research_graph_trace (
            trace_id TEXT, instance_id TEXT, branch_id TEXT, edge_id TEXT,
            from_node TEXT, to_node TEXT, evidence_json TEXT, created_at REAL
        )
        """
    )
    rows = (
        ("t1", "any_node__capability_gap",
         "hypothesis_preregistration", "capability_gap"),
        ("t2", "capability_gap__capability_resolution",
         "capability_gap", "capability_resolution"),
        ("t3", "capability_resolution__capability_gap",
         "capability_resolution", "capability_gap"),
        ("t4", "capability_gap__capability_resolution",
         "capability_gap", "capability_resolution"),
        ("t5", "capability_resolution__capability_gap",
         "capability_resolution", "capability_gap"),
    )
    conn.executemany(
        """
        INSERT INTO research_graph_trace VALUES (
            ?, 'maxa-instance', 'maxa-branch', ?, ?, ?, '{}', ?
        )
        """,
        [(*row, index) for index, row in enumerate(rows, start=1)],
    )

    state = reconstruct_from_trace(
        conn,
        instance_id="maxa-instance",
        branch_id="maxa-branch",
    )

    assert state == {
        "schema_version": 1,
        "status": "pending",
        "episode_id": "capability-detour:t1",
        "resume_node": "hypothesis_preregistration",
        "origin_trace_id": "t1",
        "report_container": {
            "kind": "special",
            "anchor_node": "hypothesis_preregistration",
            "episode_ref": "capability-detour:t1",
        },
    }


def test_direct_capability_resolution_is_also_a_detour() -> None:
    opened = project_transition(
        None,
        edge_id="hypothesis__capability_resolution",
        source_node="hypothesis_preregistration",
        target_node="capability_resolution",
        trace_id="trace-direct-resolution",
    )

    assert opened["state"]["resume_node"] == "hypothesis_preregistration"
    assert opened["state"]["report_container"]["kind"] == "special"


def test_replay_uses_frozen_delta_for_direct_resolution_detour() -> None:
    report_container = {
        "kind": "special",
        "anchor_node": "hypothesis_preregistration",
        "episode_ref": "capability-detour:trace-direct",
    }
    replay = project_trace_rows([{
        "trace_id": "trace-direct",
        "edge_id": "hypothesis__capability_resolution",
        "from_node": "hypothesis_preregistration",
        "to_node": "capability_resolution",
        "evidence_json": json.dumps({
            "capability_detour_delta": {
                "schema_version": 1,
                "status": "opened",
                "episode_id": "capability-detour:trace-direct",
                "resume_node": "hypothesis_preregistration",
                "origin_trace_id": "trace-direct",
                "latest_trace_id": "trace-direct",
                "report_container": report_container,
            },
        }),
    }])

    assert replay["state"]["resume_node"] == "hypothesis_preregistration"
    assert replay["items"]["trace-direct"]["report_container"] == (
        report_container
    )
