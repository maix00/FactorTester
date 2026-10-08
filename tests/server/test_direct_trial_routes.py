from __future__ import annotations

import json
import time

from flask import Flask, session
import settings as Settings
from tools.data.sqlite.db import connect_sqlite

from server.modules.single_factor_test import sft_bp
from server.services import direct_trial_plan_registry, research_runs
from tests.server.trial_plan_fixtures import trial_plan


def test_direct_trial_plan_write_is_retired_and_historical_binding_is_readable(
    tmp_path, monkeypatch,
) -> None:
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", tmp_path / "direct-plan.sqlite")
    run_spec_hash = "a" * 64
    legacy_plan = trial_plan(run_spec_hash)
    digest = "b" * 64
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE direct_trial_plans (
                owner TEXT NOT NULL, trial_plan_hash TEXT NOT NULL,
                trial_plan_id TEXT NOT NULL, trial_plan_version INTEGER NOT NULL,
                trial_plan_json TEXT NOT NULL, created_at REAL NOT NULL,
                PRIMARY KEY (owner, trial_plan_hash)
            )
            """
        )
        conn.execute(
            "INSERT INTO direct_trial_plans VALUES (?, ?, ?, ?, ?, ?)",
            (
                "owner-1", digest, legacy_plan["trial_plan_id"], 1,
                json.dumps(legacy_plan), time.time(),
            ),
        )
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

    assert response.status_code == 410
    assert "sample_use" in response.get_json()["error"]
    loaded = app.test_client().get(
        "/api/trial-plans/direct/" + digest
    )
    assert loaded.status_code == 200
    assert loaded.get_json()["trial_plan"]["trial_plan_hash"] == (
        digest
    )


def test_run_spec_endpoint_returns_an_owned_immutable_run_spec(
    tmp_path, monkeypatch,
) -> None:
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", tmp_path / "run-spec.sqlite")
    run_spec = {
        "run_spec_version": research_runs.RUN_SPEC_VERSION,
        "configuration": {"shared": {}},
    }
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
        run_spec={
            "run_spec_version": research_runs.RUN_SPEC_VERSION,
            "configuration": {"shared": {}},
        },
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
