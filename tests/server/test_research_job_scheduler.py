from __future__ import annotations

import hashlib
import time
from dataclasses import replace

import orjson

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
    run_spec = {
        "workspace_id": "workspace-1",
        "products": ["A.DCE"],
    }
    job_spec = {
        "run_id": f"run-{job_id}",
        "run_spec": run_spec,
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
        source_revision="test-backend-revision",
        runner_path=f"{RUNNERS}:{runner}",
        job_spec=job_spec,
        run_spec_hash=hashlib.sha256(
            orjson.dumps(run_spec, option=orjson.OPT_SORT_KEYS)
        ).hexdigest(),
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
    assert completed.worker_exitcode is None
    assert completed.result_summary["success"] is True
    assert completed.result_summary["pid"] == completed.worker_pid
    assert len(completed.execution_plan["cache_keys"]) == 1
    assert "A.DCE" in completed.execution_plan["cache_keys"][0]
    assert completed.terminal_assurance is not None
    assert completed.terminal_assurance.disposition == "trusted"
    assert events["latest_progress"]["event"] == "progress"


def test_live_progress_event_does_not_read_durable_repository(tmp_path, monkeypatch) -> None:
    repository = JobRepository(tmp_path / "jobs.sqlite")
    with ResearchJobScheduler(
        repository=repository,
        deployment_id="test",
        planner_workers=1,
        execution_workers=1,
    ) as scheduler:
        monkeypatch.setattr(
            repository,
            "load",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("live progress must not read durable repository")
            ),
        )
        scheduler._handle_event(
            "live-only",
            "progress",
            {"completed": 1, "total": 2},
            stage="execution",
        )
        snapshot = scheduler.broker.read("live-only")

    assert snapshot["events"][0]["event"] == "progress"


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


def test_pin_only_reorders_its_owner_queue_without_cross_user_priority(tmp_path) -> None:
    repository = JobRepository(tmp_path / "jobs.sqlite")
    bob = replace(
        _record("bob-first", owner="bob", runner="blocking_runner", seconds=30),
        created_at=time.time() - 10,
        entitlement=SchedulingEntitlement(priority_class="standard", weight=1.0),
    )
    alice_first = _record("alice-first", owner="alice")
    alice_pinned = _record("alice-pinned", owner="alice")
    for job in (bob, alice_first, alice_pinned):
        repository.create(job)
        repository.transition(job.job_id, JobStatus.PLANNING, expected=JobStatus.SUBMITTED)
        repository.set_execution_plan(
            job.job_id, plan={"cache_keys": []}, notices=[], requires_confirmation=False,
        )
    repository.pin("alice-pinned", owner="alice")

    with ResearchJobScheduler(
        repository=repository,
        deployment_id="test",
        planner_workers=1,
        execution_workers=1,
    ) as scheduler:
        scheduler.tick()

        assert repository.require("bob-first").status is JobStatus.RUNNING
        assert repository.require("alice-pinned").status is JobStatus.QUEUED

        repository.request_cancel("bob-first", owner="bob", reason="test_complete")
        _drive(scheduler, repository, "bob-first", {JobStatus.CANCELLED})
        scheduler.tick()

        assert repository.require("alice-pinned").status is JobStatus.RUNNING
        assert repository.require("alice-first").status is JobStatus.QUEUED


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
    assert cancelled.terminal_assurance is not None
    assert cancelled.terminal_assurance.disposition == "not_usable"
    assert crashed.error["code"] == "worker_crashed"
    assert crashed.worker_exitcode == 17
    assert crashed.terminal_assurance is not None
    assert crashed.terminal_assurance.disposition == "maintenance_required"
    assert "worker_crashed" in crashed.terminal_assurance.anomaly_codes


def test_cancel_requested_before_result_commit_wins_result_race(tmp_path) -> None:
    repository = JobRepository(tmp_path / "jobs.sqlite")
    repository.create(_record(
        "cancel-race",
        runner="cancel_result_race_runner",
        seconds=30,
    ))

    with ResearchJobScheduler(
        repository=repository,
        deployment_id="test",
        execution_workers=1,
    ) as scheduler:
        _drive(scheduler, repository, "cancel-race", {JobStatus.RUNNING})
        repository.request_cancel(
            "cancel-race", owner="alice", reason="explicit_cancel"
        )
        cancelled, _ = _drive(
            scheduler, repository, "cancel-race", {JobStatus.CANCELLED}
        )

    assert cancelled.cancel_reason == "explicit_cancel"
    assert cancelled.error["code"] == "cancelled_before_result_commit"
    assert cancelled.result_summary is None


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

    cancelled = repository.require("step-cancel")
    assert cancelled.status is JobStatus.CANCELLED
    assert cancelled.terminal_assurance is not None
    assert cancelled.terminal_assurance.disposition == "not_usable"
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
