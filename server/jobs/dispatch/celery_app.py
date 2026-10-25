"""Celery application and task for FactorTester Job dispatch.

The task body is a thin adapter: validate the JSON message, resolve the
Nautilus-backed executor, claim the JobAttempt, execute, write terminal state.
FactorTester remains the Job business authority; Celery state is operational
only.
"""

from __future__ import annotations

import importlib
import os

from server import branding
from typing import Any, Mapping

from server.jobs.repository.sqlite import JobRepository
from server.jobs.states import JobStatus

from .contract import DispatchMessage
from .dispatcher import DEFAULT_QUEUE
from .worker import DispatchWorker, JobExecutor

TASK_NAME = "factortester.execute_job"
PLAN_TASK_NAME = "factortester.jobs.plan"
EXECUTOR_ENV = "FACTORTESTER_NAUTILUS_EXECUTOR"
DEFAULT_EXECUTOR = "server.services.nautilus_bridge.job_executor:execute_nautilus_job"


class DispatchExecutorUnavailable(RuntimeError):
    """No complete Nautilus Job executor is installed in this worker image."""


def repository_from_env() -> JobRepository:
    path = branding.env("JOB_DB", "").strip()
    return JobRepository(path) if path else JobRepository()


def resolve_executor() -> JobExecutor:
    target = os.environ.get(EXECUTOR_ENV, DEFAULT_EXECUTOR).strip()
    module_name, _, attribute = target.partition(":")
    if not module_name or not attribute:
        raise DispatchExecutorUnavailable(
            f"{EXECUTOR_ENV} must be 'module:attribute'"
        )
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        raise DispatchExecutorUnavailable(
            f"Nautilus Job executor is not installed: {module_name}"
        ) from exc
    candidate = getattr(module, attribute, None)
    if candidate is None or not hasattr(candidate, "execute"):
        raise DispatchExecutorUnavailable(
            f"Nautilus Job executor is not callable: {target}"
        )
    return candidate


def execute_dispatch_payload(
    payload: Mapping[str, Any],
    *,
    executor: JobExecutor | None = None,
    repository: JobRepository | None = None,
    target_deployment: str | None = None,
    target_port: int | None = None,
) -> dict[str, Any]:
    """Execute one Celery payload; safe to call directly in tests.

    A worker bound to another deployment/port must return ``wrong_target``
    without claiming; the exchange routes by target, but this is defense in
    depth against a misbound consumer.
    """
    message = DispatchMessage.from_dict(payload)
    if target_deployment is not None and message.deployment_id != target_deployment:
        return {"status": "wrong_target", "job_id": message.job_id}
    if target_port is not None and message.service_port != int(target_port):
        return {"status": "wrong_target", "job_id": message.job_id}
    resolved = executor if executor is not None else resolve_executor()
    repo = repository or repository_from_env()
    return DispatchWorker(repo).execute(message, resolved)


class _PlanSink:
    def __init__(self) -> None:
        self.plan: dict[str, Any] | None = None
        self.notices: list[dict[str, Any]] = []
        self.error: dict[str, Any] | None = None
        self.cancelled = False

    def emit_plan(self, value: dict[str, Any]) -> None:
        plan = value.get("plan") if isinstance(value, dict) else None
        if not isinstance(plan, dict):
            raise ValueError("planner emitted no plan")
        self.plan = plan
        self.notices = list(value.get("notices") or [])

    def emit_error(self, message: str, *, cancelled: bool = False, **extra: Any) -> None:
        if cancelled:
            self.cancelled = True
            return
        self.error = {
            "code": str(extra.get("error_code") or "planning_failed"),
            "message": str(message),
        }


def execute_plan_payload(
    payload: Mapping[str, Any],
    *,
    repository: JobRepository | None = None,
    planner: Any = None,
    target_deployment: str | None = None,
    target_port: int | None = None,
) -> dict[str, Any]:
    """Plan one submitted JobAttempt on a Celery worker."""
    message = DispatchMessage.from_dict(payload)
    if target_deployment is not None and message.deployment_id != target_deployment:
        return {"status": "wrong_target", "job_id": message.job_id}
    if target_port is not None and message.service_port != int(target_port):
        return {"status": "wrong_target", "job_id": message.job_id}
    repo = repository or repository_from_env()
    record = repo.load(message.job_id)
    if record is None or record.attempt != message.attempt:
        return {"status": "stale", "job_id": message.job_id}
    if record.status is not JobStatus.PLANNING:
        return {"status": "duplicate", "job_id": message.job_id}
    if planner is None:
        from server.jobs.planning.runners import plan_job

        planner = plan_job
    payload_value = dict(record.job_spec)
    payload_value.update({
        "job_spec": record.job_spec,
        "kind": record.kind,
        "runner_path": record.runner_path,
        "_owner": record.owner,
    })
    sink = _PlanSink()
    try:
        planner(payload_value, sink, _NeverCancelled())
    except Exception as exc:
        repo.transition(
            record.job_id, JobStatus.FAILED, expected=JobStatus.PLANNING,
            error={"code": "planning_failed", "message": f"{type(exc).__name__}: {exc}"},
        )
        return {"status": "failed", "job_id": record.job_id}
    if sink.error is not None:
        repo.transition(
            record.job_id, JobStatus.FAILED, expected=JobStatus.PLANNING,
            error=sink.error,
        )
        return {"status": "failed", "job_id": record.job_id}
    if sink.plan is None:
        repo.transition(
            record.job_id, JobStatus.FAILED, expected=JobStatus.PLANNING,
            error={"code": "planning_no_plan", "message": "planner returned no plan"},
        )
        return {"status": "failed", "job_id": record.job_id}
    repo.set_execution_plan(
        record.job_id, plan=sink.plan, notices=sink.notices,
        requires_confirmation=bool(sink.plan.get("requires_confirmation")),
    )
    return {"status": "planned", "job_id": record.job_id}


class _NeverCancelled:
    def is_set(self) -> bool:
        return False


def create_app(
    *,
    broker_url: str | None = None,
    queue: str = DEFAULT_QUEUE,
    target_deployment: str | None = None,
    target_port: int | None = None,
):
    from celery import Celery

    broker = broker_url or branding.env("BROKER_URL", "").strip()
    if not broker:
        raise RuntimeError("FACTORTESTER_BROKER_URL is required to create the Celery app")
    resolved_deployment = target_deployment or branding.env("DEPLOYMENT_ID", "").strip() or None
    raw_port = target_port if target_port is not None else branding.env("SERVICE_PORT", "").strip()
    resolved_port = int(raw_port) if raw_port not in (None, "") else None
    queue_name = queue
    if resolved_deployment and resolved_port:
        queue_name = f"{queue}.{resolved_deployment}.{resolved_port}"
    app = Celery("factortester.jobs", broker=broker)
    app.conf.update(
        task_default_queue=queue_name,
        task_default_exchange="factortester",
        task_default_exchange_type="direct",
        task_default_routing_key=queue_name,
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        task_acks_late=False,
        task_reject_on_worker_lost=False,
        worker_prefetch_multiplier=1,
        worker_concurrency=1,
        worker_max_tasks_per_child=max(1, int(os.environ.get("FACTORTESTER_WORKER_MAX_TASKS", "1"))),
        worker_max_memory_per_child=max(
            1, int(os.environ.get("FACTORTESTER_WORKER_MAX_MEMORY_KB", "3500000"))
        ),
        task_track_started=True,
        broker_connection_retry_on_startup=True,
        timezone="UTC",
        enable_utc=True,
    )

    @app.task(name=TASK_NAME, bind=True)
    def execute_job(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return execute_dispatch_payload(
            payload,
            target_deployment=resolved_deployment,
            target_port=resolved_port,
        )

    @app.task(name=PLAN_TASK_NAME, bind=True)
    def plan_job(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return execute_plan_payload(
            payload,
            target_deployment=resolved_deployment,
            target_port=resolved_port,
        )

    return app
