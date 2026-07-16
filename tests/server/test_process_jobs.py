from __future__ import annotations

import os
import time
import uuid

from server.services import test_job_store, test_jobs


RUNNER = "tests.server.process_job_fakes"


def _job(kind: str = "process-test"):
    token = f"{kind}-{uuid.uuid4().hex}"
    return test_jobs.create_job(
        kind=kind,
        run_token=token,
        run_id=token,
        workspace_id="workspace-process",
        lifecycle_policy="durable",
        owner="alice",
        payload={"run_token": token, "run_id": token, "workspace_id": "workspace-process"},
    )


def _wait(job, statuses: set[str] | None = None, *, timeout: float = 8.0) -> None:
    statuses = statuses or test_jobs.TERMINAL_STATUSES
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if job.status in statuses and job.closed:
            return
        time.sleep(0.02)
    raise AssertionError(f"job did not reach {statuses}: {job.summary()}")


def _wait_until(predicate, *, timeout: float = 8.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("condition was not met")


def test_process_job_runs_cpu_bound_runner_in_child_pid() -> None:
    job = _job()
    test_jobs.submit_process(job, f"{RUNNER}:cpu_bound_success", {"total": 50000})

    _wait(job)

    assert job.status == "succeeded"
    assert job.execution_mode == "process"
    assert job.worker_pid is not None
    assert job.worker_pid != os.getpid()
    assert job.result is not None
    assert job.result["pid"] == job.worker_pid
    assert job.worker_exitcode == 0
    assert any(event.event == "worker" for event in job.events_after())
    assert any(event.event == "progress" for event in job.events_after())


def test_process_job_concurrency_limit_leaves_excess_job_queued() -> None:
    semantics = test_jobs.deployment_semantics()
    concurrent = min(int(semantics["thread_workers"]), int(semantics["process_workers"]))
    jobs = [_job("queue-test") for _ in range(concurrent + 1)]
    for job in jobs:
        test_jobs.submit_process(job, f"{RUNNER}:slow_success", {"duration": 0.6})

    _wait_until(lambda: sum(1 for job in jobs if job.status == "running") >= concurrent)
    queued = [job for job in jobs if job.status == "queued"]
    assert queued, [job.summary() for job in jobs]

    for job in jobs:
        _wait(job)
    assert {job.status for job in jobs} == {"succeeded"}
    assert len({job.worker_pid for job in jobs}) == 3


def test_process_job_cancel_is_cross_process_and_readable() -> None:
    job = _job("cancel-test")
    test_jobs.submit_process(job, f"{RUNNER}:waits_for_cancel", {"timeout": 5.0})

    _wait_until(lambda: job.status == "running" and job.worker_pid is not None)
    # Simulate a cancel request accepted by another Flask worker that has no
    # access to this process-local TestJob object.
    requested, status = test_job_store.request_cancel(
        job_id=job.job_id, owner="alice", reason="explicit_cancel",
    )
    assert requested is True
    assert status == "running"
    _wait(job)

    assert job.status == "cancelled"
    assert job.error is not None
    assert job.error["cancelled"] is True
    assert job.process is not None
    assert not job.process.is_alive()


def test_process_job_failure_serializes_error_and_traceback() -> None:
    job = _job("failure-test")
    test_jobs.submit_process(job, f"{RUNNER}:raises_error", {"message": "process boom"})

    _wait(job)

    assert job.status == "failed"
    assert job.error is not None
    assert job.error["error"] == "process boom"
    assert "RuntimeError: process boom" in job.error["traceback"]
    assert job.worker_exitcode == 0


def test_process_job_worker_crash_is_reported_as_failure() -> None:
    job = _job("crash-test")
    test_jobs.submit_process(job, f"{RUNNER}:crashes", {"exitcode": 7})

    _wait(job)

    assert job.status == "failed"
    assert job.worker_exitcode == 7
    assert job.error is not None
    assert "worker process exited with code 7" in job.error["error"]


def test_dead_dispatcher_is_reconciled_after_restart() -> None:
    job = _job("dispatcher-crash-test")
    job.start()
    job.dispatcher_pid = 99999999
    test_job_store.update_job_record(job)

    assert test_job_store.reconcile_orphaned_jobs() >= 1
    durable = test_job_store.load_job(job.job_id)

    assert durable is not None
    assert durable.status == "failed"
    assert durable.error is not None
    assert durable.error["worker_crash"] is True


def test_paused_process_releases_worker_and_remains_cancellable() -> None:
    job = _job("paused-test")
    test_jobs.submit_process(job, f"{RUNNER}:pauses", {"flow_index": 7})

    _wait(job, {"paused"})

    assert job.status == "paused"
    assert job.checkpoint == {"flow_index": 7, "flow_id": "signal"}
    assert job.process is not None and not job.process.is_alive()
    assert test_jobs.cancel(job.job_id, "alice") is True
    assert job.status == "cancelled"


def test_thread_submit_compatibility_path_is_unchanged() -> None:
    job = _job("thread-test")

    def _target(sink):
        sink.emit_result({"success": True, "pid": os.getpid()})

    test_jobs.submit(job, _target).result(timeout=3)
    _wait(job)

    assert job.status == "succeeded"
    assert job.execution_mode == "thread"
    assert job.worker_pid is None
    assert job.result is not None
    assert job.result["success"] is True
    assert job.result["pid"] == os.getpid()
    assert job.result["job_id"] == job.job_id


def test_process_payload_rejects_non_serializable_objects() -> None:
    job = _job("bad-payload-test")

    try:
        test_jobs.submit_process(job, f"{RUNNER}:cpu_bound_success", {"bad": lambda x: x})
    except ValueError as exc:
        assert "pickle-serializable" in str(exc)
    else:
        raise AssertionError("non-serializable process payload should fail")


def test_deployment_semantics_are_explicit() -> None:
    semantics = test_jobs.deployment_semantics()

    assert semantics["registry"] == "sqlite_canonical_with_process_local_live_cache"
    assert semantics["restart_persistent"] is True
    assert semantics["cross_flask_worker_visible"] is True
    assert semantics["requires_sticky_routing"] is False
    assert semantics["process_worker_limit_scope"].startswith("global")
    assert "no Flask/page objects" in semantics["process_runner_contract"]
