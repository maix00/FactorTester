from __future__ import annotations

import hashlib

import orjson

from server.jobs.assurance import canonical_hash
from server.jobs.dispatch import DispatchMessage, DispatchOutbox
from server.jobs.dispatch.worker import DispatchWorker
from server.jobs.models import JobRecord
from server.jobs.repository.sqlite import JobRepository
from server.jobs.states import JobStatus
from server.services.nautilus_bridge.job_executor import NautilusJobExecutor
from server.services.research_run_identity import hash_run_spec


def test_queued_job_runs_through_nautilus_executor_adapter(tmp_path):
    run_spec = {"run_spec_version": 10}
    plan = {"plan_version": 1, "kind": "backtest"}
    job_spec = {"owner": "owner", "run_spec": run_spec}
    repository = JobRepository(tmp_path / "jobs.db")
    record = JobRecord(
        job_id="job-nautilus-queue",
        run_id="run-nautilus-queue",
        owner="owner",
        workspace_id="workspace",
        kind="backtest",
        status=JobStatus.SUBMITTED,
        deployment_id="local-feature",
        service_port=8001,
        runner_path="server.modules.single_factor_test.process_runners:run_group",
        job_spec=job_spec,
        run_spec_hash=hash_run_spec(run_spec),
        execution_plan=plan,
        execution_plan_hash=canonical_hash(plan),
    )
    repository.create(record)
    repository.transition(record.job_id, JobStatus.PLANNING)
    repository.transition(record.job_id, JobStatus.QUEUED)
    outbox = DispatchOutbox(tmp_path / "jobs.db")
    message = outbox.get((record.job_id, 1)).message

    calls = []

    def runner(payload, sink, cancel_event):
        calls.append(payload)
        sink.emit_progress(1, 2, "event_replay", percent=50.0)
        sink.emit_result({"success": True, "orders": 3})

    worker = DispatchWorker(repository)
    result = worker.execute(message, NautilusJobExecutor(runner))
    assert result["status"] == "succeeded"
    assert len(calls) == 1
    terminal = repository.require(record.job_id)
    assert terminal.status is JobStatus.SUCCEEDED
    assert terminal.result_summary == {"success": True, "orders": 3}
    assert repository.progress(record.job_id, 1)["percent"] == 100.0
