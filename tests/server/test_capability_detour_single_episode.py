from server.services.research_graph.branch.capability_detour import (
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
