"""Celery application and task for FactorTester Job dispatch.

The task body is a thin adapter: validate the JSON message, resolve the
Nautilus-backed executor, claim the JobAttempt, execute, write terminal state.
FactorTester remains the Job business authority; Celery state is operational
only.
"""

from __future__ import annotations

import importlib
import os
from typing import Any, Mapping

from server.jobs.repository.sqlite import JobRepository

from .contract import DispatchMessage
from .dispatcher import DEFAULT_QUEUE
from .worker import DispatchWorker, JobExecutor

TASK_NAME = "factortester.execute_job"
EXECUTOR_ENV = "FACTORTESTER_NAUTILUS_EXECUTOR"
DEFAULT_EXECUTOR = "server.services.nautilus_bridge.job_executor:execute_nautilus_job"


class DispatchExecutorUnavailable(RuntimeError):
    """No complete Nautilus Job executor is installed in this worker image."""


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
) -> dict[str, Any]:
    """Execute one Celery payload; safe to call directly in tests."""
    message = DispatchMessage.from_dict(payload)
    resolved = executor if executor is not None else resolve_executor()
    repo = repository or JobRepository()
    return DispatchWorker(repo).execute(message, resolved)


def create_app(
    *,
    broker_url: str | None = None,
    queue: str = DEFAULT_QUEUE,
):
    from celery import Celery

    broker = broker_url or os.environ.get("FACTORTESTER_BROKER_URL", "").strip()
    if not broker:
        raise RuntimeError("FACTORTESTER_BROKER_URL is required to create the Celery app")
    app = Celery("factortester.jobs", broker=broker)
    app.conf.update(
        task_default_queue=queue,
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        task_acks_late=False,
        task_reject_on_worker_lost=False,
        worker_prefetch_multiplier=1,
        worker_concurrency=1,
        task_track_started=True,
        broker_connection_retry_on_startup=True,
        timezone="UTC",
        enable_utc=True,
    )

    @app.task(name=TASK_NAME, bind=True)
    def execute_job(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return execute_dispatch_payload(payload)

    return app
