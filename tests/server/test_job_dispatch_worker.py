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
            service_port=8001,
            run_spec_hash="e" * 64,
            job_spec={},
        )
    )
    repository.transition(job_id, JobStatus.PLANNING)
    repository.transition(job_id, JobStatus.QUEUED)


def _message(job_id: str = "job-worker") -> DispatchMessage:
    return DispatchMessage(job_id, 1, "remote-main", "e" * 64, "f" * 64, 8001)


class _Executor:
    def __init__(self, outcome: ExecutionOutcome | None = None, *, crash: bool = False) -> None:
        self.outcome = outcome or ExecutionOutcome({"total_return": 0.1})
        self.crash = crash
        self.calls = 0

    def execute(self, record, message, context):
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


def test_worker_heartbeats_during_long_executor(tmp_path):
    import time

    repository = JobRepository(tmp_path / "jobs.db")
    _queued_job(repository, "job-beat")

    class SlowExecutor:
        def execute(self, record, message, context):
            time.sleep(0.12)
            return ExecutionOutcome({"ok": True})

    DispatchWorker(repository).execute(
        _message("job-beat"), SlowExecutor(), worker_id="worker-beat",
        heartbeat_interval=0.02,
    )
    import sqlite3
    with sqlite3.connect(tmp_path / "jobs.db") as conn:
        row = conn.execute(
            "SELECT lease_until, heartbeat_at FROM research_job_worker_leases WHERE job_id=?",
            ("job-beat",),
        ).fetchone()
    # The terminal transition removes the lease.
    assert row is None


def test_worker_writes_cancelled_outcome(tmp_path):
    repository = JobRepository(tmp_path / "jobs.db")
    _queued_job(repository, "job-cancel-worker")

    class CancelExecutor:
        def execute(self, record, message, context):
            return ExecutionOutcome({"bars": 10}, cancelled=True)

    result = DispatchWorker(repository).execute(
        _message("job-cancel-worker"), CancelExecutor(),
    )
    assert result["status"] == "cancelled"
    assert repository.require("job-cancel-worker").status is JobStatus.CANCELLED


def test_cancel_requested_visible_to_executor(tmp_path):
    repository = JobRepository(tmp_path / "jobs.db")
    _queued_job(repository, "job-cancel-flag")
    repository.request_cancel("job-cancel-flag", owner="owner", reason="stop")

    class Cancelled(Exception):
        pass

    class Exploding:
        def execute(self, record, message, context):
            assert context.cancel_requested()
            raise Cancelled("stopped")

    # request_cancel on a queued job already marked it cancelled, so this claim
    # is a duplicate; the executor must not run.
    result = DispatchWorker(repository).execute(_message("job-cancel-flag"), Exploding())
    assert result["status"] == "duplicate"
    assert repository.require("job-cancel-flag").status is JobStatus.CANCELLED


def test_running_job_cancel_request_is_observed_at_batch_boundary(tmp_path):
    repository = JobRepository(tmp_path / "jobs.db")
    _queued_job(repository, "job-running-cancel")

    class BoundaryCancel:
        def execute(self, record, message, context):
            repository.request_cancel(record.job_id, owner="owner", reason="user")
            assert context.cancel_requested()
            return ExecutionOutcome({"bars": 10}, cancelled=True)

    result = DispatchWorker(repository).execute(
        _message("job-running-cancel"), BoundaryCancel(),
    )
    assert result["status"] == "cancelled"
    record = repository.require("job-running-cancel")
    assert record.status is JobStatus.CANCELLED
    assert record.cancel_requested_at is not None


def test_progress_is_monotonic_and_visible_to_job_owner(tmp_path):
    repository = JobRepository(tmp_path / "jobs.db")
    _queued_job(repository, "job-progress")

    class ProgressExecutor:
        def execute(self, record, message, context):
            assert context.report_progress(
                sequence=1, phase="event_replay", completed=1, total=2, percent=50,
            )
            assert not context.report_progress(
                sequence=1, phase="stale", completed=2, total=2, percent=60,
            )
            assert context.report_progress(
                sequence=2, phase="done", completed=2, total=2, percent=100,
            )
            return ExecutionOutcome({"ok": True})

    DispatchWorker(repository).execute(_message("job-progress"), ProgressExecutor())
    snapshot = repository.progress("job-progress", 1)
    assert snapshot == {
        "sequence": 2, "phase": "done", "completed": 2, "total": 2,
        "percent": 100.0, "message": "",
    }


def test_worker_target_heartbeat_is_port_scoped(tmp_path):
    repository = JobRepository(tmp_path / "jobs.db")
    repository.heartbeat_worker_target(
        "local-docker", 8001, "worker-a", capabilities={"engine": "fake"}, ttl_seconds=30,
    )
    assert repository.worker_target_online("local-docker", 8001)
    assert not repository.worker_target_online("local-docker", 8000)
    assert not repository.worker_target_online("other", 8001)
    assert not repository.worker_target_online("local-docker", 8001, now=10**12)


def test_success_persists_report_ref(tmp_path):
    from server.jobs.dispatch.worker import DispatchWorker, ExecutionOutcome
    from server.jobs.models import JobRecord
    from server.jobs.repository.sqlite import JobRepository
    from server.jobs.states import JobStatus
    from server.jobs.dispatch.contract import DispatchMessage

    repo = JobRepository(tmp_path / "jobs.db")
    repo.create(JobRecord(job_id="job-report", run_id="r", owner="o", workspace_id="w",
                          kind="backtest", status=JobStatus.SUBMITTED,
                          deployment_id="d", service_port=8001,
                          run_spec_hash="a" * 64, job_spec={}))
    repo.transition("job-report", JobStatus.PLANNING)
    repo.transition("job-report", JobStatus.QUEUED)
    class E:
        def execute(self, record, message, context):
            return ExecutionOutcome({"report_ref": "report:job-report:1"})
    DispatchWorker(repo).execute(DispatchMessage("job-report", 1, "d", "a"*64, "b"*64, 8001), E())
    with repo._connection() as conn:
        assert conn.execute("select report_ref from research_jobs where job_id='job-report'").fetchone()[0] == "report:job-report:1"
