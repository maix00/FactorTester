from __future__ import annotations

from server.jobs.dispatch import DispatchMessage, DispatchOutbox
from server.jobs.dispatch.worker import DispatchWorker, ExecutionOutcome
from server.jobs.models import JobRecord
from server.jobs.repository.sqlite import JobRepository
from server.jobs.states import JobStatus


def _queued_job(repository: JobRepository, job_id: str = "job-worker") -> None:
    repository.create(
        JobRecord(
            job_id=job_id,
            run_id="run-worker",
            owner="owner",
            workspace_id="workspace",
            kind="backtest",
            status=JobStatus.SUBMITTED,
            deployment_id="remote-main",
            run_spec_hash="e" * 64,
            job_spec={},
        )
    )
    repository.transition(job_id, JobStatus.PLANNING)
    repository.transition(job_id, JobStatus.QUEUED)


def _message(job_id: str = "job-worker") -> DispatchMessage:
    return DispatchMessage(job_id, 1, "remote-main", "e" * 64, "f" * 64)


class _Executor:
    def __init__(self, outcome: ExecutionOutcome | None = None, *, crash: bool = False) -> None:
        self.outcome = outcome or ExecutionOutcome({"total_return": 0.1})
        self.crash = crash
        self.calls = 0

    def execute(self, record, message):
        self.calls += 1
        if self.crash:
            raise RuntimeError("engine crashed")
        return self.outcome


def test_worker_claims_executes_and_completes(tmp_path):
    repository = JobRepository(tmp_path / "jobs.db")
    _queued_job(repository)
    executor = _Executor()
    result = DispatchWorker(repository).execute(_message(), executor, worker_pid=7)
    assert result["status"] == "succeeded"
    assert executor.calls == 1
    record = repository.require("job-worker")
    assert record.status is JobStatus.SUCCEEDED
    assert record.result_summary == {"total_return": 0.1}


def test_worker_duplicate_does_not_execute_again(tmp_path):
    repository = JobRepository(tmp_path / "jobs.db")
    _queued_job(repository)
    executor = _Executor()
    worker = DispatchWorker(repository)
    assert worker.execute(_message(), executor)["status"] == "succeeded"
    assert worker.execute(_message(), executor)["status"] == "duplicate"
    assert executor.calls == 1


def test_worker_executor_exception_fails_job(tmp_path):
    repository = JobRepository(tmp_path / "jobs.db")
    _queued_job(repository)
    result = DispatchWorker(repository).execute(_message(), _Executor(crash=True))
    assert result["status"] == "failed"
    record = repository.require("job-worker")
    assert record.status is JobStatus.FAILED
    assert record.error["code"] == "worker_execution_failed"


def test_worker_reported_error_fails_job(tmp_path):
    repository = JobRepository(tmp_path / "jobs.db")
    _queued_job(repository)
    outcome = ExecutionOutcome({"bars": 0}, error={"code": "unsupported_capability", "message": "x"})
    result = DispatchWorker(repository).execute(_message(), _Executor(outcome))
    assert result["status"] == "failed"
    record = repository.require("job-worker")
    assert record.error["code"] == "unsupported_capability"


def test_outbox_message_still_pending_is_independent_of_execution(tmp_path):
    outbox = DispatchOutbox(tmp_path / "jobs.db")
    outbox.enqueue(_message(), now=100.0)
    repository = JobRepository(tmp_path / "jobs.db")
    _queued_job(repository)
    # A direct worker execution does not fabricate broker confirmation.
    DispatchWorker(repository).execute(_message(), _Executor())
    assert outbox.get(("job-worker", 1)).status == "pending"
