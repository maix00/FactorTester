from __future__ import annotations

from tools.data.sqlite.db import connect_sqlite

from tests.server.test_profile_research_projection import _seed, _service


def test_timeline_projects_one_capability_episode_and_resumed_container(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "report-placement.sqlite"
    _seed(path, branch_count=1, trace_count=1)
    transitions = [
        ("trace-1", "to-prereg", "hypothesis", "hypothesis_preregistration"),
        (
            "trace-2", "missing-capability",
            "hypothesis_preregistration", "capability_gap",
        ),
        (
            "trace-3", "inspect-capability",
            "capability_gap", "capability_resolution",
        ),
        (
            "trace-4", "legacy-resume",
            "capability_resolution", "hypothesis_preregistration",
        ),
        (
            "trace-5", "to-plan",
            "hypothesis_preregistration", "trial_plan",
        ),
    ]
    with connect_sqlite(path) as conn:
        conn.execute("DELETE FROM research_graph_trace")
        conn.executemany(
            """
            INSERT INTO research_graph_trace (
                trace_id, instance_id, branch_id, edge_id,
                from_node, to_node, evidence_json, telemetry_json,
                actor, created_at
            ) VALUES (?, 'instance-a', 'branch-0000', ?, ?, ?, '{}', '{}',
                      'research-agent', ?)
            """,
            [
                (*transition, 1_000.0 + index)
                for index, transition in enumerate(transitions)
            ],
        )
        conn.execute(
            """
            UPDATE research_graph_branches
            SET current_node='trial_plan', latest_trace_id='trace-5'
            WHERE instance_id='instance-a' AND branch_id='branch-0000'
            """
        )

    service = _service(path, monkeypatch)
    first = service.list_timeline(
        owner="alice",
        research_ref="graph-branch:instance-a:branch-0000",
        limit=2,
    )
    second = service.list_timeline(
        owner="alice",
        research_ref="graph-branch:instance-a:branch-0000",
        limit=3,
        after=first["next_cursor"],
    )
    by_trace = {
        item["step_ref"].removeprefix("trace:"): item
        for item in [*first["items"], *second["items"]]
    }

    assert by_trace["trace-1"]["report_container"] == {
        "kind": "chapter",
        "anchor_node": "hypothesis_preregistration",
    }
    episode = "capability-detour:trace-2"
    for trace_id in ("trace-2", "trace-3", "trace-4"):
        assert by_trace[trace_id]["report_container"] == {
            "kind": "special",
            "anchor_node": "hypothesis_preregistration",
            "episode_ref": episode,
        }
    assert by_trace["trace-4"]["capability_detour"]["delta"]["status"] == (
        "resumed"
    )
    assert by_trace["trace-4"]["capability_detour"]["state_after"] is None
    assert by_trace["trace-5"]["source_report_container"] == {
        "kind": "chapter",
        "anchor_node": "hypothesis_preregistration",
    }
    assert by_trace["trace-5"]["report_container"] == {
        "kind": "chapter",
        "anchor_node": "trial_plan",
    }


def test_legacy_timeline_replays_main_resolution_and_non_resume_exit(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "legacy-resolution-placement.sqlite"
    _seed(path, branch_count=1, trace_count=1)
    transitions = [
        (
            "trace-1", "hypothesis__capability_resolution",
            "hypothesis_preregistration", "capability_resolution",
        ),
        (
            "trace-2", "capability_resolution__data_contract",
            "capability_resolution", "data_contract",
        ),
        (
            "trace-3", "any_node__capability_gap",
            "validation_design", "capability_gap",
        ),
        (
            "trace-4", "capability_gap__capability_resolution",
            "capability_gap", "capability_resolution",
        ),
        (
            "trace-5", "capability_resolution__data_contract",
            "capability_resolution", "data_contract",
        ),
    ]
    with connect_sqlite(path) as conn:
        conn.execute("DELETE FROM research_graph_trace")
        conn.executemany(
            """
            INSERT INTO research_graph_trace (
                trace_id, instance_id, branch_id, edge_id,
                from_node, to_node, evidence_json, telemetry_json,
                actor, created_at
            ) VALUES (?, 'instance-a', 'branch-0000', ?, ?, ?, '{}', '{}',
                      'research-agent', ?)
            """,
            [
                (*transition, 1_000.0 + index)
                for index, transition in enumerate(transitions)
            ],
        )
        conn.execute(
            """
            UPDATE research_graph_branches
            SET current_node='data_contract', latest_trace_id='trace-5'
            WHERE instance_id='instance-a' AND branch_id='branch-0000'
            """
        )

    timeline = _service(path, monkeypatch).list_timeline(
        owner="alice",
        research_ref="graph-branch:instance-a:branch-0000",
    )
    by_trace = {
        item["step_ref"].removeprefix("trace:"): item
        for item in timeline["items"]
    }

    first_episode = "capability-detour:trace-1"
    assert by_trace["trace-1"]["capability_detour"]["state_after"][
        "resume_node"
    ] == "hypothesis_preregistration"
    assert by_trace["trace-1"]["report_container"] == {
        "kind": "special",
        "anchor_node": "hypothesis_preregistration",
        "episode_ref": first_episode,
    }
    assert by_trace["trace-2"]["source_report_container"] == {
        "kind": "special",
        "anchor_node": "hypothesis_preregistration",
        "episode_ref": first_episode,
    }
    assert by_trace["trace-2"]["capability_detour"]["delta"]["status"] == (
        "legacy_exited"
    )
    assert by_trace["trace-2"]["capability_detour"]["state_after"] is None
    episode = "capability-detour:trace-3"
    for trace_id in ("trace-3", "trace-4", "trace-5"):
        assert by_trace[trace_id]["report_container"] == {
            "kind": "special",
            "anchor_node": "validation_design",
            "episode_ref": episode,
        }
    assert by_trace["trace-5"]["capability_detour"]["delta"]["status"] == (
        "legacy_exited"
    )
    assert by_trace["trace-5"]["capability_detour"]["delta"][
        "exit_node"
    ] == "data_contract"
    assert by_trace["trace-5"]["capability_detour"]["state_after"] is None
