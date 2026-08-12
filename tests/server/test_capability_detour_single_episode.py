from server.services.research_graph.branch.capability_detour import (
    project_trace_rows,
    project_transition,
)


def test_second_capability_gap_retains_one_episode() -> None:
    opened = project_transition(
        None,
        edge_id="hypothesis__capability_resolution",
        source_node="hypothesis_preregistration",
        target_node="capability_resolution",
        trace_id="outer",
    )
    repeated = project_transition(
        opened["state"],
        edge_id="any_node__capability_gap",
        source_node="capability_resolution",
        target_node="capability_gap",
        trace_id="later-gap",
    )

    assert repeated["delta"]["status"] == "retained"
    assert repeated["state"]["episode_id"] == "capability-detour:outer"
    assert repeated["state"]["resume_node"] == "hypothesis_preregistration"
    assert "frames" not in repeated["state"]


def test_legacy_direct_resolution_replays_as_one_detour_not_a_chapter() -> None:
    projected = project_trace_rows([{
        "trace_id": "open",
        "edge_id": "hypothesis__capability_resolution",
        "from_node": "hypothesis_preregistration",
        "to_node": "capability_resolution",
        "evidence_json": "{}",
    }, {
        "trace_id": "exit",
        "edge_id": "capability_resolution__data_contract",
        "from_node": "capability_resolution",
        "to_node": "data_contract",
        "evidence_json": "{}",
    }])

    opened = projected["items"]["open"]
    assert opened["report_container"] == {
        "kind": "special",
        "anchor_node": "hypothesis_preregistration",
        "episode_ref": "capability-detour:open",
    }
    assert opened["capability_detour"]["state_after"]["resume_node"] == (
        "hypothesis_preregistration"
    )
    assert projected["items"]["exit"]["source_report_container"]["kind"] == (
        "special"
    )
    assert projected["items"]["exit"]["capability_detour"][
        "state_after"
    ] is None
