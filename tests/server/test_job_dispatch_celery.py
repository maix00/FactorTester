from __future__ import annotations

import pytest

from server.jobs.dispatch.celery_app import (
    DispatchExecutorUnavailable,
    create_app,
    execute_dispatch_payload,
    resolve_executor,
)
from server.jobs.dispatch.worker import ExecutionOutcome
from server.jobs.models import JobRecord
from server.jobs.repository.sqlite import JobRepository
from server.jobs.states import JobStatus


def _queued(repository: JobRepository, job_id: str = "job-celery") -> None:
    repository.create(
        JobRecord(
            job_id=job_id,
            run_id="run-celery",
            owner="owner",
            workspace_id="workspace",
            kind="backtest",
            status=JobStatus.SUBMITTED,
            deployment_id="remote-main",
            service_port=8001,
            run_spec_hash="a" * 64,
            job_spec={},
        )
    )
    repository.transition(job_id, JobStatus.PLANNING)
    repository.transition(job_id, JobStatus.QUEUED)


def _payload(job_id: str = "job-celery") -> dict:
    return {
        "schema_version": 2,
        "job_id": job_id,
        "attempt": 1,
        "deployment_id": "remote-main",
        "run_spec_hash": "a" * 64,
        "job_spec_hash": "b" * 64,
        "service_port": 8001,
    }


class _Executor:
    def execute(self, record, message, context):
        return ExecutionOutcome({"total_return": 0.2})


def test_celery_app_is_single_concurrency_and_json_only():
    pytest.importorskip("celery")
    app = create_app(broker_url="memory://", queue="q")
    assert app.conf.worker_prefetch_multiplier == 1
    assert app.conf.worker_concurrency == 1
    assert app.conf.worker_max_tasks_per_child == 1
    assert app.conf.worker_max_memory_per_child == 3_500_000
    assert app.conf.task_acks_late is False
    assert app.conf.task_serializer == "json"
    assert "factortester.execute_job" in app.tasks


def test_payload_reaches_worker_and_writes_result(tmp_path):
    repository = JobRepository(tmp_path / "jobs.db")
    _queued(repository)
    result = execute_dispatch_payload(
        _payload(), executor=_Executor(), repository=repository,
    )
    assert result["status"] == "succeeded"
    assert repository.require("job-celery").result_summary == {"total_return": 0.2}


def test_missing_executor_fails_before_job_claim(tmp_path, monkeypatch):
    repository = JobRepository(tmp_path / "jobs.db")
    _queued(repository)
    monkeypatch.setenv("FACTORTESTER_NAUTILUS_EXECUTOR", "missing.module:execute")
    with pytest.raises(DispatchExecutorUnavailable):
        execute_dispatch_payload(_payload(), repository=repository)
    assert repository.require("job-celery").status is JobStatus.QUEUED


def test_duplicate_task_is_idempotent(tmp_path):
    repository = JobRepository(tmp_path / "jobs.db")
    _queued(repository)
    execute_dispatch_payload(_payload(), executor=_Executor(), repository=repository)
    duplicate = execute_dispatch_payload(_payload(), executor=_Executor(), repository=repository)
    assert duplicate["status"] == "duplicate"


def test_resolve_executor_rejects_non_executor(monkeypatch):
    monkeypatch.setenv("FACTORTESTER_NAUTILUS_EXECUTOR", "server.jobs.dispatch.worker:ExecutionOutcome")
    with pytest.raises(DispatchExecutorUnavailable):
        resolve_executor()


def test_wrong_target_is_rejected_before_claim(tmp_path):
    repository = JobRepository(tmp_path / "jobs.db")
    _queued(repository)
    result = execute_dispatch_payload(
        _payload(), executor=_Executor(), repository=repository,
        target_deployment="remote-main", target_port=8002,
    )
    assert result["status"] == "wrong_target"
    assert repository.require("job-celery").status is JobStatus.QUEUED


def test_app_queue_is_scoped_to_deployment_and_port():
    pytest.importorskip("celery")
    app = create_app(broker_url="memory://", queue="q", target_deployment="remote-main", target_port=8001)
    assert app.conf.task_default_queue == "q.remote-main.8001"


def test_worker_app_uses_environment_target(monkeypatch):
    pytest.importorskip("celery")
    monkeypatch.setenv("FACTORTESTER_BROKER_URL", "memory://")
    monkeypatch.setenv("FACTORTESTER_DEPLOYMENT_ID", "remote-main")
    monkeypatch.setenv("FACTORTESTER_SERVICE_PORT", "8001")
    import importlib
    import server.jobs.dispatch.worker_app as worker_app

    module = importlib.reload(worker_app)
    assert module.app.conf.task_default_queue == "factortester.jobs.remote-main.8001"



def test_worker_app_registers_target_heartbeat(monkeypatch, tmp_path):
    pytest.importorskip("celery")
    import importlib, time
    monkeypatch.setenv("FACTORTESTER_BROKER_URL", "memory://")
    monkeypatch.setenv("FACTORTESTER_DEPLOYMENT_ID", "local-docker")
    monkeypatch.setenv("FACTORTESTER_SERVICE_PORT", "8001")
    monkeypatch.setenv("FACTORTESTER_JOB_DB", str(tmp_path / "jobs.db"))
    monkeypatch.setenv("FACTORTESTER_TARGET_HEARTBEAT_SECONDS", "5")
    import server.jobs.dispatch.worker_app as worker_app
    importlib.reload(worker_app)
    from server.jobs.repository.sqlite import JobRepository
    repository = JobRepository(tmp_path / "jobs.db")
    deadline = time.time() + 3
    while time.time() < deadline and not repository.worker_target_online("local-docker", 8001):
        time.sleep(0.05)
    assert repository.worker_target_online("local-docker", 8001)
