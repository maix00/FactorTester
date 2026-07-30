from tools.cli.release.research_reporting.graph_adapter import (
    enrich_graph_packet,
)


def test_graph_packet_commands_use_public_factortester_groups() -> None:
    packet = enrich_graph_packet({
        "node": {"node_id": "hypothesis_preregistration"},
        "candidate_edges": [],
        "report_requirements": {"current_node": {}},
    })

    commands = packet["report_packet"]["document_commands"]
    assert commands[0].startswith("factortester research-graph node info ")
    assert commands[1].startswith("factortester research-graph edge info ")
    assert commands[-1].startswith(
        "factortester research-graph node advance "
    )
    assert all("factortester node " not in command for command in commands)
    assert all("factortester edge " not in command for command in commands)


def test_graph_packet_keeps_detailed_edge_requirement_contract() -> None:
    packet = enrich_graph_packet({
        "node": {"node_id": "capability_resolution"},
        "candidate_edges": [{
            "edge_id": "capability_resolution__resume",
            "report_requirement_refs": ["report.edge.resume"],
        }],
        "report_requirements": {
            "current_node": {},
            "candidate_edges": {
                "capability_resolution__resume": [{
                    "report_requirement_id": "report.edge.resume",
                    "subject_ref": "graph-edge:capability_resolution__resume",
                    "allowed_content": ["sentence"],
                    "phase": "edge",
                    "status": "missing",
                }],
            },
        },
    })

    task = next(
        item for item in packet["report_packet"]["required_tasks"]
        if item["task_ref"] == "report.edge.resume"
    )
    assert task["subject_ref"] == (
        "graph-edge:capability_resolution__resume"
    )
    assert task["allowed_content"] == ["sentence"]
