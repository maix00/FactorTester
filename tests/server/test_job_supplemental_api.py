from __future__ import annotations

import hashlib
import time

import orjson
import pytest
from flask import Flask

import settings as Settings
from server.jobs.models import JobRecord
from server.jobs.report_outputs import build_report_artifacts
from server.jobs.repository import JobRepository
from server.jobs.states import JobStatus
from server.modules.single_factor_test import sft_bp


class _Daemon:
    def __init__(self) -> None:
        self.wakes = 0

    def wake(self) -> None:
        self.wakes += 1


def _parent(repository: JobRepository, root) -> None:
    repository.create(JobRecord(
        job_id="parent-1", run_id="run-1", owner="alice",
        workspace_id="workspace-1", kind="backtest",
        status=JobStatus.SUBMITTED, deployment_id="test",
        job_spec={"run_spec": {"schema_version": 1}},
        run_spec_hash="run-spec-hash", created_at=time.time(),
    ))
    repository.transition("parent-1", JobStatus.PLANNING)
    repository.set_execution_plan(
        "parent-1", plan={"runner": "test"}, notices=[],
        requires_confirmation=False,
    )
    repository.transition("parent-1", JobStatus.RUNNING)
    source = {
        "artifact_version": 1,
        "strategies": {
            "strategy-1": {
                "identity": {
                    "strategy_id": "strategy-1", "group_index": 0,
                    "product_path_selection_id": "products-1",
                    "strategy_configuration_id": "config-1",
                },
                "result_group": {
                    "strategy_id": "strategy-1", "metrics_key": "strategy-1",
                    "timestamps": [1704067200000, 1704153600000],
                    "total_equity": [100.0, 101.0],
                },
                "position_curve": {}, "notional_curve": {},
                "margin_curve": {}, "fill_turnover": {},
            },
        },
        "metrics": {"strategy-1": {"Total Return": 0.01}},
        "detail_context": {},
    }
    raw = orjson.dumps(source)
    target = root / "parent-1" / "strategy-analysis-source.json"
    target.parent.mkdir(parents=True)
    target.write_bytes(raw)
    repository.record_artifact(
        job_id="parent-1", name="strategy_analysis_source",
        relative_path="parent-1/strategy-analysis-source.json",
        content_type="application/json",
        content_hash=hashlib.sha256(raw).hexdigest(), size_bytes=len(raw),
    )
    repository.transition(
        "parent-1", JobStatus.SUCCEEDED, result_summary={"success": True},
    )


def test_supplemental_routes_create_single_flight_and_page(tmp_path, monkeypatch):
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", tmp_path / "jobs.sqlite")
    monkeypatch.setenv("GTHT_JOB_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    repository = JobRepository()
    _parent(repository, tmp_path / "artifacts")
    app = Flask(__name__)
    app.secret_key = "supplemental"
    app.register_blueprint(sft_bp)
    client = app.test_client()
    with client.session_transaction() as session:
        session["username"] = "alice"

    request = {
        "kind": "backtest_strategy_analysis",
        "params": {"analysis_tab": "overview", "strategy_id": "strategy-1"},
    }
    created = client.post("/api/jobs/parent-1/supplementals", json=request)
    duplicate = client.post("/api/jobs/parent-1/supplementals", json={
        "kind": "backtest_strategy_analysis",
        "params": {"analysis_tab": "rolling", "strategy_id": "strategy-1"},
    })
    listed = client.get(
        "/api/jobs/parent-1/supplementals",
        query_string={"search": "backtest_strategy", "limit": 10},
    )

    assert created.status_code == 201, created.get_json()
    assert duplicate.status_code == 202
    assert created.get_json()["job"]["status"] == "queued"
    assert duplicate.get_json()["job"]["job_id"] == created.get_json()["job"]["job_id"]
    payload = listed.get_json()
    assert payload["total"] == 1
    assert payload["jobs"][0]["supplemental_kind"] == "backtest_strategy_analysis"


def test_visitor_cannot_submit_supplemental(tmp_path, monkeypatch):
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", tmp_path / "jobs.sqlite")
    monkeypatch.setenv("GTHT_JOB_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    _parent(JobRepository(), tmp_path / "artifacts")
    app = Flask(__name__)
    app.secret_key = "supplemental"
    app.register_blueprint(sft_bp)
    client = app.test_client()
    with client.session_transaction() as session:
        session["username"] = "visitor:test"
        session["manager_gateway_public_jobs"] = True

    response = client.post("/api/jobs/parent-1/supplementals", json={
        "kind": "backtest_strategy_analysis", "params": {},
    })

    assert response.status_code == 403


def test_report_output_supplemental_reports_missing_retained_sources(
    tmp_path, monkeypatch,
):
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", tmp_path / "jobs.sqlite")
    monkeypatch.setenv("GTHT_JOB_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    repository = JobRepository()
    _parent(repository, tmp_path / "artifacts")
    app = Flask(__name__)
    app.secret_key = "supplemental"
    app.register_blueprint(sft_bp)
    client = app.test_client()
    with client.session_transaction() as session:
        session["username"] = "alice"

    response = client.post("/api/jobs/parent-1/supplementals", json={
        "kind": "report_output_generation",
        "params": {"output_requests": ["position_detail"]},
    })

    assert response.status_code == 409
    assert "group_execution" in response.get_json()["error"]


