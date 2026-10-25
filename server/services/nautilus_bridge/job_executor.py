"""Celery JobAttempt adapter for the frozen Nautilus backtest runner.

Only the durable Job identity crosses RabbitMQ. This adapter checks that
identity, then passes the repository-owned frozen inputs to the approved
Nautilus runner. It does not create a second queue or copy market data.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import threading
import uuid
from typing import Any

import orjson

from server.jobs.artifacts import artifact_root
from server.jobs.assurance import canonical_hash
from server.jobs.dispatch.contract import DispatchMessage
from server.jobs.dispatch.worker import ExecutionContext, ExecutionOutcome
from server.jobs.models import JobRecord
from server.services.research_run_identity import (
    NAUTILUS_RUN_SPEC_VERSION,
    hash_run_spec,
)


class NautilusJobValidationError(ValueError):
    """A durable JobAttempt no longer matches its dispatched identity."""


def _verify_dispatch(record: JobRecord, message: DispatchMessage) -> dict[str, Any]:
    if record.kind != "backtest":
        raise NautilusJobValidationError("Nautilus executor only accepts backtest Jobs")
    if (record.job_id, record.attempt) != message.identity:
        raise NautilusJobValidationError("dispatch identity differs from the claimed JobAttempt")
    if record.deployment_id != message.deployment_id:
        raise NautilusJobValidationError("dispatch deployment differs from the JobAttempt")
    if record.service_port != message.service_port:
        raise NautilusJobValidationError("dispatch service port differs from the JobAttempt")
    if not record.job_spec or not record.job_spec_hash:
        raise NautilusJobValidationError("JobAttempt has no immutable job specification")
    job_hash = hashlib.sha256(
        orjson.dumps(record.job_spec, option=orjson.OPT_SORT_KEYS)
    ).hexdigest()
    if job_hash != record.job_spec_hash or job_hash != message.job_spec_hash:
        raise NautilusJobValidationError("dispatched job_spec hash differs from durable Job data")
    if record.run_spec_hash != message.run_spec_hash:
        raise NautilusJobValidationError("dispatch RunSpec hash differs from the JobAttempt")
    run_spec = record.job_spec.get("run_spec")
    if not isinstance(run_spec, dict):
        raise NautilusJobValidationError("JobAttempt has no frozen RunSpec")
    if hash_run_spec(run_spec) != record.run_spec_hash:
        raise NautilusJobValidationError("frozen RunSpec hash differs from the JobAttempt")
    if run_spec.get("run_spec_version") != NAUTILUS_RUN_SPEC_VERSION:
        raise NautilusJobValidationError(
            f"only RunSpec v{NAUTILUS_RUN_SPEC_VERSION} can execute on Nautilus"
        )
    if not isinstance(record.execution_plan, dict) or not record.execution_plan_hash:
        raise NautilusJobValidationError("JobAttempt has no immutable execution plan")
    if canonical_hash(record.execution_plan) != record.execution_plan_hash:
        raise NautilusJobValidationError("execution plan hash differs from durable Job data")
    if record.runner_path != "server.modules.single_factor_test.process_runners:run_group":
        raise NautilusJobValidationError("JobAttempt is not bound to the Nautilus backtest runner")
    return run_spec


class _CancellationFlag:
    def __init__(self, context: ExecutionContext) -> None:
        self._context = context

    def is_set(self) -> bool:
        return self._context.cancel_requested()


class _DispatchEventSink:
    """Consume the established worker-sink events without an intermediate queue."""

    def __init__(self, context: ExecutionContext) -> None:
        self.context = context
        self._lock = threading.Lock()
        self._sequence = 0
        self.result: dict[str, Any] | None = None
        self.error: dict[str, Any] | None = None
        self.cancelled = False

    def put(self, event: dict[str, Any]) -> None:
        if not isinstance(event, dict) or event.get("job_id") != self.context.job_id:
            raise ValueError("runner emitted an event for a different Job")
        kind = str(event.get("event") or "")
        data = event.get("data")
        if not isinstance(data, dict):
            raise ValueError("runner event data must be an object")
        if kind == "artifact":
            self._register_artifact(data)
        elif kind == "result":
            self.result = dict(data)
        elif kind == "error":
            self.cancelled = bool(data.get("cancelled")) or self.context.cancel_requested()
            self.error = {
                "code": str(data.get("code") or "nautilus_execution_failed"),
                "message": str(data.get("message") or data.get("error") or "Nautilus execution failed"),
            }
        elif kind in {"progress", "signal_progress"}:
            self._record_progress(data)

    def _record_progress(self, data: dict[str, Any]) -> None:
        with self._lock:
            self._sequence += 1
            sequence = self._sequence
        completed = max(0, int(data.get("completed") or 0))
        total = max(0, int(data.get("total") or 0))
        percent_value = data.get("percent")
        percent = (
            100.0 if total <= 0 else completed / total * 100.0
        ) if percent_value is None else float(percent_value)
        self.context.report_progress(
            sequence=sequence,
            phase=str(data.get("phase") or "event_replay"),
            completed=completed,
            total=total,
            percent=max(0.0, min(100.0, percent)),
            message=str(data.get("message") or ""),
        )

    def _register_artifact(self, data: dict[str, Any]) -> None:
        relative = Path(str(data.get("relative_path") or ""))
        root = artifact_root()
        path = (root / relative).resolve()
        if (
            relative.is_absolute() or not relative.parts
            or any(part in {"", ".", ".."} for part in relative.parts)
            or root not in path.parents or not path.is_file()
        ):
            raise ValueError("runner artifact path is invalid or missing")
        self.context.repository.record_artifact(
            job_id=self.context.job_id,
            name=str(data.get("name") or ""),
            relative_path=relative.as_posix(),
            content_type=str(data.get("content_type") or "application/octet-stream"),
            content_hash=str(data.get("content_hash") or ""),
            size_bytes=int(data.get("size_bytes") or 0),
            retention_mode="retained",
        )


class _RunnerSinkAdapter:
    """Normalize the legacy runner's error keyword without changing Job events."""

    def __init__(self, sink: Any) -> None:
        self._sink = sink

    def __getattr__(self, name: str) -> Any:
        return getattr(self._sink, name)

    def emit_error(self, error: str, traceback: str = "", **extra: Any) -> None:
        code = extra.pop("error_code", None)
        self._sink.emit_error(error, traceback, code=code, **extra)


class _ReplayRunner:
    """Run the bounded, receipt-checked Nautilus catalog replay for one Job."""

    def __init__(self, record: JobRecord, context: ExecutionContext) -> None:
        self.record = record
        self.context = context

    def __call__(self, payload: dict[str, Any], sink: Any, cancel_event: Any) -> None:
        from dataclasses import asdict

        from server.services.nautilus_bridge.backtest_runner import (
            ReplayInput,
            run_small_catalog_replay,
        )

        plan = self.record.execution_plan or {}
        raw_inputs = plan.get("catalog_inputs")
        if not isinstance(raw_inputs, list) or not raw_inputs:
            sink.emit_error(
                "execution plan has no catalog inputs",
                error_code="nautilus_replay_invalid_plan",
            )
            return
        allowed_root = Path(
            os.environ.get("FACTORTESTER_NAUTILUS_CATALOG_ROOT", "/data")
        ).resolve()
        inputs = []
        for item in raw_inputs:
            if not isinstance(item, dict):
                sink.emit_error(
                    "catalog input must be an object",
                    error_code="nautilus_replay_invalid_plan",
                )
                return
            folder = Path(str(item.get("catalog_dir") or "")).resolve()
            if not folder.is_relative_to(allowed_root):
                sink.emit_error(
                    "catalog input is outside the configured catalog root",
                    error_code="nautilus_replay_forbidden_path",
                )
                return
            contract = str(item.get("contract_uid") or "").strip()
            if not contract:
                sink.emit_error(
                    "catalog input has no contract uid",
                    error_code="nautilus_replay_invalid_plan",
                )
                return
            inputs.append(ReplayInput(folder, contract))
        output = (
            Path(artifact_root()) / self.record.job_id
            / f"nautilus-replay-{self.record.attempt}-{uuid.uuid4().hex[:8]}"
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        try:
            receipt = run_small_catalog_replay(
                tuple(inputs), output,
                max_input_bars=int(plan.get("max_input_bars") or 200),
                batch_minutes=int(plan.get("batch_minutes") or 20),
                synthetic_order_probe=bool(plan.get("synthetic_order_probe")),
                position_cost_basis=str(
                    plan.get("position_cost_basis") or "WEIGHTED_AVERAGE"
                ),
            )
        except NotImplementedError as exc:
            sink.emit_error(str(exc), error_code="nautilus_execution_unavailable")
            return
        except Exception as exc:  # runner errors surface as Job failure
            sink.emit_error(
                f"Nautilus replay failed: {type(exc).__name__}: {exc}",
                error_code="nautilus_replay_failed",
            )
            return
        result = asdict(receipt)
        result["reports_dir"] = str(output)
        sink.emit_result(result)


class NautilusJobExecutor:
    """Execute one verified Nautilus RunSpec through FactorTester's runner API."""

    def __init__(self, runner: Any = None) -> None:
        self._runner = runner

    def execute(
        self, record: JobRecord, message: DispatchMessage,
        context: ExecutionContext,
    ) -> ExecutionOutcome:
        run_spec = _verify_dispatch(record, message)
        if context.cancel_requested():
            return ExecutionOutcome({}, cancelled=True)

        payload = dict(record.job_spec)
        payload.update({
            "kind": "backtest",
            "run_spec": run_spec,
            "execution_plan": record.execution_plan,
            "execution_plan_hash": record.execution_plan_hash,
            "job_id": record.job_id,
            "attempt": record.attempt,
            "runner_path": record.runner_path,
        })
        receiver = _DispatchEventSink(context)
        from server.jobs.dispatch.artifact_sink import _WorkerSink

        sink = _WorkerSink(
            record.job_id,
            receiver,
            artifact_job_id=record.job_id,
            artifact_root=str(artifact_root()),
            retention_mode=record.retention_mode,
            output_requests=record.job_spec.get("output_requests") or (),
            cancel_event=_CancellationFlag(context),
        )
        runner_sink = _RunnerSinkAdapter(sink)
        runner = self._runner
        if runner is None:
            if str((record.execution_plan or {}).get("kind") or "") == "nautilus_catalog_replay":
                runner = _ReplayRunner(record, context)
            else:
                from server.modules.single_factor_test.process_runners import run_group

                runner = run_group
        runner(payload, runner_sink, sink.cancel_event)

        if receiver.cancelled or context.cancel_requested():
            return ExecutionOutcome(receiver.result or {}, cancelled=True)
        if receiver.error is not None:
            return ExecutionOutcome(receiver.result or {}, error=receiver.error)
        if receiver.result is None:
            return ExecutionOutcome(
                {}, error={
                    "code": "nautilus_runner_no_result",
                    "message": "Nautilus runner returned without a result or error event",
                },
            )
        return ExecutionOutcome(receiver.result)


execute_nautilus_job = NautilusJobExecutor()


__all__ = [
    "NautilusJobExecutor", "NautilusJobValidationError", "execute_nautilus_job",
]
