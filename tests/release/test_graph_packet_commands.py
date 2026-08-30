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
    assert commands[0].startswith("factortester research graphs node info ")
    assert commands[1].startswith("factortester research graphs edge info ")
    assert commands[-1].startswith(
        "factortester research graphs node advance "
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
    assert "--title" not in task["next_command"]
    assert task["title_policy"] == (
        "content components may omit --title; structure nodes require a "
        "meaningful subject title"
    )


def test_graph_packet_routes_obligation_requirement_to_bound_special() -> None:
    packet = enrich_graph_packet({
        "node": {"node_id": "data_contract"},
        "candidate_edges": [],
        "report_requirements": {
            "current_node": {
                "on_entry": [{
                    "report_requirement_id": "report.requirement.data.coverage",
                    "title_zh": "数据覆盖检查",
                    "subject_ref": "requirement:data.coverage",
                    "allowed_content": ["list"],
                    "status": "missing",
                }],
            },
        },
    })

    task = packet["report_packet"]["required_tasks"][0]
    assert task["obligation_requirement_id"] == "data.coverage"
    assert task["title_zh"] == "数据覆盖检查"
    assert "--kind special" in task["next_command"]
    assert "--title '数据覆盖检查'" in task["next_command"]
    assert "--display-kind obligation_requirement" in task["next_command"]
    assert (
        "--obligation-requirement-id data.coverage"
        in task["next_command"]
    )
    assert "--report-requirement-id report.requirement.data.coverage" in (
        task["next_command"]
    )
    assert "--report-subject-ref requirement:data.coverage" in (
        task["next_command"]
    )


def test_graph_packet_discloses_the_shared_component_title_policy() -> None:
    packet = enrich_graph_packet({
        "node": {"node_id": "hypothesis_preregistration"},
        "candidate_edges": [],
        "report_requirements": {"current_node": {}},
    })

    assert packet["report_packet"]["component_title_policy"] == {
        "structure_kinds": ["chapter", "section", "subsection", "special"],
        "content_kinds": [
            "entry", "list", "table", "image", "code", "math", "result",
        ],
        "rule": (
            "structure nodes require a meaningful subject title; content "
            "components may omit title"
        ),
    }
