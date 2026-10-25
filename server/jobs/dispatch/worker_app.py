"""Celery CLI entry point for one (deployment_id, service_port) worker."""

from __future__ import annotations

import os
import socket
import threading
import uuid

from .celery_app import create_app, repository_from_env


app = create_app(
    broker_url=os.environ.get("FACTORTESTER_BROKER_URL", "").strip() or None,
    queue=os.environ.get("FACTORTESTER_JOB_QUEUE", "factortester.jobs"),
    target_deployment=os.environ.get("FACTORTESTER_DEPLOYMENT_ID", "").strip() or None,
    target_port=(
        int(os.environ["FACTORTESTER_SERVICE_PORT"])
        if os.environ.get("FACTORTESTER_SERVICE_PORT", "").strip()
        else None
    ),
)


def heartbeat_target_once(
    *, deployment: str | None = None, service_port: int | None = None,
) -> bool:
    deployment = (deployment or os.environ.get("FACTORTESTER_DEPLOYMENT_ID", "")).strip()
    raw_port = service_port if service_port is not None else os.environ.get("FACTORTESTER_SERVICE_PORT", "")
    if not deployment or str(raw_port).strip() == "" or not os.environ.get("FACTORTESTER_JOB_DB", "").strip():
        return False
    port = int(raw_port)
    interval = max(5.0, float(os.environ.get("FACTORTESTER_TARGET_HEARTBEAT_SECONDS", "20")))
    repository = repository_from_env()
    worker_id = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:12]}"
    repository.heartbeat_worker_target(
        deployment, port, worker_id,
        capabilities={
            "executor": os.environ.get("FACTORTESTER_NAUTILUS_EXECUTOR", ""),
        },
        ttl_seconds=max(interval * 3, 60.0),
    )
    return True


def _start_target_heartbeat() -> None:
    if not heartbeat_target_once():
        return
    interval = max(5.0, float(os.environ.get("FACTORTESTER_TARGET_HEARTBEAT_SECONDS", "20")))

    def loop() -> None:
        while True:
            try:
                heartbeat_target_once()
            except Exception:
                pass
            threading.Event().wait(interval)

    threading.Thread(target=loop, name="job-target-heartbeat", daemon=True).start()


_start_target_heartbeat()
