from __future__ import annotations

import time
from dataclasses import replace

from server.jobs.models import JobRecord, SchedulingEntitlement
from server.jobs.repository import JobRepository
from server.jobs.scheduling import ResearchJobScheduler
from server.jobs.states import JobStatus


RUNNERS = "tests.server.long_lived_worker_fakes"


def _record(
    job_id: str,
    *,
    runner: str = "planned_cpu_runner",
    owner: str = "alice",
    loops: int = 50_000,
    seconds: float | None = None,
) -> JobRecord:
    job_spec = {
        "run_id": f"run-{job_id}",
        "loops": loops,
        "product_selections": {
            "core": {
                "selected_paths": [
                    {"product": "A.DCE", "source": "CNFutures", "frequency": "DAY1"}
                ]
            }
        },
    }
    if seconds is not None:
        job_spec["seconds"] = seconds
    return JobRecord(
        job_id=job_id,
        run_id=f"run-{job_id}",
        owner=owner,
        workspace_id="workspace-1",
        kind="fake",
        status=JobStatus.SUBMITTED,
        deployment_id="test",
        runner_path=f"{RUNNERS}:{runner}",
        job_spec=job_spec,
        entitlement=SchedulingEntitlement(max_concurrency=1),
        created_at=time.time(),
    )


def _drive(scheduler, repository, job_id, statuses, *, timeout=8.0):
    deadline = time.monotonic() + timeout
    seen = []
    while time.monotonic() < deadline:
        scheduler.tick()
        current = repository.require(job_id)
        seen.append(current.status)
        if current.status in statuses:
            return current, seen
        time.sleep(0.01)
    raise AssertionError(f"job did not reach {statuses}: {repository.require(job_id)}")


def test_scheduler_plans_and_executes_real_job_in_child_process(tmp_path) -> None:
    repository = JobRepository(tmp_path / "jobs.sqlite")
    repository.create(_record("success"))

    with ResearchJobScheduler(
        repository=repository,
        deployment_id="test",
        planner_workers=1,
        execution_workers=1,
    ) as scheduler:
        completed, seen = _drive(
            scheduler, repository, "success", {JobStatus.SUCCEEDED}
        )
        events = scheduler.broker.read("success")

    assert JobStatus.PLANNING in seen
    assert JobStatus.RUNNING in seen
    assert completed.worker_pid is not None
    assert completed.worker_pid != 0
    assert completed.result_summary["success"] is True
    assert completed.result_summary["pid"] == completed.worker_pid
    assert len(completed.execution_plan["cache_keys"]) == 1
    assert "A.DCE" in completed.execution_plan["cache_keys"][0]
    assert events["latest_progress"]["event"] == "progress"


def test_scheduler_respects_per_user_concurrency_and_runs_queued_job_next(tmp_path) -> None:
    repository = JobRepository(tmp_path / "jobs.sqlite")
    repository.create(_record("first", runner="blocking_runner", seconds=30))
    repository.create(_record("second"))

    with ResearchJobScheduler(
        repository=repository,
        deployment_id="test",
        planner_workers=2,
        execution_workers=2,
    ) as scheduler:
        first, _ = _drive(scheduler, repository, "first", {JobStatus.RUNNING})
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            scheduler.tick()
            second = repository.require("second")
            if second.status is JobStatus.QUEUED:
                break
            time.sleep(0.01)
        assert first.status is JobStatus.RUNNING
        assert repository.require("second").status is JobStatus.QUEUED
        repository.request_cancel("first", owner="alice", reason="explicit_cancel")
        _drive(scheduler, repository, "first", {JobStatus.CANCELLED})
        second, _ = _drive(scheduler, repository, "second", {JobStatus.SUCCEEDED})

    assert second.status is JobStatus.SUCCEEDED


def test_scheduler_persists_failure_cancel_and_worker_crash(tmp_path) -> None:
    repository = JobRepository(tmp_path / "jobs.sqlite")
    repository.create(_record("cancel", runner="blocking_runner", seconds=30))
    repository.create(_record("crash", runner="crash_runner", owner="bob"))

    with ResearchJobScheduler(
        repository=repository,
        deployment_id="test",
        execution_workers=2,
        cancel_grace_seconds=0.05,
    ) as scheduler:
        _drive(scheduler, repository, "cancel", {JobStatus.RUNNING})
        repository.request_cancel("cancel", owner="alice", reason="explicit_cancel")
        cancelled, _ = _drive(
            scheduler, repository, "cancel", {JobStatus.CANCELLED}
        )
        crashed, _ = _drive(
            scheduler, repository, "crash", {JobStatus.FAILED}
        )

    assert cancelled.cancel_reason == "explicit_cancel"
    assert cancelled.error["cancelled"] is True
    assert crashed.error["code"] == "worker_crashed"
    assert crashed.worker_exitcode == 17


def test_full_result_uses_files_and_over_quota_cancels_waiting_not_running(tmp_path) -> None:
    repository = JobRepository(tmp_path / "jobs.sqlite")
    first = _record("full", runner="artifact_runner")
    first = replace(
        first,
        retention_mode="full",
        job_spec={**first.job_spec, "size": 200_000},
    )
    repository.create(first)
    repository.create(_record("waiting"))
    repository.set_storage_quota(owner="alice", quota_bytes=1)
    artifact_dir = tmp_path / "artifacts"

    with ResearchJobScheduler(
        repository=repository,
        deployment_id="test",
        execution_workers=1,
        result_artifact_root=str(artifact_dir),
    ) as scheduler:
        completed, _ = _drive(
            scheduler, repository, "full", {JobStatus.SUCCEEDED}
        )
        waiting = repository.require("waiting")

    assert completed.status is JobStatus.SUCCEEDED
    assert completed.result_summary["summary_truncated"] is True
    assert "equity_curve" not in completed.result_summary
    assert waiting.status is JobStatus.CANCELLED
    assert waiting.cancel_reason == "storage_quota_exceeded"
    artifacts = repository.list_artifacts(job_id="full", owner="alice")
    assert {item["name"] for item in artifacts} == {"details", "result"}
    assert all((artifact_dir / item["relative_path"]).is_file() for item in artifacts)


def test_step_job_pauses_and_continues_in_same_worker_process(tmp_path) -> None:
    repository = JobRepository(tmp_path / "jobs.sqlite")
    job = replace(_record("step", runner="pausing_runner"), step_mode=True)
    repository.create(job)

    with ResearchJobScheduler(
        repository=repository,
        deployment_id="test",
        execution_workers=1,
    ) as scheduler:
        first, _ = _drive(scheduler, repository, "step", {JobStatus.PAUSED})
        pid = first.worker_pid
        assert scheduler.continue_step("step", {"action": "continue"}) is True
        second, _ = _drive(scheduler, repository, "step", {JobStatus.PAUSED})
        assert second.worker_pid == pid
        assert scheduler.continue_step("step", {"action": "end"}) is True
        completed, _ = _drive(scheduler, repository, "step", {JobStatus.SUCCEEDED})

    assert completed.worker_pid == pid
    assert completed.result_summary["pid"] == pid
    assert completed.result_summary["seen"] == [0, 1]


def test_paused_step_job_cancels_and_releases_its_worker(tmp_path) -> None:
    repository = JobRepository(tmp_path / "jobs.sqlite")
    repository.create(replace(
        _record("step-cancel", runner="pausing_runner"), step_mode=True
    ))

    with ResearchJobScheduler(
        repository=repository,
        deployment_id="test",
        execution_workers=1,
    ) as scheduler:
        paused, _ = _drive(
            scheduler, repository, "step-cancel", {JobStatus.PAUSED}
        )
        pid = paused.worker_pid
        repository.request_cancel(
            "step-cancel", owner="alice", reason="explicit_cancel"
        )
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            scheduler.tick()
            if scheduler.executors.worker_snapshot()[0]["job_id"] == "":
                break
            time.sleep(0.01)
        repository.create(_record("after-cancel"))
        completed, _ = _drive(
            scheduler, repository, "after-cancel", {JobStatus.SUCCEEDED}
        )

    assert repository.require("step-cancel").status is JobStatus.CANCELLED
    assert completed.worker_pid == pid


def test_drain_finishes_active_work_without_starting_queued_jobs(tmp_path) -> None:
    repository = JobRepository(tmp_path / "jobs.sqlite")
    repository.create(_record("draining", runner="blocking_runner", seconds=0.2))
    repository.create(_record("held"))

    with ResearchJobScheduler(
        repository=repository,
        deployment_id="test",
        planner_workers=2,
        execution_workers=1,
    ) as scheduler:
        _drive(scheduler, repository, "draining", {JobStatus.RUNNING})
        deadline = time.monotonic() + 3
        while repository.require("held").status is not JobStatus.QUEUED:
            scheduler.tick()
            assert time.monotonic() < deadline
            time.sleep(0.01)
        scheduler.set_draining(True)
        finished, _ = _drive(
            scheduler, repository, "draining", {JobStatus.SUCCEEDED}
        )
        for _ in range(10):
            scheduler.tick()

    assert finished.status is JobStatus.SUCCEEDED
    assert repository.require("held").status is JobStatus.QUEUED
