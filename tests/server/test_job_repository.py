from __future__ import annotations

import sqlite3
import time

import pytest

from server.jobs.models import JobRecord
from server.jobs.repository import JobRepository
from server.jobs.states import JobStatus


def _record(
    job_id: str,
    *,
    owner: str = "alice",
    status: JobStatus = JobStatus.SUBMITTED,
    step_mode: bool = False,
) -> JobRecord:
    return JobRecord(
        job_id=job_id,
        run_id="run-1",
        owner=owner,
        workspace_id="workspace-1",
        kind="backtest",
        status=status,
        step_mode=step_mode,
        deployment_id="issue-135",
        source_revision="abc123",
        created_at=time.time(),
    )


def test_repository_schema_contains_only_durable_job_facts(tmp_path) -> None:
    path = tmp_path / "jobs.sqlite"
    repository = JobRepository(path)
    repository.ensure_schema()

    with sqlite3.connect(path) as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        columns = {
            row[1] for row in conn.execute("PRAGMA table_info(research_jobs)")
        }

    assert tables >= {
        "research_jobs",
        "user_job_pins",
        "user_storage_policies",
        "research_job_artifacts",
    }
    assert "test_job_events" not in tables
    assert "research_view_leases" not in tables
    assert "latest_progress_json" not in columns
    assert "manifest_json" not in columns
    assert "initiator_page_uuid" not in columns
    assert "lifecycle_policy" not in columns


def test_repository_freezes_plan_and_enforces_transitions(tmp_path) -> None:
    repository = JobRepository(tmp_path / "jobs.sqlite")
    created = repository.create(_record("job-1"))
    planning = repository.transition(
        created.job_id,
        JobStatus.PLANNING,
        expected=JobStatus.SUBMITTED,
    )
    planned = repository.set_execution_plan(
        planning.job_id,
        plan={"products": ["A.DCE"], "frequency": "DAY1"},
        notices=[{"severity": "info", "code": "auto_source"}],
        requires_confirmation=True,
    )

    assert planned.status is JobStatus.AWAITING_CONFIRMATION
    assert planned.execution_plan_hash
    assert planned.plan_notices[0]["code"] == "auto_source"

    queued = repository.approve_plan(planned.job_id, owner="alice")
    running = repository.transition(
        queued.job_id,
        JobStatus.RUNNING,
        expected=JobStatus.QUEUED,
        worker_pid=123,
    )
    succeeded = repository.transition(
        running.job_id,
        JobStatus.SUCCEEDED,
        expected=JobStatus.RUNNING,
        result_summary={"success": True, "annual_return": 0.1},
    )

    assert succeeded.status is JobStatus.SUCCEEDED
    assert succeeded.result_summary == {"success": True, "annual_return": 0.1}
    with pytest.raises(ValueError, match="invalid job transition"):
        repository.transition(succeeded.job_id, JobStatus.RUNNING)


def test_repository_allows_one_step_job_and_one_replaceable_pin_per_user(tmp_path) -> None:
    repository = JobRepository(tmp_path / "jobs.sqlite")
    repository.create(_record("step-1", step_mode=True))
    with pytest.raises(ValueError, match="step job already active"):
        repository.create(_record("step-2", step_mode=True))

    for job_id in ("normal-1", "normal-2"):
        repository.create(_record(job_id))
        repository.transition(job_id, JobStatus.PLANNING)
        repository.set_execution_plan(
            job_id,
            plan={"products": []},
            notices=[],
            requires_confirmation=False,
        )

    repository.pin("normal-1", owner="alice")
    repository.pin("normal-2", owner="alice")
    assert repository.pinned_job_id(owner="alice") == "normal-2"

    repository.transition("normal-2", JobStatus.RUNNING)
    assert repository.pinned_job_id(owner="alice") == ""


def test_cancel_is_immediate_before_running_and_durable_while_running(tmp_path) -> None:
    repository = JobRepository(tmp_path / "jobs.sqlite")
    repository.create(_record("queued"))
    repository.transition("queued", JobStatus.PLANNING)
    repository.set_execution_plan(
        "queued", plan={"products": []}, notices=[], requires_confirmation=False
    )
    cancelled = repository.request_cancel(
        "queued", owner="alice", reason="explicit_cancel"
    )
    assert cancelled.status is JobStatus.CANCELLED
    assert cancelled.cancel_reason == "explicit_cancel"

    repository.create(_record("running"))
    repository.transition("running", JobStatus.PLANNING)
    repository.set_execution_plan(
        "running", plan={"products": []}, notices=[], requires_confirmation=False
    )
    repository.transition("running", JobStatus.RUNNING)
    requested = repository.request_cancel(
        "running", owner="alice", reason="explicit_cancel"
    )
    assert requested.status is JobStatus.RUNNING
    assert requested.cancel_requested_at is not None
