"""Celery CLI entry point for one (deployment_id, service_port) worker."""

from __future__ import annotations

import os

from server import branding
import socket
import threading
import uuid

from .celery_app import create_app, repository_from_env


app = create_app(
    broker_url=branding.env("BROKER_URL", "").strip() or None,
    queue=branding.env("JOB_QUEUE", "factortester.jobs"),
    target_deployment=branding.env("DEPLOYMENT_ID", "").strip() or None,
    target_port=(
        int(os.environ["FACTORTESTER_SERVICE_PORT"])
        if branding.env("SERVICE_PORT", "").strip()
        else None
    ),
)


def heartbeat_target_once(
    *, deployment: str | None = None, service_port: int | None = None,
) -> bool:
    deployment = (deployment or branding.env("DEPLOYMENT_ID", "")).strip()
    raw_port = service_port if service_port is not None else branding.env("SERVICE_PORT", "")
    if os.environ.get("TR_MANAGER_ENDPOINT"):
        repository_from_env().register()
        return True
    if not deployment or str(raw_port).strip() == "" or not branding.env("JOB_DB", "").strip():
        return False
    port = int(raw_port)
    interval = max(5.0, float(os.environ.get("FACTORTESTER_TARGET_HEARTBEAT_SECONDS", "20")))
    repository = repository_from_env()
    worker_id = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:12]}"
    repository.heartbeat_worker_target(
        deployment, port, worker_id,
        capabilities={
            "executor": branding.env("NAUTILUS_EXECUTOR", ""),
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
