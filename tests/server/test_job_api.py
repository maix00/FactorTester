from __future__ import annotations

import time
import uuid

from flask import Flask
import pytest

import settings as Settings
from server.modules.single_factor_test import sft_bp
from server.modules.single_factor_test import backtest_jobs, research_jobs
from server.services import test_job_store, test_jobs


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", tmp_path / "jobs.sqlite")
    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(sft_bp)
    client = app.test_client()
    with client.session_transaction() as session:
        session["username"] = "alice"
    with test_jobs._lock:
        test_jobs._jobs.clear()
        test_jobs._run_token_to_job.clear()
        test_jobs._run_id_to_job.clear()
    return client


def _job(*, kind: str = "backtest", workspace_id: str = "workspace-a"):
    token = f"job-{uuid.uuid4().hex}"
    return test_jobs.create_job(
        kind=kind,
        run_token=token,
        run_id=f"run-{uuid.uuid4().hex}",
        workspace_id=workspace_id,
        lifecycle_policy="durable",
        owner="alice",
        payload={
            "run_token": token,
            "run_id": f"run-{uuid.uuid4().hex}",
            "workspace_id": workspace_id,
            "_owner": "alice",
        },
    )


def test_job_status_result_and_workspace_filter_are_durable(client) -> None:
    wanted = _job(workspace_id="workspace-a")
    _job(workspace_id="workspace-b")
    sink = test_jobs.TestJobSink(wanted)
    wanted.start()
    sink.emit_activity_manifest([{"key": "prepare", "label": "Prepare"}])
    sink.emit_progress(1, 2, "compute")
    sink.emit_result({"success": True, "answer": 42})
    wanted.close()

    status = client.get(f"/api/jobs/{wanted.job_id}").get_json()
    result = client.get(f"/api/jobs/{wanted.job_id}/result").get_json()
    listed = client.get("/api/jobs?workspace_id=workspace-a").get_json()["jobs"]

    assert status["status"] == "succeeded"
    assert status["attempt"] == 1
    assert "manifest" in status
    assert status["latest_progress"]["data"]["phase"] == "compute"
    assert status["manifest"]["data"]["phases"][0]["key"] == "prepare"
    assert result["result"]["answer"] == 42
    assert [item["job_id"] for item in listed] == [wanted.job_id]


def test_retry_without_view_becomes_durable_and_explicit_view_rebinds(monkeypatch) -> None:
    old = _job()
    captured = []

    def fake_submit(kind, payload):
        captured.append((kind, payload))
        return old

    monkeypatch.setattr(research_jobs, "_submit_kind", fake_submit)
    payload = {"lifecycle_policy": "observer_bound", "view_uuid": "old-view"}

    backtest_jobs._resubmit(old, dict(payload))
    backtest_jobs._resubmit(old, dict(payload), view_uuid="new-view")

    assert captured[0][1]["lifecycle_policy"] == "durable"
    assert "view_uuid" not in captured[0][1]
    assert captured[1][1]["lifecycle_policy"] == "observer_bound"
    assert captured[1][1]["view_uuid"] == "new-view"


def test_last_event_id_and_gap_reset_are_supported(client, monkeypatch) -> None:
    monkeypatch.setattr(test_jobs, "_MAX_EVENTS", 2)
    job = _job()
    job.emit("progress", {"value": 1})
    job.emit("progress", {"value": 2})
    job.emit("progress", {"value": 3})
    job.emit("progress", {"value": 4})
    job.succeed({"success": True})
    job.close()

    response = client.get(
        f"/api/jobs/{job.job_id}/stream",
        headers={"Last-Event-ID": "1"},
    )
    body = response.get_data(as_text=True)

    assert "event: reset" in body
    assert '"requested_seq":1' in body
    assert "event: progress" in body


def test_failure_cancel_and_artifact_records_remain_queryable(client) -> None:
    failed = _job(kind="ic")
    sink = test_jobs.TestJobSink(failed)
    failed.start()
    sink.emit_artifact("diagnostic", {"rows": 3})
    sink.emit_error("bad input", traceback="traceback text")
    failed.close()
    queued = _job(kind="factor_evaluation")

    assert client.post(f"/api/jobs/{queued.job_id}/cancel").get_json()["cancelled"] is True
    failure = client.get(f"/api/jobs/{failed.job_id}/result").get_json()
    cancelled = client.get(f"/api/jobs/{queued.job_id}/result").get_json()
    artifact = client.get(f"/api/jobs/{failed.job_id}/artifacts/diagnostic").get_json()

    assert failure["status"] == "failed"
    assert failure["error"]["traceback"] == "traceback text"
    assert cancelled["status"] == "cancelled"
    assert artifact["artifact"] == {"rows": 3}


def test_expired_result_and_artifact_return_explicit_terminal_state(client, monkeypatch) -> None:
    job = _job()
    sink = test_jobs.TestJobSink(job)
    job.start()
    sink.emit_artifact("detail", {"large": True})
    sink.emit_result({"success": True})
    job.close()
    monkeypatch.setattr(test_jobs, "_JOB_TTL_SECONDS", 60)

    from tools.data.sqlite.db import connect_sqlite

    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        conn.execute(
            "UPDATE test_jobs SET finished_at = ? WHERE job_id = ?",
            (time.time() - 61, job.job_id),
        )
    with test_jobs._lock:
        test_jobs._jobs.pop(job.job_id, None)

    status = client.get(f"/api/jobs/{job.job_id}").get_json()
    artifact = client.get(f"/api/jobs/{job.job_id}/artifacts/detail")

    assert status["status"] == "expired"
    assert artifact.status_code == 410
    assert artifact.get_json()["status"] == "expired"
