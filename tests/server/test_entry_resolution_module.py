"""Public Entry Resolution Module interface."""

from cli_anything.factortester_research.core.successor_graph import (
    build_successor_graph,
)
from server.services.research_graph.branch.entry_resolution import (
    assess_departure,
    project_arrival,
)
from tests.server.test_entry_requirement_gate import (
    REQUIREMENT_ID,
    _checkpoint,
    _mapped_assessment,
    _node,
)


def test_public_module_resolves_departure_and_reuses_same_node_arrival() -> None:
    graph = build_successor_graph()
    node = _node(graph)
    node["entry_requirement_refs"] = [REQUIREMENT_ID]
    attempt = assess_departure(
        graph=graph,
        node=node,
        checkpoint=_checkpoint(),
        current_frame={},
        current_node="data_contract",
        target_node="data_contract",
        submitted=[_mapped_assessment()],
    )

    outcome = project_arrival(
        attempt=attempt,
        graph=graph,
        checkpoint=_checkpoint(),
        scope={"product_group": "CNFutures", "workspace_id": "workspace-1"},
        trace_ref="trace:entry-1",
    )

    assert outcome["assessments"][0]["requirement_id"] == REQUIREMENT_ID
    assert outcome["frame"]["status"] == "resolved"
    assert outcome["frame"]["reused_requirement_ids"] == [REQUIREMENT_ID]
    assert outcome["trace_delta"]["assessed_requirement_ids"] == [
        REQUIREMENT_ID
    ]
