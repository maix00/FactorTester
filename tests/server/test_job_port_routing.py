from __future__ import annotations

import settings as Settings

from server.jobs.models import JobRecord
from server.jobs.repository import JobRepository
from server.jobs.states import JobStatus
from flask import Flask
from server import auth as server_auth

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


def test_public_job_list_is_fixed_newest_twenty_snapshot(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", tmp_path / "public-jobs.sqlite")
    repository = JobRepository()
    for index in range(25):
        job_id = f"job-{index:02d}"
        updated_at = float(index + 1)
        port = 8141 if index % 2 else 8142
        repository.create(JobRecord(
            job_id=job_id,
            run_id=job_id,
            owner=f"owner-{job_id}",
            workspace_id="workspace-public",
            kind="ic",
            status=JobStatus.SUBMITTED,
            service_port=port,
            job_spec={},
            created_at=updated_at,
            updated_at=updated_at,
        ))
    app = Flask(__name__)
    app.secret_key = "public-jobs"

    @app.before_request
    def _manager_public_projection() -> None:
        from flask import session
        session["manager_gateway_public_jobs"] = True

    app.register_blueprint(sft_bp)
    client = app.test_client()
    first = client.get("/api/jobs?limit=100").get_json()
    second = client.get(
        "/api/jobs",
        query_string={"limit": 100, "cursor": "ignored-for-public-snapshot"},
    ).get_json()

    assert [item["job_id"] for item in first["jobs"]] == [
        f"job-{index:02d}" for index in range(24, 4, -1)
    ]
    assert first["page_size"] == 20
    assert first["total"] == 20
    assert first["total_pages"] == 1
    assert first["has_more"] is False
    assert first["next_cursor"] is None
    assert second == first


def test_public_job_list_ignores_cursor(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", tmp_path / "public-jobs.sqlite")
    app = Flask(__name__)
    app.secret_key = "public-jobs"

    @app.before_request
    def _manager_public_projection() -> None:
        from flask import session
        session["manager_gateway_public_jobs"] = True

    app.register_blueprint(sft_bp)
    response = app.test_client().get("/api/jobs?cursor=invalid")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["has_more"] is False
    assert payload["next_cursor"] is None


def test_public_job_detail_is_not_limited_by_anonymous_owner(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", tmp_path / "public-detail.sqlite")
    monkeypatch.setattr(
        "server.modules.single_factor_test.backtest_job_support.detect_port",
        lambda _environ: 8141,
    )
    repository = JobRepository()
    repository.create(JobRecord(
        job_id="public-detail",
        run_id="public-detail-run",
        owner="alice",
        workspace_id="workspace-public",
        kind="ic",
        status=JobStatus.SUBMITTED,
        service_port=8141,
        job_spec={"run_spec": {}},
    ))
    app = Flask(__name__)
    app.secret_key = "public-detail"

    @app.before_request
    def _manager_public_projection() -> None:
        from flask import session
        session["manager_gateway_public_jobs"] = True

    app.register_blueprint(sft_bp)
    response = app.test_client().get("/api/jobs/public-detail")

    assert response.status_code == 200
    assert response.get_json()["job_id"] == "public-detail"


def test_owner_job_list_reports_total_pages(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", tmp_path / "owner-pages.sqlite")
    monkeypatch.setattr(
        "server.modules.single_factor_test.backtest_job_reads.detect_port",
        lambda _environ: 8141,
    )
    repository = JobRepository()
    for index in range(3):
        repository.create(JobRecord(
            job_id=f"owner-page-{index}",
            run_id=f"owner-page-run-{index}",
            owner="alice",
            workspace_id="workspace-pages",
            kind="backtest",
            status=JobStatus.SUBMITTED,
            service_port=8141,
            job_spec={},
            updated_at=float(index + 1),
            created_at=float(index + 1),
        ))
    app = Flask(__name__)
    app.secret_key = "owner-pages"
    app.register_blueprint(sft_bp)
    client = app.test_client()
    with client.session_transaction() as flask_session:
        flask_session["username"] = "alice"

    response = client.get("/api/jobs?scope=mine&limit=2&page=2")
    payload = response.get_json()

    assert response.status_code == 200
    assert payload["page"] == 2
    assert payload["total"] == 3
    assert payload["total_pages"] == 2
    assert len(payload["jobs"]) == 1


def test_manager_public_job_gateway_bypasses_only_read_projections() -> None:
    app = Flask(__name__)
    app.secret_key = "public-jobs"
    app.add_url_rule(
        "/api/jobs", endpoint="sft.list_test_jobs",
        view_func=lambda: "ok",
    )

    with app.test_request_context("/api/jobs"):
        from flask import session
        session["manager_gateway_public_jobs"] = True
        assert server_auth._is_public_job_gateway_read()

    with app.test_request_context("/api/jobs/job-1/stream"):
        from flask import session
        session["manager_gateway_public_jobs"] = True
        assert not server_auth._is_public_job_gateway_read()

    with app.test_request_context(
        "/api/jobs/job-1/artifacts/archive",
        method="GET",
    ):
        from flask import session
        session["manager_gateway_public_jobs"] = True
        assert not server_auth._is_public_job_gateway_read()


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
