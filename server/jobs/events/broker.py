"""Bounded in-memory job event rings and reconnect snapshots."""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class EventGap:
    requested_seq: int
    oldest_seq: int
    newest_seq: int


@dataclass(frozen=True)
class BrokerEvent:
    seq: int
    event: str
    data: dict[str, Any]
    created_at: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "event": self.event,
            "data": dict(self.data),
            "created_at": self.created_at,
        }


class _JobEvents:
    def __init__(self, max_events: int) -> None:
        self.next_seq = 1
        self.events: deque[BrokerEvent] = deque(maxlen=max_events)
        self.latest_progress: BrokerEvent | None = None
        self.manifest: BrokerEvent | None = None
        self.closed = False


class EventBroker:
    """Live-only event storage owned by the scheduler daemon."""

    def __init__(self, *, max_events_per_job: int = 2000) -> None:
        self.max_events_per_job = max(1, int(max_events_per_job))
        self._jobs: dict[str, _JobEvents] = {}
        self._lock = threading.RLock()
        self._condition = threading.Condition(self._lock)

    def publish(self, job_id: str, event: str, data: dict[str, Any]) -> dict[str, Any]:
        with self._condition:
            state = self._jobs.setdefault(
                str(job_id), _JobEvents(self.max_events_per_job)
            )
            item = BrokerEvent(
                seq=state.next_seq,
                event=str(event),
                data=dict(data),
                created_at=time.time(),
            )
            state.next_seq += 1
            state.events.append(item)
            if item.event in {"progress", "signal_progress", "activity"}:
                state.latest_progress = item
            elif item.event == "activity_manifest":
                state.manifest = item
            if item.event in {"result", "error"}:
                state.closed = True
            self._condition.notify_all()
            return item.to_dict()

    def close(self, job_id: str) -> None:
        with self._condition:
            state = self._jobs.setdefault(
                str(job_id), _JobEvents(self.max_events_per_job)
            )
            state.closed = True
            self._condition.notify_all()

    def read(self, job_id: str, *, after: int = 0) -> dict[str, Any]:
        with self._lock:
            state = self._jobs.get(str(job_id))
            if state is None:
                return {
                    "events": [],
                    "gap": None,
                    "latest_progress": None,
                    "manifest": None,
                    "closed": False,
                    "oldest_seq": 0,
                    "newest_seq": 0,
                }
            oldest = state.events[0].seq if state.events else 0
            newest = state.events[-1].seq if state.events else state.next_seq - 1
            gap = None
            if int(after) > 0 and oldest > 0 and int(after) < oldest - 1:
                gap = EventGap(int(after), oldest, newest).__dict__
            return {
                "events": [
                    event.to_dict() for event in state.events if event.seq > int(after)
                ],
                "gap": gap,
                "latest_progress": (
                    state.latest_progress.to_dict() if state.latest_progress else None
                ),
                "manifest": state.manifest.to_dict() if state.manifest else None,
                "closed": state.closed,
                "oldest_seq": oldest,
                "newest_seq": newest,
            }

    def wait(self, job_id: str, *, after: int = 0, timeout: float = 15.0) -> dict[str, Any]:
        deadline = time.monotonic() + max(0.0, float(timeout))
        with self._condition:
            while True:
                snapshot = self.read(job_id, after=after)
                if snapshot["events"] or snapshot["gap"] or snapshot["closed"]:
                    return snapshot
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return snapshot
                self._condition.wait(timeout=remaining)

    def discard(self, job_id: str) -> None:
        with self._condition:
            self._jobs.pop(str(job_id), None)
            self._condition.notify_all()
