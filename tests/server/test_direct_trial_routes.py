from __future__ import annotations

from flask import Flask, session
import settings as Settings

from server.modules.single_factor_test import sft_bp
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
