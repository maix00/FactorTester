from __future__ import annotations

from cli_anything.factortester_research.core.successor_graph import (
    build_successor_graph,
)
from server.services.research_graph.branch.capability_detour import (
    filter_available_edges,
)


def test_v10_exposes_only_the_matching_resume_edge() -> None:
    graph = build_successor_graph()
    state = {
        "schema_version": 1,
        "status": "pending",
        "episode_id": "capability-detour:trace-gap-1",
        "resume_node": "hypothesis_preregistration",
        "origin_trace_id": "trace-gap-1",
        "report_container": {
            "kind": "special",
            "anchor_node": "hypothesis_preregistration",
            "episode_ref": "capability-detour:trace-gap-1",
        },
    }

    available = filter_available_edges(
        graph["edges"],
        current_node="capability_resolution",
        state=state,
    )
    recovery = [
        edge for edge in available
        if edge["edge_id"].startswith("capability_resolution__resume_")
    ]

    assert [edge["to_node"] for edge in recovery] == [
        "hypothesis_preregistration"
    ]
    assert "capability_resolution__data_contract" not in {
        edge["edge_id"] for edge in available
    }
    assert recovery[0]["guard"] == {
        "capability_detour_resume_node": "hypothesis_preregistration"
    }
def test_v10_detour_nodes_declare_special_report_placement() -> None:
    graph = build_successor_graph()
    nodes = {node["node_id"]: node for node in graph["nodes"]}

    for node_id in (
        "capability_gap",
        "capability_resolution",
        "skill_candidate_review",
        "code_improvement_required",
    ):
        assert nodes[node_id]["report_container_policy"] == {
            "kind": "special",
            "anchor_from": "capability_detour.resume_node",
            "episode_from": "capability_detour.episode_id",
        }
    assert nodes["hypothesis_preregistration"][
        "report_container_policy"
    ] == {"kind": "chapter", "anchor_from": "node.node_id"}
