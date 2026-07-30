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
