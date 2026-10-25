from __future__ import annotations

from server.jobs.dispatch.contract import DispatchMessage
from server.jobs.dispatch.executors import JobExecutorRouter, ProcessRunnerExecutor
from server.jobs.dispatch.worker import ExecutionOutcome
from server.jobs.models import JobRecord
from server.jobs.states import JobStatus


class _Context:
    def __init__(self):
        self.values = []
        self.cancelled = False

    def cancel_requested(self):
        return self.cancelled

    def report_progress(self, **value):
        self.values.append(value)
        return True


def _job(kind: str) -> JobRecord:
    return JobRecord(
        job_id="job-executor", run_id="run", owner="owner", workspace_id="ws",
        kind=kind, status=JobStatus.RUNNING, attempt=1,
        deployment_id="local", service_port=8001, job_spec={"run_spec": {}},
    )


def _message() -> DispatchMessage:
    return DispatchMessage("job-executor", 1, "local", "a" * 64, "b" * 64, 8001)


def test_process_executor_routes_ic_and_persists_progress():
    def runner(payload, sink, cancel):
        assert payload["kind"] == "ic"
        sink.emit_start(total=2, phase="compute")
        sink.emit_progress(1, 2, "compute", percent=50)
        sink.emit_result({"ic": 0.1})

    context = _Context()
    outcome = ProcessRunnerExecutor({"ic": runner}).execute(_job("ic"), _message(), context)
    assert outcome.succeeded
    assert outcome.result_summary == {"ic": 0.1}
    assert context.values[-1]["percent"] == 100.0


def test_process_executor_cancel_and_unknown_kind():
    context = _Context()
    outcome = ProcessRunnerExecutor({}).execute(_job("ic"), _message(), context)
    assert not outcome.succeeded
    assert outcome.error["code"] == "unsupported_job_kind"
    context.cancelled = True
    outcome = ProcessRunnerExecutor({"ic": lambda *_: None}).execute(
        _job("ic"), _message(), context,
    )
    assert outcome.cancelled


def test_router_uses_backtest_executor_for_backtest():
    class Backtest:
        def execute(self, record, message, context):
            return ExecutionOutcome({"engine": "backtest"})

    router = JobExecutorRouter(backtest=Backtest(), process=ProcessRunnerExecutor({}))
    outcome = router.execute(_job("backtest"), _message(), _Context())
    assert outcome.result_summary == {"engine": "backtest"}
