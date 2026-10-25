from __future__ import annotations

import hashlib

import orjson
import pytest

from server.jobs.assurance import canonical_hash
from server.jobs.dispatch.contract import DispatchMessage
from server.jobs.models import JobRecord
from server.jobs.states import JobStatus
from server.services.nautilus_bridge.job_executor import (
    NautilusJobExecutor,
    NautilusJobValidationError,
)
from server.services.research_run_identity import hash_run_spec


class _Context:
    job_id = "job-nautilus-celery"

    def __init__(self):
        self.progress = []
        self.cancelled = False

    def cancel_requested(self):
        return self.cancelled

    def report_progress(self, **value):
        self.progress.append(value)
        return True


def _job(*, runner_path="server.modules.single_factor_test.process_runners:run_group"):
    run_spec = {"run_spec_version": 10}
    job_spec = {"_owner": "owner", "run_spec": run_spec}
    plan = {"plan_version": 1, "kind": "backtest"}
    job_hash = hashlib.sha256(
        orjson.dumps(job_spec, option=orjson.OPT_SORT_KEYS)
    ).hexdigest()
    run_hash = hash_run_spec(run_spec)
    record = JobRecord(
        job_id="job-nautilus-celery",
        run_id="run-nautilus-celery",
        owner="owner",
        workspace_id="workspace",
        kind="backtest",
        status=JobStatus.RUNNING,
        attempt=2,
        deployment_id="local-feat",
        service_port=8000,
        runner_path=runner_path,
        job_spec=job_spec,
        job_spec_hash=job_hash,
        run_spec_hash=run_hash,
        execution_plan=plan,
        execution_plan_hash=canonical_hash(plan),
    )
    message = DispatchMessage(
        job_id=record.job_id,
        attempt=record.attempt,
        deployment_id=record.deployment_id,
        run_spec_hash=run_hash,
        job_spec_hash=job_hash,
        service_port=record.service_port,
    )
    return record, message


def test_celery_default_executor_resolves_to_nautilus_job_adapter(monkeypatch):
    monkeypatch.delenv("FACTORTESTER_NAUTILUS_EXECUTOR", raising=False)

    from server.jobs.dispatch.celery_app import resolve_executor

    executor = resolve_executor()
    assert isinstance(executor, NautilusJobExecutor)


def test_executor_projects_frozen_job_to_runner_and_persists_progress():
    record, message = _job()
    context = _Context()
    called = []

    def runner(payload, sink, cancel_event):
        called.append(payload)
        assert payload["run_spec"] == record.job_spec["run_spec"]
        assert payload["execution_plan"] == record.execution_plan
        assert not cancel_event.is_set()
        sink.emit_progress(1, 2, "event_replay", percent=30.0)
        sink.emit_result({"success": True, "orders": 3})

    outcome = NautilusJobExecutor(runner).execute(record, message, context)

    assert outcome.succeeded
    assert outcome.result_summary == {"success": True, "orders": 3}
    assert len(called) == 1
    assert context.progress[0] == {
        "sequence": 1,
        "phase": "event_replay",
        "completed": 1,
        "total": 2,
        "percent": 30.0,
        "message": "",
    }


def test_executor_rejects_mutated_run_spec_before_runner_call():
    record, message = _job()
    record.job_spec["run_spec"]["tampered"] = True
    called = []

    with pytest.raises(NautilusJobValidationError, match="job_spec hash"):
        NautilusJobExecutor(lambda *_: called.append(True)).execute(
            record, message, _Context(),
        )
    assert not called


def test_executor_maps_runner_error_to_failed_outcome():
    record, message = _job()

    def runner(_payload, sink, _cancel_event):
        sink.emit_error("factor replay is not enabled", error_code="nautilus_execution_unavailable")

    outcome = NautilusJobExecutor(runner).execute(record, message, _Context())
    assert not outcome.succeeded
    assert outcome.error == {
        "code": "nautilus_execution_unavailable",
        "message": "factor replay is not enabled",
    }


def test_executor_rejects_unbound_runner_path_before_execution():
    record, message = _job(runner_path="tools.testers.backtest:legacy_runner")
    called = []
    with pytest.raises(NautilusJobValidationError, match="not bound"):
        NautilusJobExecutor(lambda *_: called.append(True)).execute(
            record, message, _Context(),
        )
    assert not called
