"""Celery CLI entry point for one (deployment_id, service_port) worker."""

from __future__ import annotations

import os

from .celery_app import create_app

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
