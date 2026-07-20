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


def _create_job(
    repository: JobRepository,
    *,
    job_id: str,
    owner: str = "alice",
    workspace_id: str = "workspace-1",
    status: JobStatus = JobStatus.SUCCEEDED,
    kind: str = "backtest",
) -> None:
    run_spec = {"workspace_id": workspace_id}
    repository.create(JobRecord(
        job_id=job_id,
        run_id=f"run-{job_id}",
        owner=owner,
        workspace_id=workspace_id,
        kind=kind,
        status=JobStatus.SUBMITTED,
        retention_mode="full",
        deployment_id="test",
        source_revision="test-backend-revision",
        runner_path="tests.server.long_lived_worker_fakes:artifact_runner",
        job_spec={"run_spec": run_spec},
        run_spec_hash=hashlib.sha256(
            orjson.dumps(run_spec, option=orjson.OPT_SORT_KEYS)
        ).hexdigest(),
        created_at=time.time(),
    ))
    repository.transition(job_id, JobStatus.PLANNING)
    repository.set_execution_plan(
        job_id,
        plan={"runner": "artifact_runner"},
        notices=[],
        requires_confirmation=False,
    )
    if status is JobStatus.CANCELLED:
        repository.request_cancel(job_id, owner=owner, reason="test_cancel")
        return
    repository.transition(job_id, JobStatus.RUNNING)
    if status is JobStatus.RUNNING:
        return
    if status is JobStatus.SUCCEEDED:
        repository.transition(
            job_id,
            status,
            result_summary={"success": True},
        )
    elif status is JobStatus.FAILED:
        repository.transition(
            job_id,
            status,
            error={"code": "test_failure", "message": "test failure"},
        )


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
    _create_job(
        repository,
        job_id="job-full",
        status=JobStatus.RUNNING,
    )
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
    repository.transition(
        "job-full",
        JobStatus.SUCCEEDED,
        result_summary={"success": True},
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
    assert job.get_json()["has_terminal_assurance"] is True
    assert "terminal_assurance" not in job.get_json()
    assert (
        job.get_json()["evidence"]["terminal_assurance"]["disposition"]
        == "trusted"
    )
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
        _create_job(
            repository,
            job_id=job_id,
            workspace_id=workspace_id,
            status=JobStatus.RUNNING,
        )
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
        repository.transition(
            job_id,
            JobStatus.SUCCEEDED,
            result_summary={"success": True},
        )

    cleared = client.delete("/api/jobs/artifacts?workspace_id=workspace-1")

    assert cleared.status_code == 200
    assert cleared.get_json()["deleted_files"] == 2
    assert not (root / "job-a" / "result.json").exists()
    assert not (root / "job-b" / "result.json").exists()
    assert (root / "job-c" / "result.json").is_file()
    assert client.get("/api/jobs/job-a").status_code == 200


def test_user_can_delete_terminal_job_history_without_touching_active_or_other_jobs(
    tmp_path, monkeypatch,
) -> None:
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", tmp_path / "jobs.sqlite")
    monkeypatch.setenv("GTHT_JOB_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(sft_bp)
    client = app.test_client()
    with client.session_transaction() as session:
        session["username"] = "alice"

    repository = JobRepository()
    rows = (
        ("done", "alice", "workspace-1", JobStatus.SUCCEEDED),
        ("failed", "alice", "workspace-1", JobStatus.FAILED),
        ("cancelled", "alice", "workspace-1", JobStatus.CANCELLED),
        ("running", "alice", "workspace-1", JobStatus.RUNNING),
        ("other-workspace", "alice", "workspace-2", JobStatus.SUCCEEDED),
        ("other-owner", "bob", "workspace-1", JobStatus.SUCCEEDED),
    )
    for job_id, owner, workspace_id, status in rows:
        _create_job(
            repository,
            job_id=job_id,
            owner=owner,
            workspace_id=workspace_id,
            status=(
                JobStatus.RUNNING
                if job_id == "done"
                else status
            ),
        )
    root = tmp_path / "artifacts"
    target = root / "done" / "result.json"
    target.parent.mkdir(parents=True)
    raw = orjson.dumps({"job_id": "done"})
    target.write_bytes(raw)
    repository.record_artifact(
        job_id="done",
        name="result",
        relative_path="done/result.json",
        content_type="application/json",
        content_hash=hashlib.sha256(raw).hexdigest(),
        size_bytes=len(raw),
    )
    repository.transition(
        "done",
        JobStatus.SUCCEEDED,
        result_summary={"success": True},
    )

    missing_workspace = client.delete("/api/jobs")
    cleared = client.delete("/api/jobs?workspace_id=workspace-1")

    assert missing_workspace.status_code == 400
    assert cleared.status_code == 200
    assert set(cleared.get_json()["deleted_job_ids"]) == {
        "done", "failed", "cancelled",
    }
    assert cleared.get_json()["deleted_files"] == 1
    assert not target.exists()
    for job_id in ("done", "failed", "cancelled"):
        assert repository.load(job_id) is None
    for job_id in ("running", "other-workspace", "other-owner"):
        assert repository.load(job_id) is not None


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
    repository = JobRepository()
    _create_job(
        repository,
        job_id="job-after-restart",
        kind="ic",
        status=JobStatus.SUCCEEDED,
    )

    class EmptyDaemon:
        def events(self, job_id, *, after, timeout):
            return {
                "known": False, "events": [], "gap": None, "closed": False,
                "latest_progress": None, "manifest": None,
            }

    monkeypatch.setattr(
        "server.modules.single_factor_test.backtest_job_reads._daemon_client",
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
