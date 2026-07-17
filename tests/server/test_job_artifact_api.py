from __future__ import annotations

import hashlib
import os
import time

from flask import Flask
import orjson

import settings as Settings
from server.jobs.models import JobRecord
from server.jobs.artifacts import cleanup_staging_files
from server.jobs.repository import JobRepository
from server.jobs.states import JobStatus
from server.modules.single_factor_test import sft_bp


def test_user_can_read_and_clear_full_result_without_deleting_job(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", tmp_path / "jobs.sqlite")
    monkeypatch.setenv("GTHT_JOB_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(sft_bp)
    client = app.test_client()
    with client.session_transaction() as session:
        session["username"] = "alice"

    repository = JobRepository()
    repository.create(JobRecord(
        job_id="job-full",
        run_id="run-full",
        owner="alice",
        workspace_id="workspace-1",
        kind="backtest",
        status=JobStatus.SUCCEEDED,
        retention_mode="full",
        deployment_id="test",
        runner_path="tests.server.long_lived_worker_fakes:artifact_runner",
        job_spec={},
        created_at=time.time(),
    ))
    root = tmp_path / "artifacts"
    target = root / "job-full" / "result.json"
    target.parent.mkdir(parents=True)
    raw = orjson.dumps({"success": True, "curve": [1, 2, 3]})
    target.write_bytes(raw)
    repository.record_artifact(
        job_id="job-full",
        name="result",
        relative_path="job-full/result.json",
        content_type="application/json",
        content_hash=hashlib.sha256(raw).hexdigest(),
        size_bytes=len(raw),
    )

    loaded = client.get("/api/jobs/job-full/artifacts/result")
    cleared = client.delete("/api/jobs/job-full/artifacts")
    job = client.get("/api/jobs/job-full")

    assert loaded.status_code == 200
    assert loaded.get_json()["curve"] == [1, 2, 3]
    assert cleared.get_json()["deleted_files"] == 1
    assert not target.exists()
    assert job.status_code == 200
    assert job.get_json()["status"] == "succeeded"
    assert repository.storage_usage(owner="alice") == 0


def test_user_can_bulk_clear_retained_results_by_workspace(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", tmp_path / "jobs.sqlite")
    monkeypatch.setenv("GTHT_JOB_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(sft_bp)
    client = app.test_client()
    with client.session_transaction() as session:
        session["username"] = "alice"

    repository = JobRepository()
    root = tmp_path / "artifacts"
    for job_id, workspace_id in (("job-a", "workspace-1"), ("job-b", "workspace-1"), ("job-c", "workspace-2")):
        repository.create(JobRecord(
            job_id=job_id,
            run_id=f"run-{job_id}",
            owner="alice",
            workspace_id=workspace_id,
            kind="backtest",
            status=JobStatus.SUCCEEDED,
            retention_mode="full",
            deployment_id="test",
            runner_path="tests.server.long_lived_worker_fakes:artifact_runner",
            job_spec={},
            created_at=time.time(),
        ))
        target = root / job_id / "result.json"
        target.parent.mkdir(parents=True)
        raw = orjson.dumps({"job_id": job_id})
        target.write_bytes(raw)
        repository.record_artifact(
            job_id=job_id,
            name="result",
            relative_path=f"{job_id}/result.json",
            content_type="application/json",
            content_hash=hashlib.sha256(raw).hexdigest(),
            size_bytes=len(raw),
        )

    cleared = client.delete("/api/jobs/artifacts?workspace_id=workspace-1")

    assert cleared.status_code == 200
    assert cleared.get_json()["deleted_files"] == 2
    assert not (root / "job-a" / "result.json").exists()
    assert not (root / "job-b" / "result.json").exists()
    assert (root / "job-c" / "result.json").is_file()
    assert client.get("/api/jobs/job-a").status_code == 200


def test_artifact_cleanup_only_removes_expired_staging_files(tmp_path) -> None:
    old = tmp_path / "job-old" / ".result.1.tmp"
    recent = tmp_path / "job-new" / ".result.2.tmp"
    retained = tmp_path / "job-old" / "result.json"
    for path in (old, recent, retained):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("data", encoding="utf-8")
    expired = time.time() - 7200
    os.utime(old, (expired, expired))

    removed = cleanup_staging_files(tmp_path, max_age_seconds=3600)

    assert removed == 1
    assert not old.exists()
    assert recent.is_file()
    assert retained.is_file()


def test_terminal_job_stream_resets_when_daemon_lost_live_event_state(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", tmp_path / "jobs.sqlite")
    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(sft_bp)
    client = app.test_client()
    with client.session_transaction() as session:
        session["username"] = "alice"
    JobRepository().create(JobRecord(
        job_id="job-after-restart",
        run_id="run-after-restart",
        owner="alice",
        workspace_id="workspace-1",
        kind="ic",
        status=JobStatus.SUCCEEDED,
        deployment_id="test",
        runner_path="tests.server.long_lived_worker_fakes:cpu_runner",
        job_spec={},
        result_summary={"success": True},
        created_at=time.time(),
    ))

    class EmptyDaemon:
        def events(self, job_id, *, after, timeout):
            return {
                "known": False, "events": [], "gap": None, "closed": False,
                "latest_progress": None, "manifest": None,
            }

    monkeypatch.setattr(
        "server.modules.single_factor_test.backtest_jobs._daemon_client",
        lambda: EmptyDaemon(),
    )

    response = client.get(
        "/api/jobs/job-after-restart/stream",
        headers={"Last-Event-ID": "12"},
    )
    body = response.get_data(as_text=True)

    assert "event: reset" in body
    assert '"reason":"event_state_unavailable"' in body
    assert '"status":"succeeded"' in body
