from __future__ import annotations

from flask import Flask

from server.modules.single_factor_test import sft_bp
from server.services import research_graphs
from server.services.research_graph.trial_plan import execution_checkpoint_api
from tests.server.research_step.test_contracts import (
    _execution,
    _next_packet,
)


def _client():
    app = Flask(__name__)
    app.secret_key = "research-step-test"
    app.register_blueprint(sft_bp)
    client = app.test_client()
    with client.session_transaction() as session:
        session["username"] = "alice"
    return client


def test_inspect_route_composes_only_existing_reads(monkeypatch) -> None:
    calls: list[str] = []

    def next_packet(**kwargs):
        calls.append("next")
        assert kwargs["owner"] == "alice"
        return _next_packet()

    def checkpoint(**kwargs):
        calls.append("checkpoint")
        assert kwargs["owner"] == "alice"
        return _execution()

    monkeypatch.setattr(
        research_graphs, "build_graph_branch_next", next_packet,
    )
    monkeypatch.setattr(
        execution_checkpoint_api,
        "load_execution_checkpoint_contract",
        checkpoint,
    )
    response = _client().get(
        "/api/research-graph-instances/instance-1/branches/branch-1/"
        "research-step"
    )

    assert response.status_code == 200
    value = response.get_json()["research_step"]
    assert calls == ["next", "checkpoint"]
    assert value["binding"]["work_package_id"] == "work-package-1"
    assert "trial_plan" not in value


def test_prepare_route_reloads_authority_and_reports_gap(
    monkeypatch,
) -> None:
    from server.services.research_step import build_inspect_contract

    inspect = build_inspect_contract(_next_packet(), _execution())
    calls: list[str] = []

    def next_packet(**kwargs):
        calls.append("next")
        return _next_packet()

    def checkpoint(**kwargs):
        calls.append("checkpoint")
        return _execution()

    monkeypatch.setattr(
        research_graphs, "build_graph_branch_next", next_packet,
    )
    monkeypatch.setattr(
        execution_checkpoint_api,
        "load_execution_checkpoint_contract",
        checkpoint,
    )
    response = _client().post(
        "/api/research-graph-instances/instance-1/branches/branch-1/"
        "research-step/prepare",
        json={
        "request": {
            "schema_version": 1,
            "context_ref": inspect["graph"]["context_ref"],
            "action_id": "action-1",
            "configurations": [{
                "configuration_id": "config-1",
                "configuration_revision": 1,
                "configuration_fingerprint": "7" * 64,
                "analyses": ["ic"],
                "trial_role": "candidate",
                "comparison_id": "comparison-1",
            }],
        },
    })

    assert response.status_code == 200
    assert calls == ["next", "checkpoint"]
    contract = response.get_json()["contract"]
    assert contract["binding"]["profile_ref"] == "profile:maxa"
    assert contract["binding"]["work_package_id"] == "work-package-1"
    assert contract["cas"]["checkpoint_hash"] == "3" * 64
    assert contract["execution_ready"] is False
    assert contract["capability_gaps"][0]["capability_id"] == (
        "research-run.immutable-configuration-snapshot"
    )


def test_prepare_rejects_forged_inspect_without_authority_reads(
    monkeypatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        research_graphs,
        "build_graph_branch_next",
        lambda **kwargs: calls.append("next"),
    )
    response = _client().post(
        "/api/research-graph-instances/instance-1/branches/branch-1/"
        "research-step/prepare",
        json={"inspect": {
            "binding": {
                "profile_ref": "profile:other",
                "work_package_id": "work-package:other",
            },
        }, "request": {}},
    )

    assert response.status_code == 400
    assert calls == []


def test_prepare_rejects_stale_context_and_action_after_exact_reads(
    monkeypatch,
) -> None:
    calls: list[str] = []

    def next_packet(**kwargs):
        calls.append("next")
        return _next_packet()

    def checkpoint(**kwargs):
        calls.append("checkpoint")
        return _execution()

    monkeypatch.setattr(
        research_graphs, "build_graph_branch_next", next_packet,
    )
    monkeypatch.setattr(
        execution_checkpoint_api,
        "load_execution_checkpoint_contract",
        checkpoint,
    )
    response = _client().post(
        "/api/research-graph-instances/instance-1/branches/branch-1/"
        "research-step/prepare",
        json={"request": {
            "schema_version": 1,
            "context_ref": "sha256:" + "9" * 64,
            "action_id": "forged-action",
            "configurations": [{
                "configuration_id": "config-1",
                "configuration_revision": 1,
                "configuration_fingerprint": "7" * 64,
                "analyses": ["ic"],
                "trial_role": "candidate",
                "comparison_id": "comparison-1",
            }],
        }},
    )

    assert response.status_code == 400
    assert calls == ["next", "checkpoint"]
    assert "stale" in response.get_json()["error"]


def test_prepare_rejects_stale_action_after_authoritative_reads(
    monkeypatch,
) -> None:
    calls: list[str] = []

    def next_packet(**kwargs):
        calls.append("next")
        return _next_packet()

    def checkpoint(**kwargs):
        calls.append("checkpoint")
        return _execution()

    monkeypatch.setattr(
        research_graphs, "build_graph_branch_next", next_packet,
    )
    monkeypatch.setattr(
        execution_checkpoint_api,
        "load_execution_checkpoint_contract",
        checkpoint,
    )
    response = _client().post(
        "/api/research-graph-instances/instance-1/branches/branch-1/"
        "research-step/prepare",
        json={"request": {
            "schema_version": 1,
            "context_ref": "sha256:" + "1" * 64,
            "action_id": "forged-action",
            "configurations": [{
                "configuration_id": "config-1",
                "configuration_revision": 1,
                "configuration_fingerprint": "7" * 64,
                "analyses": ["ic"],
                "trial_role": "candidate",
                "comparison_id": "comparison-1",
            }],
        }},
    )

    assert response.status_code == 400
    assert calls == ["next", "checkpoint"]
    assert "action_id is stale" in response.get_json()["error"]
