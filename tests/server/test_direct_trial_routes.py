from __future__ import annotations

from flask import Flask, session
import settings as Settings

from server.modules.single_factor_test import sft_bp
from server.modules.single_factor_test import direct_trial_routes as _legacy_routes  # noqa: F401
from server.services import research_runs
from tests.server.trial_plan_fixtures import trial_plan


def test_direct_trial_plan_endpoint_returns_a_frozen_binding(
    tmp_path, monkeypatch,
) -> None:
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", tmp_path / "direct-plan.sqlite")
    run_spec_hash = "a" * 64
    app = Flask(__name__)
    app.secret_key = "direct-trial-test"

    @app.before_request
    def _authenticate() -> None:
        session["username"] = "owner-1"

    app.register_blueprint(sft_bp)
    response = app.test_client().post("/api/trial-plans/direct", json={
        "trial_plan": trial_plan(run_spec_hash),
        "run_spec_hash": run_spec_hash,
        "trial_role": "selection",
        "comparison_id": "main-comparison",
    })

    assert response.status_code == 200
    binding = response.get_json()["trial_binding"]
    assert binding["binding_origin"] == "agent_direct"
    assert binding["trial_plan_ref"] == (
        "trial-plan:sha256:" + binding["trial_plan_hash"]
    )
    assert binding["trial_plan"]["trial_plan_id"] == "plan-1"
    loaded = app.test_client().get(
        "/api/trial-plans/direct/" + binding["trial_plan_hash"]
    )
    assert loaded.status_code == 200
    assert loaded.get_json()["trial_plan"]["trial_plan_hash"] == (
        binding["trial_plan_hash"]
    )


def test_direct_trial_plan_rejects_graph_action_schema(
    tmp_path, monkeypatch,
) -> None:
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", tmp_path / "direct-plan.sqlite")
    app = Flask(__name__)
    app.secret_key = "direct-trial-test"

    @app.before_request
    def _authenticate() -> None:
        session["username"] = "owner-1"

    app.register_blueprint(sft_bp)
    response = app.test_client().post("/api/trial-plans/direct", json={
        "trial_plan": {"schema_version": 5},
        "run_spec_hash": "a" * 64,
        "trial_role": "candidate",
        "comparison_id": "comparison-1",
    })

    assert response.status_code == 400
    assert response.get_json()["success"] is False


def test_direct_trial_plan_rejects_a_non_object_body(
    tmp_path, monkeypatch,
) -> None:
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", tmp_path / "direct-plan.sqlite")
    app = Flask(__name__)
    app.secret_key = "direct-trial-test"

    @app.before_request
    def _authenticate() -> None:
        session["username"] = "owner-1"

    app.register_blueprint(sft_bp)
    response = app.test_client().post("/api/trial-plans/direct", json={
        "trial_plan": [],
        "run_spec_hash": "a" * 64,
        "trial_role": "candidate",
        "comparison_id": "comparison-1",
    })

    assert response.status_code == 400
    assert response.get_json()["success"] is False


def test_run_spec_endpoint_returns_an_owned_immutable_run_spec(
    tmp_path, monkeypatch,
) -> None:
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", tmp_path / "run-spec.sqlite")
    run_spec = {"run_spec_version": 3, "configuration": {"shared": {}}}
    run = research_runs.create_run(
        owner="owner-1",
        workspace_id="workspace-1",
        configuration_id="configuration-1",
        configuration_revision=3,
        run_spec=run_spec,
    )
    app = Flask(__name__)
    app.secret_key = "run-spec-test"

    @app.before_request
    def _authenticate() -> None:
        session["username"] = "owner-1"

    app.register_blueprint(sft_bp)
    response = app.test_client().get(
        "/api/run-specs/" + run["run_spec_hash"]
    )

    assert response.status_code == 200
    value = response.get_json()["run_spec"]
    assert value["run_spec_hash"] == run["run_spec_hash"]
    assert value["run_spec"] == run_spec
    assert value["configuration_revision"] == 3
    assert value["alias_zh"] == "研究运行"
    assert value["summary_zh"].startswith("研究运行；")


def test_run_spec_endpoint_does_not_expose_another_users_run_spec(
    tmp_path, monkeypatch,
) -> None:
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", tmp_path / "private-spec.sqlite")
    run = research_runs.create_run(
        owner="owner-2",
        workspace_id="workspace-2",
        configuration_id="configuration-2",
        configuration_revision=1,
        run_spec={"run_spec_version": 3, "configuration": {"shared": {}}},
    )
    app = Flask(__name__)
    app.secret_key = "private-run-spec-test"

    @app.before_request
    def _authenticate() -> None:
        session["username"] = "owner-1"

    app.register_blueprint(sft_bp)
    response = app.test_client().get(
        "/api/run-specs/" + run["run_spec_hash"]
    )

    assert response.status_code == 404
