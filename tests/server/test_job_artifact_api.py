from __future__ import annotations

import hashlib
import time

from flask import Flask
import orjson

import settings as Settings
from server.jobs.models import JobRecord
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
