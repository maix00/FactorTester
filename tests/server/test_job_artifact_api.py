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
from server.modules.single_factor_test.backtest_job_reads import _public_job_spec


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

    manifest = client.get("/api/jobs/job-full/artifacts")
    loaded = client.get("/api/jobs/job-full/artifacts/result")
    archive = client.get("/api/jobs/job-full/artifacts/archive")
    cleared = client.delete("/api/jobs/job-full/artifacts")
    job = client.get("/api/jobs/job-full")

    assert manifest.status_code == 200
    assert manifest.get_json()["artifacts"][0]["content_hash"] == (
        hashlib.sha256(raw).hexdigest()
    )
    assert loaded.status_code == 404
    assert archive.status_code == 404
    assert cleared.get_json()["deleted_files"] == 1
    assert not target.exists()
    assert job.status_code == 200
    assert job.get_json()["status"] == "succeeded"
    assert job.get_json()["compatibility"]["source"] == "research_jobs"
    assert job.get_json()["job_spec"]["run_spec"]["workspace_id"] == "workspace-1"
    task_detail = job.get_json()["task_detail"]
    assert task_detail["job"]["job_id"] == "job-full"
    assert task_detail["research_binding"] == {}
    assert task_detail["caller"]["channel"] == "unknown"
    assert task_detail["results"]["summary"] == {"success": True}
    assert task_detail["artifacts"][0]["content_type"] == "application/json"
    assert job.get_json()["has_terminal_assurance"] is True
    assert "terminal_assurance" not in job.get_json()
    assert (
        job.get_json()["evidence"]["terminal_assurance"]["disposition"]
        == "trusted"
    )
    assert repository.storage_usage(owner="alice") == 0


def test_user_can_delete_one_output_without_deleting_other_artifacts(
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
    _create_job(repository, job_id="job-delete-one", status=JobStatus.RUNNING)
    root = tmp_path / "artifacts" / "job-delete-one"
    root.mkdir(parents=True)
    for name, role in (("equity_curve_data", "output"), ("factor_source", "input")):
        target = root / f"{name}.json"
        raw = orjson.dumps({"name": name})
        target.write_bytes(raw)
        repository.record_artifact(
            job_id="job-delete-one",
            name=name,
            relative_path=str(target.relative_to(tmp_path / "artifacts")),
            content_type="application/json",
            content_hash=hashlib.sha256(raw).hexdigest(),
            size_bytes=len(raw),
            artifact_role=role,
        )

    deleted = client.delete(
        "/api/jobs/job-delete-one/artifacts/equity_curve_data"
    )
    input_delete = client.delete(
        "/api/jobs/job-delete-one/artifacts/factor_source"
    )
    manifest = client.get("/api/jobs/job-delete-one/artifacts").get_json()

    assert deleted.status_code == 200
    assert deleted.get_json()["artifact_name"] == "equity_curve_data"
    assert not (root / "equity_curve_data.json").exists()
    assert input_delete.status_code == 409
    assert (root / "factor_source.json").is_file()
    states = {item["name"]: item["state"] for item in manifest["artifacts"]}
    assert states == {"equity_curve_data": "deleted", "factor_source": "active"}


def test_artifact_manifest_preserves_distinct_input_logical_paths(
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
    _create_job(
        repository, job_id="job-input-archive", status=JobStatus.RUNNING,
    )
    root = tmp_path / "artifacts" / "job-input-archive" / "inputs"
    for index, logical_path in enumerate((
        "strategies/alpha/settings.yaml",
        "strategies/beta/settings.yaml",
    )):
        target = root / f"dependency-{index}.yaml"
        target.parent.mkdir(parents=True, exist_ok=True)
        raw = f"strategy: {index}\n".encode()
        target.write_bytes(raw)
        repository.record_artifact(
            job_id="job-input-archive",
            name=f"run_dependency__{index}",
            relative_path=str(target.relative_to(tmp_path / "artifacts")),
            content_type="application/yaml",
            content_hash=hashlib.sha256(raw).hexdigest(),
            size_bytes=len(raw),
            artifact_role="input",
            artifact_kind="run_dependency",
            file_name="settings.yaml",
            logical_path=logical_path,
            title_zh=f"策略配置 {index}",
        )

    response = client.get("/api/jobs/job-input-archive/artifacts")

    assert response.status_code == 200
    artifacts = response.get_json()["artifacts"]
    assert [item["logical_path"] for item in artifacts] == [
        "strategies/alpha/settings.yaml",
        "strategies/beta/settings.yaml",
    ]


def test_service_port_never_serves_public_artifact_bytes(
    tmp_path, monkeypatch,
) -> None:
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", tmp_path / "jobs.sqlite")
    monkeypatch.setenv("GTHT_JOB_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(sft_bp)
    client = app.test_client()
    with client.session_transaction() as session:
        session["manager_gateway_public_jobs"] = True

    repository = JobRepository()
    _create_job(repository, job_id="job-preview", status=JobStatus.RUNNING)
    target = tmp_path / "artifacts" / "job-preview" / "equity_curve_report.svg"
    target.parent.mkdir(parents=True)
    raw = b"<svg xmlns='http://www.w3.org/2000/svg'><path/></svg>"
    target.write_bytes(raw)
    repository.record_artifact(
        job_id="job-preview",
        name="equity_curve_report",
        relative_path="job-preview/equity_curve_report.svg",
        content_type="image/svg+xml",
        content_hash=hashlib.sha256(raw).hexdigest(),
        size_bytes=len(raw),
    )
    repository.transition(
        "job-preview", JobStatus.SUCCEEDED, result_summary={"success": True},
    )

    preview = client.get(
        "/api/jobs/job-preview/artifacts/equity_curve_report/preview",
    )
    download = client.get(
        "/api/jobs/job-preview/artifacts/equity_curve_report",
    )

    assert preview.status_code == 404
    assert download.status_code == 404


def test_public_gateway_cannot_discover_or_preview_job_input_source(
    tmp_path, monkeypatch,
) -> None:
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", tmp_path / "jobs.sqlite")
    monkeypatch.setenv("GTHT_JOB_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(sft_bp)
    client = app.test_client()
    with client.session_transaction() as session:
        session["manager_gateway_public_jobs"] = True

    repository = JobRepository()
    _create_job(repository, job_id="job-private-input", status=JobStatus.RUNNING)
    target = tmp_path / "artifacts" / "job-private-input" / "PrivateFactor.py"
    target.parent.mkdir(parents=True)
    raw = b"class PrivateFactor:\n    pass\n"
    target.write_bytes(raw)
    repository.record_artifact(
        job_id="job-private-input",
        name="factor_source__PrivateFactor",
        relative_path="job-private-input/PrivateFactor.py",
        content_type="text/x-python",
        content_hash=hashlib.sha256(raw).hexdigest(),
        size_bytes=len(raw),
        artifact_role="input",
        artifact_kind="factor_source",
        file_name="PrivateFactor.py",
        title_zh="临时因子源码：PrivateFactor",
    )

    detail = client.get("/api/jobs/job-private-input")
    manifest = client.get("/api/jobs/job-private-input/artifacts")
    preview = client.get(
        "/api/jobs/job-private-input/artifacts/"
        "factor_source__PrivateFactor/preview",
    )

    assert detail.status_code == 200
    assert detail.get_json()["task_detail"]["input_artifacts"] == []
    assert detail.get_json()["task_detail"]["run_input_dependency_policy"] is None
    assert detail.get_json()["task_detail"]["artifacts"] == []
    assert manifest.status_code == 200
    assert manifest.get_json()["artifacts"] == []
    assert preview.status_code == 404
    assert b"PrivateFactor" not in preview.data


def test_job_detail_declares_outputs_generated_after_the_run(
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
    job_repository = JobRepository()
    _create_job(job_repository, job_id="job-generated-ic", kind="ic")
    target = tmp_path / "artifacts" / "job-generated-ic" / "ic_statistics_summary_data.json"
    target.parent.mkdir(parents=True)
    raw = orjson.dumps({"columns": ["mean_ic"], "rows": [{"mean_ic": 0.1}]})
    target.write_bytes(raw)
    job_repository.record_derived_artifact(
        job_id="job-generated-ic",
        name="ic_statistics_summary_data",
        relative_path="job-generated-ic/ic_statistics_summary_data.json",
        content_type="application/json",
        content_hash=hashlib.sha256(raw).hexdigest(),
        size_bytes=len(raw),
    )

    response = client.get("/api/jobs/job-generated-ic")

    assert response.status_code == 200
    detail = response.get_json()["task_detail"]
    assert detail["generated_output_requests"] == ["ic_statistics"]
    assert {item["name"] for item in detail["output_declarations"]} >= {
        "ic_statistics", "ic_statistics_summary",
    }


def test_public_job_projection_redacts_nested_private_fields() -> None:
    class Job:
        job_spec = {
            "run_spec": {
                "configuration": {
                    "nested": {
                        "source_code": "private",
                        "password": "private",
                    },
                },
            },
            "transient_factor_source_scope_id": "private",
        }

    projected = _public_job_spec(Job())
    serialized = orjson.dumps(projected).decode()
    assert "private" not in serialized
    assert "source_code" not in serialized


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
