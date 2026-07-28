from __future__ import annotations

import json

from click.testing import CliRunner

from tools.cli.app import cli
from tools.cli.commands import research_graph_navigation as navigation


class _Client:
    def __init__(self) -> None:
        self.advance_calls = []
        self.advance_response = None

    def get_research_graph_node_info(self, instance_id, branch_id):
        return {
            "node": {"node_id": "validation_design"},
            "next_actions": [{
                "action_id": "edge.choose",
                "command": "factortester edge info ...",
            }],
        }

    def get_research_graph_edge_info(self, instance_id, branch_id, edge_id):
        return {
            "node": {"node_id": "validation_design"},
            "edge": {"edge_id": edge_id},
            "report_requirements": [],
            "next_actions": [{
                "action_id": "node.advance",
                "command": "factortester node advance ...",
            }],
        }

    def advance_research_graph_node(
        self, instance_id, branch_id, *, edge_id, evidence,
        acting_profile_ref="",
    ):
        self.advance_calls.append((instance_id, branch_id, edge_id, evidence))
        return self.advance_response or {"current_node": "result_audit"}

    def get_research_graph_node_info(self, instance_id, branch_id):
        return {"next_actions": [{"action_id": "edge.choose"}]}


def test_node_info_exposes_next_action(monkeypatch):
    client = _Client()
    monkeypatch.setattr(navigation, "client_from_config", lambda: client)

    result = CliRunner().invoke(cli, [
        "research-graph", "node", "info", "instance-1", "branch-1",
    ])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["next_action"]["action_id"] == "edge.choose"


def test_edge_choose_is_read_only_and_returns_next_action(monkeypatch, tmp_path):
    client = _Client()
    monkeypatch.setattr(navigation, "client_from_config", lambda: client)
    output = tmp_path / "edge-choice.json"

    result = CliRunner().invoke(cli, [
        "research-graph", "edge", "choose", "instance-1", "branch-1",
        "edge-1", "--output", str(output),
    ])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["state_changed"] is False
    assert payload["selected_edge_id"] == "edge-1"
    assert json.loads(output.read_text()) == payload | {"output": str(output)}


def test_node_advance_returns_post_transition_next_action(monkeypatch, tmp_path):
    client = _Client()
    monkeypatch.setattr(navigation, "client_from_config", lambda: client)
    evidence = tmp_path / "evidence.json"
    evidence.write_text('{"ready": true}', encoding="utf-8")

    result = CliRunner().invoke(cli, [
        "research-graph", "node", "advance", "instance-1", "branch-1",
        "--edge-id", "edge-1", "--evidence-file", str(evidence),
    ])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["doctor"]["operation"] == "node.advance"
    assert payload["next"]["next_actions"][0]["action_id"] == "edge.choose"
    assert client.advance_calls == [
        ("instance-1", "branch-1", "edge-1", {"ready": True}),
    ]


def test_node_advance_doctor_blocks_missing_dynamic_report(
    monkeypatch, tmp_path,
):
    client = _Client()
    monkeypatch.setattr(navigation, "client_from_config", lambda: client)
    client.get_research_graph_node_info = lambda instance_id, branch_id: {
        "node": {"node_id": "validation_design"},
        "report_requirements": {
            "enforcement": "required",
            "current_node": {
                "on_exit": [{
                    "report_requirement_id": "report.requirement.sample",
                    "status": "missing",
                    "subject_ref": "",
                }],
            },
        },
    }
    evidence = tmp_path / "evidence.json"
    evidence.write_text('{"ready": true}', encoding="utf-8")

    result = CliRunner().invoke(cli, [
        "research-graph", "node", "advance", "instance-1", "branch-1",
        "--edge-id", "edge-1", "--evidence-file", str(evidence),
    ])

    assert result.exit_code != 0
    assert "report.requirement.sample" in result.output
    assert client.advance_calls == []


def test_node_advance_carries_entry_assessment_projection(
    monkeypatch, tmp_path,
):
    client = _Client()
    monkeypatch.setattr(navigation, "client_from_config", lambda: client)
    evidence = tmp_path / "evidence.json"
    evidence.write_text('{"ready": true}', encoding="utf-8")
    assessment = tmp_path / "assessment.json"
    assessment.write_text(json.dumps({
        "entry_requirement_assessments": [{
            "requirement_id": "data.scope",
            "entry_effect": {"status": "pass"},
        }],
    }), encoding="utf-8")

    result = CliRunner().invoke(cli, [
        "research-graph", "node", "advance", "instance-1", "branch-1",
        "--edge-id", "edge-1", "--evidence-file", str(evidence),
        "--entry-assessment-file", str(assessment),
    ])

    assert result.exit_code == 0, result.output
    assert client.advance_calls[0][3]["entry_requirement_assessments"] == [{
        "requirement_id": "data.scope",
        "entry_effect": {"status": "pass"},
    }]


def test_node_advance_keeps_local_report_publication(
    monkeypatch,
    tmp_path,
):
    client = _Client()
    carrier = {
        "schema_version": 1,
        "checkpoint_ref": "trace:checkpoint-1",
    }
    client.advance_response = {
        "current_node": "validation",
        "report_checkpoint": carrier,
    }
    monkeypatch.setattr(navigation, "client_from_config", lambda: client)
    monkeypatch.setattr(
        navigation,
        "load_profile_root",
        lambda _profile: tmp_path / "client-support",
    )
    monkeypatch.setattr(
        navigation,
        "_client_for_profile",
        lambda _root, _profile: client,
    )
    monkeypatch.setattr(
        navigation,
        "_current_branch_report_submission",
        lambda **_kwargs: {"items": []},
    )
    published = {}

    def publish(**kwargs):
        published.update(kwargs)
        return {
            "changed": True,
            "report_changed": True,
            "profile_changed": True,
            "checkpoint_ref": carrier["checkpoint_ref"],
            "artifact": {"artifact_ref": "artifact:report"},
        }

    monkeypatch.setattr(navigation, "publish_research_checkpoint", publish)
    evidence = tmp_path / "evidence.json"
    evidence.write_text('{"ready": true}', encoding="utf-8")
    narrative = tmp_path / "narrative.json"
    narrative.write_text(
        '{"schema_version": 1, "language": "zh-Hans"}',
        encoding="utf-8",
    )

    result = CliRunner().invoke(cli, [
        "research-graph", "node", "advance", "instance-1", "branch-1",
        "--edge-id", "edge-1", "--evidence-file", str(evidence),
        "--profile-id", "maxa", "--agent-id", "research-maxa",
        "--narrative-file", str(narrative),
    ])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["local_report_publish"]["status"] == "published"
    assert payload["branch"]["report_checkpoint_ref"] == (
        "trace:checkpoint-1"
    )
    assert "report_checkpoint" not in payload["branch"]
    assert published["carrier"] == carrier
