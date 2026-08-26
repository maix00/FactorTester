from __future__ import annotations

import json
from types import SimpleNamespace

from click.testing import CliRunner

from tools.cli.app import cli
from tools.cli.commands import research_graph_navigation as navigation
from cli_anything.factortester_research.core.capability_registry import (
    capability_descriptor,
    load_builtin_capability_registry,
)


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
        return {
            "node": {"node_id": "validation_design"},
            "report_container": {
                "kind": "chapter", "anchor_node": "validation_design",
            },
            "next_actions": [{"action_id": "edge.choose"}],
        }


def test_node_info_does_not_expose_server_navigation_advice(monkeypatch):
    client = _Client()
    monkeypatch.setattr(navigation, "client_from_config", lambda: client)

    result = CliRunner().invoke(cli, [
        "research", "graphs", "node", "info", "instance-1", "branch-1",
    ])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert "next_action" not in payload
    assert "next_actions" not in payload


def test_edge_choose_is_read_only_and_returns_next_action(monkeypatch, tmp_path):
    client = _Client()
    monkeypatch.setattr(navigation, "client_from_config", lambda: client)
    output = tmp_path / "edge-choice.json"

    result = CliRunner().invoke(cli, [
        "research", "graphs", "edge", "choose", "instance-1", "branch-1",
        "edge-1", "--output", str(output),
    ])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["state_changed"] is False
    assert payload["selected_edge_id"] == "edge-1"
    assert json.loads(output.read_text()) == payload | {"output": str(output)}


def test_node_advance_returns_post_transition_state_without_server_advice(
    monkeypatch, tmp_path,
):
    client = _Client()
    monkeypatch.setattr(navigation, "client_from_config", lambda: client)
    evidence = tmp_path / "evidence.json"
    evidence.write_text('{"ready": true}', encoding="utf-8")

    result = CliRunner().invoke(cli, [
        "research", "graphs", "node", "advance", "instance-1", "branch-1",
        "--edge-id", "edge-1", "--evidence-file", str(evidence),
    ])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["doctor"]["operation"] == "node.advance"
    assert "next_actions" not in payload["next"]
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
        "research", "graphs", "node", "advance", "instance-1", "branch-1",
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
        "research", "graphs", "node", "advance", "instance-1", "branch-1",
        "--edge-id", "edge-1", "--evidence-file", str(evidence),
        "--entry-assessment-file", str(assessment),
    ])

    assert result.exit_code == 0, result.output
    assert client.advance_calls[0][3]["entry_requirement_assessments"] == [{
        "requirement_id": "data.scope",
        "entry_effect": {"status": "pass"},
    }]


def test_node_advance_creates_entry_draft_without_mutating(
    monkeypatch, tmp_path,
):
    client = _Client()
    client.get_research_graph_node_info = lambda *_args: {
        "branch": {
            "instance_id": "instance-1",
            "branch_id": "branch-1",
        },
        "node": {"node_id": "validation_design"},
        "entry_requirements": [{"requirement_id": "data.scope"}],
    }
    monkeypatch.setattr(navigation, "client_from_config", lambda: client)
    draft = tmp_path / "entry-assessment.json"

    def prepare(**kwargs):
        kwargs["output"].write_text('{"schema_version": 1}', encoding="utf-8")
        return {"selected_requirement_ids": ["data.scope"]}

    monkeypatch.setattr(navigation, "prepare_entry_assessment", prepare)
    evidence = tmp_path / "evidence.json"
    evidence.write_text('{"ready": true}', encoding="utf-8")

    result = CliRunner().invoke(cli, [
        "research", "graphs", "node", "advance", "instance-1", "branch-1",
        "--edge-id", "edge-1", "--evidence-file", str(evidence),
        "--entry-assessment-file", str(draft),
        "--factor-family", "SgCPS",
    ])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "entry_assessment_edit_required"
    assert payload["state_changed"] is False
    assert payload["selected_requirement_ids"] == ["data.scope"]
    assert draft.exists()
    assert client.advance_calls == []


def test_node_help_exposes_one_advance_orchestrator() -> None:
    result = CliRunner().invoke(cli, [
        "research", "graphs", "node", "--help",
    ])

    assert result.exit_code == 0, result.output
    assert "advance" in result.output
    assert "entry-prepare" not in result.output
    assert "entry-validate" not in result.output


def test_node_advance_automatically_binds_declared_target_capabilities(
    monkeypatch,
    tmp_path,
):
    client = _Client()
    monkeypatch.setattr(navigation, "client_from_config", lambda: client)
    registry = load_builtin_capability_registry()
    capability = next(
        item for item in registry["capabilities"]
        if item["capability_id"] == "research-obligation.discover"
    )
    descriptor = capability_descriptor(capability)
    client.get_research_graph_edge_info = (
        lambda instance_id, branch_id, edge_id: {
            "branch": {"product_group": "china_futures"},
            "edge": {"edge_id": edge_id},
            "report_requirements": [],
            "target_capabilities": {
                "node_id": "hypothesis_preregistration",
                "required": [{
                    "capability_id": "research-obligation.discover",
                    **descriptor,
                }],
                "resolution_required": True,
            },
        }
    )
    evidence = tmp_path / "evidence.json"
    evidence.write_text('{"ready": true}', encoding="utf-8")

    result = CliRunner().invoke(cli, [
        "research", "graphs", "node", "advance", "instance-1", "branch-1",
        "--edge-id", "edge-1", "--evidence-file", str(evidence),
    ])

    assert result.exit_code == 0, result.output
    submitted = client.advance_calls[0][3]
    assert [
        item["capability_id"]
        for item in submitted["target_capability_resolution"]["bindings"]
    ] == ["research-obligation.discover"]
    payload = json.loads(result.output)
    assert payload["doctor"]["target_capability_resolution"] == {
        "mode": "automatic",
        "node_id": "hypothesis_preregistration",
        "capability_ids": ["research-obligation.discover"],
        "agent_guidance": [{
            "capability_id": "research-obligation.discover",
            "mode": "discover",
            "skill_ref": "research-obligation-cycle",
            "instruction_zh": "进入目标节点后立即登记可能改变研究决策的新义务",
            "discovery_sources": [
                "self_discovery", "grill", "external_audit",
            ],
            "category_policy": (
                "match_existing_category_or_register_explicitly_unclassified"
            ),
        }],
    }


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
        "report_container": {
            "kind": "chapter", "anchor_node": "validation",
        },
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
    monkeypatch.setattr(
        navigation,
        "resolve_local_graph_report",
        lambda **_kwargs: SimpleNamespace(
            profile_id="maxa", agent_id="research-maxa",
            client_root=tmp_path / "client-support",
            record={"record_id": "work-package"},
            branch_id="branch-1",
            package_root=tmp_path / "work-package",
        ),
    )
    monkeypatch.setattr(
        navigation,
        "resolve_branch_report_scope",
        lambda **_kwargs: SimpleNamespace(),
    )
    monkeypatch.setattr(navigation, "load_authoring", lambda _scope: {})
    monkeypatch.setattr(
        navigation,
        "current_chapter_structure",
        lambda *_args, **_kwargs: {
            "chapter_component_id": "chapter-validation-design",
            "first_level_child_count": 1,
            "first_level_non_special_count": 1,
        },
    )
    ledger = tmp_path / "obligations.json"
    ledger.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        navigation, "ledger_path", lambda *_args, **_kwargs: ledger,
    )
    monkeypatch.setattr(
        navigation, "reconcile_current_container",
        lambda *_args, **_kwargs: {
            "status": "synchronized",
            "component_id": "chapter-validation-design",
        },
    )
    monkeypatch.setattr(
        navigation, "synchronize_transition_container",
        lambda *_args, **_kwargs: {
            "status": "synchronized", "node_id": "validation",
            "component_id": "chapter-validation",
        },
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
    prepared = SimpleNamespace(
        attempt_id="attempt-1",
        evidence={"ready": True},
        coverage_submission={"coverage": []},
    )
    monkeypatch.setattr(
        navigation, "prepare_obligation_advance",
        lambda **_kwargs: prepared,
    )
    monkeypatch.setattr(
        navigation, "require_complete_coverage", lambda _prepared: None,
    )
    monkeypatch.setattr(
        navigation, "require_scope_consistency", lambda _prepared: None,
    )
    reconciliation = {}

    def write_reconciliation(**kwargs):
        reconciliation.update({
            "attempt_id": kwargs["prepared"].attempt_id,
        })

    monkeypatch.setattr(
        navigation, "write_accepted_reconciliation", write_reconciliation,
    )
    monkeypatch.setattr(
        navigation,
        "load_accepted_reconciliation",
        lambda *_args, **_kwargs: reconciliation or None,
    )
    monkeypatch.setattr(
        navigation,
        "finalize_accepted_advance",
        lambda **_kwargs: {"receipt": {"status": "accepted"}},
    )
    evidence = tmp_path / "evidence.json"
    evidence.write_text('{"ready": true}', encoding="utf-8")
    narrative = tmp_path / "narrative.json"
    narrative.write_text(
        '{"schema_version": 1, "language": "zh-Hans"}',
        encoding="utf-8",
    )

    result = CliRunner().invoke(cli, [
        "research", "graphs", "node", "advance", "instance-1", "branch-1",
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
    assert published["report_parent_id"] == "chapter-validation"


def test_profile_bound_node_advance_cannot_bypass_obligation_ledger(
    monkeypatch,
    tmp_path,
):
    client = _Client()
    monkeypatch.setattr(navigation, "client_from_config", lambda: client)
    monkeypatch.setattr(
        navigation, "load_profile_root",
        lambda _profile: tmp_path / "client-support",
    )
    monkeypatch.setattr(
        navigation, "_client_for_profile", lambda _root, _profile: client,
    )
    monkeypatch.setattr(
        navigation, "_current_branch_report_submission",
        lambda **_kwargs: {"items": []},
    )
    package_root = tmp_path / "work-package"
    package_root.mkdir()
    monkeypatch.setattr(
        navigation,
        "resolve_local_graph_report",
        lambda **_kwargs: SimpleNamespace(
            profile_id="maxa",
            agent_id="research-maxa",
            package_root=package_root,
        ),
    )
    monkeypatch.setattr(
        navigation, "load_accepted_reconciliation",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        navigation, "reconcile_current_container",
        lambda *_args, **_kwargs: {
            "status": "synchronized",
            "component_id": "chapter-validation-design",
        },
    )
    evidence = tmp_path / "evidence.json"
    evidence.write_text('{"ready": true}', encoding="utf-8")

    result = CliRunner().invoke(cli, [
        "research", "graphs", "node", "advance", "instance-1", "branch-1",
        "--edge-id", "edge-1", "--evidence-file", str(evidence),
        "--profile-id", "maxa", "--agent-id", "research-maxa",
    ])

    assert result.exit_code == 1
    assert "branch-local obligation ledger" in result.output
    assert client.advance_calls == []
