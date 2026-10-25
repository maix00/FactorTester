from __future__ import annotations

from flask import Flask

import settings as Settings
from server.jobs.models import JobRecord
from server.jobs.repository.sqlite import JobRepository
from server.jobs.states import JobStatus
from server.modules.single_factor_test import sft_bp


def test_dispatch_status_api_reports_outbox_and_workers(tmp_path, monkeypatch):
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", tmp_path / "jobs.sqlite")
    monkeypatch.setenv("FACTORTESTER_DEPLOYMENT_ID", "local-docker")
    monkeypatch.setenv("FACTORTESTER_SERVICE_PORT", "8001")
    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(sft_bp)
    client = app.test_client()
    with client.session_transaction() as session:
        session["username"] = "alice"
    repository = JobRepository()
    repository.create(
        JobRecord(
            job_id="dispatch-status-job",
            run_id="run",
            owner="alice",
            workspace_id="ws",
            kind="backtest",
            status=JobStatus.SUBMITTED,
            deployment_id="local-docker",
            service_port=8001,
            run_spec_hash="a" * 64,
            job_spec={},
        )
    )
    repository.transition("dispatch-status-job", JobStatus.PLANNING)
    repository.transition("dispatch-status-job", JobStatus.QUEUED)
    repository.heartbeat_worker_target("local-docker", 8001, "worker-a", ttl_seconds=60)

    response = client.get("/api/dispatch/status")
    payload = response.get_json()
    assert response.status_code == 200
    assert payload["deployment_id"] == "local-docker"
    assert payload["service_port"] == 8001
    assert payload["queue"] == "factortester.jobs.local-docker.8001"
    assert payload["outbox"]["pending"] == 1
    assert payload["workers"][0]["online"] is True
