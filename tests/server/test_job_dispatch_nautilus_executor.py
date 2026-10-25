from __future__ import annotations

import hashlib
from pathlib import Path

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


def test_real_nautilus_catalog_replay_runs_through_dispatch_worker(tmp_path, monkeypatch):
    pytest = __import__("pytest")
    pytest.importorskip("pyarrow")
    from tests.nautilus_runtime import require_nautilus
    from tests.server.test_nautilus_bridge_backtest_runner import _real_catalog

    require_nautilus()
    catalog = _real_catalog(tmp_path, count=8)
    monkeypatch.setenv("FACTORTESTER_NAUTILUS_CATALOG_ROOT", str(tmp_path))
    run_spec = {"run_spec_version": 10}
    plan = {
        "plan_version": 1,
        "kind": "nautilus_catalog_replay",
        "catalog_inputs": [{
            "catalog_dir": str(catalog.catalog_dir),
            "contract_uid": catalog.expected_contract_uid,
        }],
        "max_input_bars": 8,
        "batch_minutes": 3,
    }
    repository = JobRepository(tmp_path / "jobs.db")
    record = JobRecord(
        job_id="job-nautilus-replay", run_id="run-nautilus-replay",
        owner="owner", workspace_id="workspace", kind="backtest",
        status=JobStatus.SUBMITTED, deployment_id="local-feature",
        service_port=8001,
        runner_path="server.modules.single_factor_test.process_runners:run_group",
        job_spec={"owner": "owner", "run_spec": run_spec},
        run_spec_hash=hash_run_spec(run_spec),
        execution_plan=plan, execution_plan_hash=canonical_hash(plan),
    )
    repository.create(record)
    repository.transition(record.job_id, JobStatus.PLANNING)
    repository.transition(record.job_id, JobStatus.QUEUED)
    message = DispatchOutbox(tmp_path / "jobs.db").get((record.job_id, 1)).message

    result = DispatchWorker(repository).execute(message, NautilusJobExecutor())
    assert result["status"] == "succeeded"
    terminal = repository.require(record.job_id)
    assert terminal.status is JobStatus.SUCCEEDED
    assert terminal.result_summary["input_bars"] == 8
    assert terminal.result_summary["native_iterations"] == 8
    assert Path(terminal.result_summary["reports_dir"]).is_dir()
