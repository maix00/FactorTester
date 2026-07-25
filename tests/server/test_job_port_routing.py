from __future__ import annotations

from server.jobs.models import JobRecord
from server.jobs.repository import JobRepository
from server.jobs.states import JobStatus
from flask import Flask

from server.modules.single_factor_test import sft_bp


def test_job_port_is_persisted_but_deployment_is_not_public(tmp_path) -> None:
    repository = JobRepository(tmp_path / "jobs.sqlite")
    record = repository.create(JobRecord(
        job_id="job-port",
        run_id="run-port",
        owner="alice",
        workspace_id="workspace-port",
        kind="backtest",
        status=JobStatus.SUBMITTED,
        deployment_id="internal-deployment",
        service_port=8142,
        job_spec={"run_spec": {}},
    ))

    loaded = repository.require("job-port", owner="alice")
    assert loaded.service_port == 8142
    assert record.summary()["port"] == 8142
    assert "deployment_id" not in record.summary()


def test_job_list_can_filter_by_port(tmp_path) -> None:
    repository = JobRepository(tmp_path / "jobs.sqlite")
    for job_id, port in (("job-a", 8141), ("job-b", 8142)):
        repository.create(JobRecord(
            job_id=job_id,
            run_id=job_id,
            owner="alice",
            workspace_id="workspace-port",
            kind="ic",
            status=JobStatus.SUBMITTED,
            service_port=port,
            job_spec={},
        ))

    rows = repository.list_with_metadata(
        owner="alice", service_port=8142, limit=20,
    )
    assert [item["job"].job_id for item in rows] == ["job-b"]


def test_user_port_discovery_projects_only_running_ports(monkeypatch) -> None:
    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(sft_bp)
    monkeypatch.setattr(
        "server.modules.single_factor_test.job_port_routes.manager_snapshot",
        lambda: {
            "instances": [
                {"instance_id": "opaque", "port": 8141, "running": True},
                {"instance_id": "stopped", "port": 8142, "running": False},
            ],
            "vibe_trading": {"instance_id": "opaque-vibe", "port": 7899, "running": True},
        },
    )
    monkeypatch.setattr(
        "server.modules.single_factor_test.job_port_routes.detect_port",
        lambda environ: 8141,
    )
    client = app.test_client()
    with client.session_transaction() as session:
        session["username"] = "alice"

    response = client.get("/api/jobs/ports")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ports"] == [8141]
    assert "instances" not in payload
    assert "instance_id" not in response.get_data(as_text=True)
