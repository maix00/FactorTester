"""Publish claimed outbox rows to RabbitMQ and record broker confirmation."""

from __future__ import annotations

from dataclasses import dataclass
import os

from server import branding
from typing import Callable, Protocol

from .contract import DispatchMessage
from .outbox import DispatchOutbox, OutboxRecord

DEFAULT_QUEUE = "factortester.jobs"
BROKER_ENV = "FACTORTESTER_BROKER_URL"


class DispatchPublisher(Protocol):
    def publish(self, message: DispatchMessage) -> None: ...


@dataclass
class KombuPublisher:
    """Minimal RabbitMQ publisher; the broker URL stays in environment."""

    broker_url: str
    queue: str = DEFAULT_QUEUE
    confirm_timeout: float = 10.0

    def target_queue(self, message: DispatchMessage) -> str:
        return f"{self.queue}.{message.deployment_id}.{message.service_port}"

    def publish(self, message: DispatchMessage) -> None:
        self._send("factortester.execute_job", message)

    def publish_plan(self, message: DispatchMessage) -> None:
        self._send("factortester.jobs.plan", message)

    def _send(self, task: str, message: DispatchMessage) -> None:
        from celery import Celery
        from kombu import Exchange, Queue

        name = self.target_queue(message)
        exchange = Exchange("factortester", type="direct")
        queue = Queue(name, exchange, routing_key=name)
        app = Celery("factortester.dispatch-publisher", broker=self.broker_url)
        app.send_task(
            task,
            args=[message.to_dict()],
            queue=queue,
            exchange=exchange,
            routing_key=name,
            declare=[queue],
            serializer="json",
            retry=False,
            ignore_result=True,
        )

class DispatchRunner:
    """One dispatcher tick: lease -> publish -> mark sent/failed."""

    def __init__(
        self,
        outbox: DispatchOutbox,
        publisher: DispatchPublisher,
        *,
        preflight: Callable[[], None] | None = None,
        target_online: Callable[[str, int], bool] | None = None,
    ) -> None:
        self.outbox = outbox
        self.publisher = publisher
        self.preflight = preflight
        self.target_online = target_online

    def run_once(self, *, limit: int = 10) -> dict[str, int]:
        if self.preflight is not None:
            self.preflight()
        result = {"claimed": 0, "sent": 0, "failed": 0, "deferred": 0}
        for record in self.outbox.claim(limit=limit):
            result["claimed"] += 1
            if self.target_online is not None and not self.target_online(
                record.deployment_id, record.message.service_port,
            ):
                self.outbox.defer(record.identity)
                result["deferred"] += 1
                continue
            try:
                self.publisher.publish(record.message)
            except Exception as exc:  # broker/network/protocol failure
                status = self.outbox.mark_failed(record.identity, f"{type(exc).__name__}: {exc}")
                result["failed"] += 1
                if status == "dead":
                    result.setdefault("dead", 0)
                    result["dead"] += 1
            else:
                self.outbox.mark_sent(record.identity)
                result["sent"] += 1
        return result


def publisher_from_env() -> KombuPublisher:
    broker_url = os.environ.get(BROKER_ENV, "").strip()
    if not broker_url:
        raise RuntimeError(f"{BROKER_ENV} is required for the dispatch dispatcher")
    queue = branding.env("JOB_QUEUE", DEFAULT_QUEUE).strip() or DEFAULT_QUEUE
    return KombuPublisher(broker_url=broker_url, queue=queue)
