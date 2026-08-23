from __future__ import annotations

import time

from flask import Flask
import pytest

import settings as Settings
from server.admin import admin_bp
from server.jobs.models import JobRecord
from server.jobs.repository import JobRepository
from server.jobs.states import JobStatus
from tools.data.sqlite.db import connect_sqlite


def _client(monkeypatch, tmp_path, *, role: str):
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", tmp_path / "jobs.sqlite")
    monkeypatch.setattr(
        "server.admin.get_account",
        lambda username: {
            "username": username,
            "role": role,
            "is_admin": role == "super_admin",
        },
    )
    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(admin_bp)
    client = app.test_client()
    with client.session_transaction() as session:
        session["username"] = "root"
    return client


def _create_job(repository: JobRepository, *, job_id: str, owner: str, updated_at: float) -> None:
    repository.create(JobRecord(
        job_id=job_id,
        run_id=f"run-{job_id}",
        owner=owner,
        workspace_id=f"workspace-{owner}",
        kind="backtest",
        status=JobStatus.SUBMITTED,
        deployment_id="server-main",
        source_revision="secret-source-revision",
        runner_path="/Users/private/source/runner.py",
        job_spec={
            "source": "def secret_factor(): pass",
            "credential": "should-not-leak",
        },
        created_at=updated_at,
        updated_at=updated_at,
    ))


def test_super_admin_can_read_a_bounded_global_job_summary(tmp_path, monkeypatch) -> None:
    client = _client(monkeypatch, tmp_path, role="super_admin")
    repository = JobRepository()
    _create_job(repository, job_id="job-a", owner="alice", updated_at=time.time())

    response = client.get("/admin/api/jobs?limit=1")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    assert payload["page_size"] == 1
    assert payload["jobs"] == [{
        "attempt": 1,
        "cancel_requested": False,
        "created_at": payload["jobs"][0]["created_at"],
        "deployment_id": "server-main",
        "finished_at": None,
        "job_id": "job-a",
            "kind": "backtest",
            "owner": "alice",
            "parent_updated_at": payload["jobs"][0]["updated_at"],
            "run_id": "run-job-a",
            "started_at": None,
            "status": "submitted",
            "step_mode": False,
            "supplemental_active_count": 0,
            "supplemental_count": 0,
            "supplemental_failed_count": 0,
            "supplemental_updated_at": None,
            "updated_at": payload["jobs"][0]["updated_at"],
        "workspace_id": "workspace-alice",
    }]
    serialized = response.get_data(as_text=True)
    assert "secret_factor" not in serialized
    assert "credential" not in serialized
    assert "/Users/" not in serialized
    assert "source_revision" not in serialized
    assert "runner_path" not in serialized


@pytest.mark.parametrize("role", ["user", "developer", "level_admin", "org_admin"])
def test_non_super_admin_cannot_read_the_global_job_queue(
    tmp_path,
    monkeypatch,
    role: str,
) -> None:
    client = _client(monkeypatch, tmp_path, role=role)

    response = client.get(
        "/admin/api/jobs",
        headers={"Accept": "application/json"},
    )

    assert response.status_code == 403
    assert response.get_json()["success"] is False


def test_global_job_queue_uses_stable_cursor_pagination(tmp_path, monkeypatch) -> None:
    client = _client(monkeypatch, tmp_path, role="super_admin")
    repository = JobRepository()
    for index, owner in enumerate(("alice", "bob", "carol"), start=1):
        _create_job(
            repository,
            job_id=f"job-{index}",
            owner=owner,
            updated_at=float(index),
        )

    first = client.get("/admin/api/jobs?limit=2").get_json()
    second = client.get(
        "/admin/api/jobs",
        query_string={"limit": 2, "cursor": first["next_cursor"]},
    ).get_json()

    assert [job["job_id"] for job in first["jobs"]] == ["job-3", "job-2"]
    assert first["has_more"] is True
    assert first["next_cursor"]
    assert [job["job_id"] for job in second["jobs"]] == ["job-1"]
    assert second["has_more"] is False
    assert second["next_cursor"] is None


def test_global_job_queue_rejects_an_invalid_cursor(tmp_path, monkeypatch) -> None:
    client = _client(monkeypatch, tmp_path, role="super_admin")

    response = client.get("/admin/api/jobs?cursor=a")

    assert response.status_code == 400
    assert response.get_json() == {"success": False, "error": "cursor 无效"}


def test_global_job_queue_caps_each_page_at_one_hundred_rows(
    tmp_path,
    monkeypatch,
) -> None:
    client = _client(monkeypatch, tmp_path, role="super_admin")
    repository = JobRepository()
    for index in range(101):
        _create_job(
            repository,
            job_id=f"job-{index:03d}",
            owner="alice",
            updated_at=float(index),
        )

    response = client.get("/admin/api/jobs?limit=10000")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["page_size"] == 100
    assert len(payload["jobs"]) == 100
    assert payload["has_more"] is True


def test_global_job_summary_hot_path_is_one_read_and_zero_writes(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", tmp_path / "jobs.sqlite")
    repository = JobRepository()
    _create_job(
        repository,
        job_id="job-read-only",
        owner="alice",
        updated_at=1.0,
    )
    connection = connect_sqlite(Settings.CACHE_DB_PATH, foreign_keys=True)
    statements = []
    connection.set_trace_callback(statements.append)
    monkeypatch.setattr(repository, "_connect", lambda: connection)

    jobs, has_more = repository.list_global_summaries(limit=20)

    assert jobs[0]["job_id"] == "job-read-only"
    assert has_more is False
    sql = [statement.strip().upper() for statement in statements]
    assert sum(statement.startswith("SELECT") for statement in sql) == 1
    assert not any(
        statement.startswith(("INSERT", "UPDATE", "DELETE", "REPLACE"))
        for statement in sql
    )
    connection.close()


def test_global_job_summary_uses_the_global_updated_cursor_index(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", tmp_path / "jobs.sqlite")
    repository = JobRepository()
    repository.ensure_schema()
    connection = connect_sqlite(Settings.CACHE_DB_PATH)

    plan = connection.execute(
        """
        EXPLAIN QUERY PLAN
        SELECT job_id, updated_at
        FROM research_jobs
        WHERE (updated_at, job_id) < (?, ?)
        ORDER BY updated_at DESC, job_id DESC
        LIMIT ?
        """,
        (100.0, "job-z", 101),
    ).fetchall()

    details = "\n".join(str(row[3]) for row in plan)
    assert "idx_research_jobs_global_updated" in details
    assert "SEARCH" in details
    assert "USE TEMP B-TREE" not in details
    connection.close()
