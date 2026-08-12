from tools.cli.commands.research_graph_local_report import (
    _server_owned_records,
)


def test_historical_continuation_resolves_to_one_logical_research() -> None:
    profile = {
        "research_records": [
            {"record_id": "sgccs", "agent_id": "research-maxa"},
            {"record_id": "momentum", "agent_id": "research-maxa"},
        ],
    }
    values = {
        "work-package:sgccs": {
            "branches": [{"branch_ref": "graph-branch:new:head"}],
            "tree": {
                "nodes": [
                    {"branch_ref": "graph-branch:old:historical"},
                    {"branch_ref": "graph-branch:new:head"},
                ],
            },
        },
        "work-package:momentum": {
            "branches": [{"branch_ref": "graph-branch:momentum:main"}],
            "tree": {"nodes": []},
        },
    }

    matches = _server_owned_records(
        profile=profile,
        branch_ref="graph-branch:old:historical",
        agent_id="research-maxa",
        loader=values.__getitem__,
    )

    assert [item["record_id"] for item in matches] == ["sgccs"]


def test_branch_resolution_never_guesses_from_branch_id_alone() -> None:
    profile = {
        "research_records": [
            {"record_id": "one", "agent_id": "research-maxa"},
        ],
    }

    matches = _server_owned_records(
        profile=profile,
        branch_ref="graph-branch:other:same-id",
        agent_id="research-maxa",
        loader=lambda _ref: {
            "branches": [{"branch_ref": "graph-branch:expected:same-id"}],
            "tree": {"nodes": []},
        },
    )

    assert matches == []
