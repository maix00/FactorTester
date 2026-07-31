from server.services.research_graph.branch.next_actions import node_next_actions
from server.services.research_graph.branch.report_requirements import (
    node_report_requirements,
)


def _graph():
    return {
        "report_policy": {"enforcement": "required"},
        "report_requirements": [
            {"report_requirement_id": "report.leave"},
            {"report_requirement_id": "report.enter"},
        ],
        "nodes": [
            {"node_id": "current", "node_report_refs": ["report.leave"]},
            {"node_id": "target", "entry_report_refs": ["report.enter"]},
        ],
        "edges": [],
    }


def test_edge_contract_includes_target_report_and_next_command():
    graph = _graph()
    node = {"node_id": "current"}
    edge = {
        "edge_id": "current__target",
        "to_node": "target",
        "report_requirement_refs": [],
    }
    requirements = node_report_requirements(
        graph=graph, node=node, edges=[edge], report_submission=None,
    )
    rows = requirements["candidate_edges"]["current__target"]
    assert [item["report_requirement_id"] for item in rows] == [
        "report.enter",
    ]
    actions = node_next_actions(
        instance_id="instance-1",
        branch_id="branch-1",
        context={"report_requirements": requirements},
        edges=[edge],
    )
    assert actions[0]["action_id"] == "edge.choose"
    assert actions[0]["command"].startswith(
        "factortester research-graph edge info "
    )
    assert actions[0]["then"].startswith(
        "factortester research-graph edge choose "
    )


def test_node_exit_report_blocks_edge_selection():
    graph = _graph()
    requirements = node_report_requirements(
        graph=graph, node=graph["nodes"][0], edges=[], report_submission=None,
    )
    actions = node_next_actions(
        instance_id="instance-1",
        branch_id="branch-1",
        context={"report_requirements": requirements},
        edges=[{"edge_id": "current__target"}],
    )
    assert actions[0]["action_id"] == "report.complete_on_exit"
    assert actions[0]["command"].startswith("factortester report add --profile ")
    assert actions[0]["then"].startswith(
        "factortester research-graph node info "
    )


def test_requirement_report_action_discloses_the_special_section_contract():
    requirements = {
        "enforcement": "required",
        "current_node": {"on_entry": [], "on_exit": [{
            "report_requirement_id": "report.requirement.data.coverage",
            "status": "missing",
        }]},
        "candidate_edges": {},
    }
    action = node_next_actions(
        instance_id="instance-1",
        branch_id="branch-1",
        context={"report_requirements": requirements},
        edges=[{"edge_id": "current__target"}],
    )[0]

    assert action["action_id"] == "report.complete_on_exit"
    assert "--kind special" in action["command"]
    assert "--display-kind obligation_requirement" in action["command"]
    assert "--obligation-requirement-id data.coverage" in action["command"]


def test_pending_entry_requirements_are_assessed_before_edge_selection():
    actions = node_next_actions(
        instance_id="instance-1",
        branch_id="branch-1",
        context={
            "entry_requirements": [
                {"requirement_id": "data.scope"},
            ],
            "report_requirements": {
                "enforcement": "required",
                "current_node": {"on_exit": []},
            },
        },
        edges=[{"edge_id": "current__target"}],
    )
    assert actions[0]["action_id"] == "entry.assess"
    assert actions[0]["then"].startswith(
        "factortester research-graph node advance "
    )
    assert "--entry-assessment-file" in actions[0]["then"]


def test_human_override_keeps_report_debt_visible_without_blocking_edge():
    requirements = {
        "enforcement": "required",
        "current_node": {"on_entry": [], "on_exit": [{
            "report_requirement_id": "report.requirement.data.coverage",
            "status": "missing",
        }]},
        "candidate_edges": {},
    }
    actions = node_next_actions(
        instance_id="instance-1",
        branch_id="branch-1",
        context={
            "report_requirements": requirements,
            "human_gate_override": {"enabled": True},
        },
        edges=[{"edge_id": "current__target"}],
    )

    assert [item["action_id"] for item in actions] == [
        "report.complete_on_exit", "edge.choose",
    ]
    assert actions[0]["blocking"] is False
    assert "--target-chapter-id" in actions[0]["command"]
    assert actions[0]["target_chapter_id"] == "<source-node-chapter-id>"
