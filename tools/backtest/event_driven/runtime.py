"""Run-scoped event runtime for causal backtests."""

from __future__ import annotations

import heapq
import itertools
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol

import pandas as pd


class EventTopic(str, Enum):
    MARKET_DATA = "market.data"
    MARKET_SLICE_CLOSED = "market.slice_closed"
    FACTOR_SIGNAL = "factor.signal"
    PORTFOLIO_INTENT = "portfolio.intent"
    PORTFOLIO_APPROVED = "portfolio.approved"
    PORTFOLIO_REJECTED = "portfolio.rejected"
    ORDER_SUBMITTED = "order.submitted"
    ORDER_ACCEPTED = "order.accepted"
    ORDER_REJECTED = "order.rejected"
    FILL = "execution.fill"
    SETTLEMENT = "account.settlement"
    MARGIN_CALL = "risk.margin_call"
    TIMER = "clock.timer"
    REPORT = "report.snapshot"


@dataclass(frozen=True, slots=True)
class EventDraft:
    """An event requested by a handler before the runtime assigns identity."""

    topic: EventTopic
    timestamp: pd.Timestamp
    payload: Any = None
    priority: int = 0


@dataclass(order=True, frozen=True, slots=True)
class EventEnvelope:
    """Scheduled event ordered deterministically by time, priority, and sequence."""

    timestamp: pd.Timestamp
    priority: int
    sequence: int
    event_id: str = field(compare=False)
    run_id: str = field(compare=False)
    topic: EventTopic = field(compare=False)
    payload: Any = field(default=None, compare=False)
    causation_id: str | None = field(default=None, compare=False)


@dataclass(frozen=True, slots=True)
class ProcessedEvent:
    event: EventEnvelope
    subscriber_count: int
    succeeded: bool = True
    error_type: str | None = None


EventHandler = Callable[
    [EventEnvelope, "EventRuntime"], EventDraft | Iterable[EventDraft] | None
]


class EventSource(Protocol):
    def start(self, runtime: "EventRuntime") -> None: ...

    def after_event(self, event: EventEnvelope, runtime: "EventRuntime") -> None: ...


class EventObserver(Protocol):
    def on_event(self, record: ProcessedEvent) -> None: ...


class EventRuntime:
    """Owns one run's queue, subscriptions, sources, and processed journal."""

    def __init__(self, run_id: str, *, max_events_per_timestamp: int = 100_000) -> None:
        if not run_id:
            raise ValueError("run_id must not be empty")
        self.run_id = run_id
        self.max_events_per_timestamp = max_events_per_timestamp
        self._queue: list[EventEnvelope] = []
        self._subscribers: dict[EventTopic, list[EventHandler]] = defaultdict(list)
        self._sources: list[EventSource] = []
        self._finalizers: list[Callable[["EventRuntime"], None]] = []
        self._observers: list[EventObserver] = []
        self._sequence = itertools.count()
        self._current: EventEnvelope | None = None
        self._started = False
        self.journal: list[ProcessedEvent] = []

    @property
    def pending_count(self) -> int:
        return len(self._queue)

    @property
    def current(self) -> EventEnvelope | None:
        return self._current

    def subscribe(self, topic: EventTopic, handler: EventHandler) -> None:
        if self._started:
            raise RuntimeError("subscriptions are immutable after the run starts")
        self._subscribers[topic].append(handler)

    def add_source(self, source: EventSource) -> None:
        if self._started:
            raise RuntimeError("event sources are immutable after the run starts")
        self._sources.append(source)

    def add_finalizer(self, finalizer: Callable[["EventRuntime"], None]) -> None:
        if self._started:
            raise RuntimeError("finalizers are immutable after the run starts")
        self._finalizers.append(finalizer)

    def add_observer(self, observer: EventObserver) -> None:
        if self._started:
            raise RuntimeError("observers are immutable after the run starts")
        self._observers.append(observer)

    def publish(self, draft: EventDraft) -> EventEnvelope:
        timestamp = pd.Timestamp(draft.timestamp)
        if self._current is not None and timestamp < self._current.timestamp:
            raise ValueError("an event cannot be published into the past")
        sequence = next(self._sequence)
        envelope = EventEnvelope(
            timestamp=timestamp,
            priority=draft.priority,
            sequence=sequence,
            event_id=f"{self.run_id}:{sequence}",
            run_id=self.run_id,
            topic=draft.topic,
            payload=draft.payload,
            causation_id=self._current.event_id if self._current else None,
        )
        heapq.heappush(self._queue, envelope)
        return envelope

    def run(self) -> None:
        if self._started:
            raise RuntimeError("EventRuntime instances are single-use")
        self._started = True
        for source in self._sources:
            source.start(self)

        timestamp: pd.Timestamp | None = None
        count_at_timestamp = 0
        try:
            while self._queue:
                event = heapq.heappop(self._queue)
                if timestamp != event.timestamp:
                    timestamp = event.timestamp
                    count_at_timestamp = 0
                count_at_timestamp += 1
                if count_at_timestamp > self.max_events_per_timestamp:
                    raise RuntimeError(
                        f"event cycle suspected at {timestamp}: "
                        f"more than {self.max_events_per_timestamp} events"
                    )

                self._current = event
                handlers = tuple(self._subscribers.get(event.topic, ()))
                try:
                    for handler in handlers:
                        self._publish_handler_result(handler(event, self))
                except Exception as exc:
                    record = ProcessedEvent(
                        event,
                        len(handlers),
                        succeeded=False,
                        error_type=type(exc).__name__,
                    )
                    self._record(record)
                    raise
                self._record(ProcessedEvent(event, len(handlers)))
                for source in self._sources:
                    source.after_event(event, self)
            for finalizer in self._finalizers:
                finalizer(self)
        finally:
            self._current = None

    def _publish_handler_result(
        self, result: EventDraft | Iterable[EventDraft] | None
    ) -> None:
        if result is None:
            return
        if isinstance(result, EventDraft):
            self.publish(result)
            return
        for draft in result:
            self.publish(draft)

    def _record(self, record: ProcessedEvent) -> None:
        self.journal.append(record)
        for observer in self._observers:
            observer.on_event(record)


class ReplayEventSource:
    """Lazily publishes one replay event at a time instead of loading all bars."""

    def __init__(
        self,
        timestamps: Iterable[pd.Timestamp],
        payloads: Iterable[Any],
        *,
        topic: EventTopic = EventTopic.MARKET_DATA,
        priority: int = -100,
    ) -> None:
        self._events = iter(zip(timestamps, payloads, strict=True))
        self._topic = topic
        self._priority = priority
        self._pending_event_id: str | None = None

    def start(self, runtime: EventRuntime) -> None:
        self._publish_next(runtime)

    def after_event(self, event: EventEnvelope, runtime: EventRuntime) -> None:
        if event.event_id == self._pending_event_id:
            self._publish_next(runtime)

    def _publish_next(self, runtime: EventRuntime) -> None:
        try:
            timestamp, payload = next(self._events)
        except StopIteration:
            self._pending_event_id = None
            return
        event = runtime.publish(EventDraft(
            self._topic,
            pd.Timestamp(timestamp),
            payload,
            priority=self._priority,
        ))
        self._pending_event_id = event.event_id


@dataclass(frozen=True, slots=True)
class ProductPrice:
    product: str
    price: float
    fields: Mapping[str, float] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class MarketSlice:
    prices: Mapping[str, ProductPrice]


class MarketSliceBarrier:
    """Closes a timestamp after all expected product price events arrive."""

    def __init__(self, products: Iterable[str]) -> None:
        self._products = frozenset(products)
        if not self._products:
            raise ValueError("market slice requires at least one product")
        self._timestamp: pd.Timestamp | None = None
        self._prices: dict[str, ProductPrice] = {}

    def on_price(
        self, event: EventEnvelope, runtime: EventRuntime
    ) -> EventDraft | None:
        price = event.payload
        if not isinstance(price, ProductPrice):
            raise TypeError("market.data payload must be ProductPrice")
        if price.product not in self._products:
            raise ValueError(f"unexpected product in market slice: {price.product}")
        if self._timestamp is None or event.timestamp != self._timestamp:
            if self._prices:
                missing = sorted(self._products - self._prices.keys())
                raise ValueError(f"incomplete market slice; missing products: {missing}")
            self._timestamp = event.timestamp
        if price.product in self._prices:
            raise ValueError(f"duplicate product price in market slice: {price.product}")
        self._prices[price.product] = price
        if self._prices.keys() != self._products:
            return None
        payload = MarketSlice(dict(self._prices))
        self._prices.clear()
        return EventDraft(EventTopic.MARKET_SLICE_CLOSED, event.timestamp, payload)

    def finalize(self, runtime: EventRuntime) -> None:
        if self._prices:
            missing = sorted(self._products - self._prices.keys())
            raise ValueError(f"incomplete final market slice; missing products: {missing}")
