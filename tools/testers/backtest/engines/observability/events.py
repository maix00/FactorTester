"""Read-only event observers for structured logs and UI progress."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from ..native.contracts import RunIdentity
from ..native.runtime import EventTopic, ProcessedEvent


class StructuredEventLogger:
    """Emit structured records; application startup owns handlers and sinks."""

    def __init__(
        self,
        identity: RunIdentity,
        logger: logging.Logger | None = None,
    ) -> None:
        self.identity = identity
        self.logger = logger or logging.getLogger("factortester.backtest.event")

    def on_event(self, record: ProcessedEvent) -> None:
        event = record.event
        strategy_id = getattr(event.payload, "strategy_id", None)
        portfolio_id = getattr(event.payload, "portfolio_id", None)
        extra = {
            "run_id": self.identity.run_id,
            "user_id": self.identity.user_id,
            "page_uuid": self.identity.page_uuid,
            "session_id": self.identity.session_id,
            "tester_alias": self.identity.tester_alias,
            "event_id": event.event_id,
            "causation_id": event.causation_id,
            "event_topic": event.topic.value,
            "event_sequence": event.sequence,
            "strategy_id": strategy_id,
            "portfolio_id": portfolio_id,
            "event_succeeded": record.succeeded,
            "event_error_type": record.error_type,
        }
        level = logging.INFO if record.succeeded else logging.ERROR
        self.logger.log(level, "backtest_event", extra=extra)


@dataclass(frozen=True, slots=True)
class ProgressUpdate:
    run_id: str
    topic: EventTopic
    sequence: int
    strategy_id: str | None
    succeeded: bool


class ProgressObserver:
    """Typed callback channel, intentionally separate from logging."""

    def __init__(self, run_id: str, callback: Callable[[ProgressUpdate], None]) -> None:
        self.run_id = run_id
        self.callback = callback

    def on_event(self, record: ProcessedEvent) -> None:
        event = record.event
        self.callback(ProgressUpdate(
            run_id=self.run_id,
            topic=event.topic,
            sequence=event.sequence,
            strategy_id=getattr(event.payload, "strategy_id", None),
            succeeded=record.succeeded,
        ))
