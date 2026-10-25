"""Publish claimed outbox rows to RabbitMQ and record broker confirmation."""

from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Protocol

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

    def publish(self, message: DispatchMessage) -> None:
        from kombu import Connection, Exchange, Producer, Queue

        queue = Queue(self.queue, Exchange("factortester", type="direct"), routing_key=self.queue)
        with Connection(self.broker_url, connect_timeout=self.confirm_timeout) as connection:
            channel = connection.channel()
            producer = Producer(channel, exchange=queue.exchange, routing_key=self.queue)
            producer.publish(
                message.to_dict(),
                declare=[queue],
                serializer="json",
                delivery_mode=2,
                retry=False,
            )


class DispatchRunner:
    """One dispatcher tick: lease -> publish -> mark sent/failed."""

    def __init__(self, outbox: DispatchOutbox, publisher: DispatchPublisher) -> None:
        self.outbox = outbox
        self.publisher = publisher

    def run_once(self, *, limit: int = 10) -> dict[str, int]:
        result = {"claimed": 0, "sent": 0, "failed": 0}
        for record in self.outbox.claim(limit=limit):
            result["claimed"] += 1
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
    queue = os.environ.get("FACTORTESTER_JOB_QUEUE", DEFAULT_QUEUE).strip() or DEFAULT_QUEUE
    return KombuPublisher(broker_url=broker_url, queue=queue)
