"""Planning-only sidecar for Manager-managed services.

Celery owns planning and execution. This process keeps the existing Manager
Unix-socket lifecycle (health/drain/resume/wake) while publishing submitted
Jobs to the Celery plan queue.
"""

from __future__ import annotations

import threading
import time
from typing import Any

from server.jobs.dispatch.planning import PlanningDispatcher
from server.jobs.events import EventBroker
from server.jobs.repository import JobRepository


class PlanningDaemon:
    def __init__(
        self, *, repository: JobRepository, deployment_id: str,
        publisher: Any, target_online: Any = None, interval: float = 2.0,
    ) -> None:
        self.repository = repository
        self.deployment_id = str(deployment_id)
        self.publisher = publisher
        self.target_online = target_online
        self.interval = max(0.2, float(interval))
        self.broker = EventBroker()
        self._stop = threading.Event()
        self._draining = False
        self._thread: threading.Thread | None = None
        self._dispatcher = (
            PlanningDispatcher(repository, publisher, target_online=target_online)
            if publisher is not None else None
        )

    def tick(self) -> None:
        if self._dispatcher is not None and not self._draining:
            self._dispatcher.run_once(limit=10)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._serve, daemon=True, name="celery-planning-sidecar",
        )
        self._thread.start()

    def _serve(self) -> None:
        while not self._stop.wait(self.interval):
            self.tick()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def health_snapshot(self) -> dict[str, Any]:
        return {
            "ok": True,
            "deployment_id": self.deployment_id,
            "draining": self._draining,
            "celery_planning": self._dispatcher is not None,
        }

    def set_draining(self, value: bool) -> None:
        self._draining = bool(value)

    def cancel(self, job_id: str) -> bool:
        return False

    def continue_step(self, job_id: str, command: dict[str, Any]) -> bool:
        return False
