"""Bounded in-memory rendezvous for one producer and one consumer."""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Iterator


class RelayError(RuntimeError):
    pass


class RelayConflict(RelayError):
    pass


class RelayTimeout(RelayError):
    pass


class _RelaySession:
    def __init__(
        self,
        attempt_id: str,
        *,
        max_buffer_bytes: int,
        rendezvous_timeout: float,
        on_close,
    ) -> None:
        self.attempt_id = attempt_id
        self.max_buffer_bytes = max_buffer_bytes
        self.rendezvous_timeout = rendezvous_timeout
        self.on_close = on_close
        self.condition = threading.Condition()
        self.buffer: deque[bytes] = deque()
        self.buffered_bytes = 0
        self.expected_bytes: int | None = None
        self.producer_attached = False
        self.consumer_attached = False
        self.producer_finished = False
        self.bytes_written = 0
        self.bytes_read = 0
        self.error: BaseException | None = None
        self.closed = False
        self.created_at = time.monotonic()

    def attach_producer(self, expected_bytes: int) -> "RelayProducer":
        with self.condition:
            if self.producer_attached:
                raise RelayConflict("relay producer is already attached")
            self.producer_attached = True
            self.expected_bytes = int(expected_bytes)
            if self.expected_bytes < 0:
                raise ValueError("expected relay size must not be negative")
            self.condition.notify_all()
        return RelayProducer(self)

    def attach_consumer(self) -> "RelayConsumer":
        with self.condition:
            if self.consumer_attached:
                raise RelayConflict("relay consumer is already attached")
            self.consumer_attached = True
            self.condition.notify_all()
        return RelayConsumer(self)

    def fail(self, error: BaseException) -> None:
        with self.condition:
            if self.error is None:
                self.error = error
            self.condition.notify_all()
        self._close_if_finished(force=True)

    def _deadline(self) -> float:
        return self.created_at + self.rendezvous_timeout

    def _wait(self, predicate, missing_side: str) -> None:
        while not predicate():
            if self.error is not None:
                raise self.error
            remaining = self._deadline() - time.monotonic()
            if remaining <= 0:
                error = RelayTimeout(
                    f"relay timed out waiting for {missing_side}"
                )
                self.error = error
                self.closed = True
                self.condition.notify_all()
                self.on_close(self.attempt_id, self)
                raise error
            self.condition.wait(timeout=remaining)

    def _close_if_finished(self, *, force: bool = False) -> None:
        should_close = False
        with self.condition:
            if not self.closed and (
                force
                or (
                    self.producer_finished
                    and not self.buffer
                    and self.bytes_read == self.bytes_written
                )
            ):
                self.closed = True
                should_close = True
                self.condition.notify_all()
        if should_close:
            self.on_close(self.attempt_id, self)


class RelayProducer:
    def __init__(self, session: _RelaySession) -> None:
        self.session = session

    @property
    def bytes_written(self) -> int:
        return self.session.bytes_written

    def write(self, value: bytes) -> None:
        raw = bytes(value)
        if not raw:
            return
        if len(raw) > self.session.max_buffer_bytes:
            for offset in range(0, len(raw), self.session.max_buffer_bytes):
                self.write(raw[offset:offset + self.session.max_buffer_bytes])
            return
        with self.session.condition:
            self.session._wait(
                lambda: self.session.consumer_attached,
                "consumer",
            )
            self.session._wait(
                lambda: (
                    self.session.buffered_bytes + len(raw)
                    <= self.session.max_buffer_bytes
                ),
                "buffer capacity",
            )
            if self.session.producer_finished:
                raise RelayConflict("relay producer has already finished")
            self.session.buffer.append(raw)
            self.session.buffered_bytes += len(raw)
            self.session.bytes_written += len(raw)
            self.session.condition.notify_all()

    def finish(self) -> None:
        with self.session.condition:
            expected = self.session.expected_bytes
            if expected is not None and self.session.bytes_written != expected:
                error = ValueError(
                    f"relay expected {expected} bytes, received "
                    f"{self.session.bytes_written}"
                )
                self.session.error = error
                self.session.condition.notify_all()
                raise error
            self.session.producer_finished = True
            self.session.condition.notify_all()
        self.session._close_if_finished()

    def fail(self, error: BaseException) -> None:
        self.session.fail(error)


class RelayConsumer:
    def __init__(self, session: _RelaySession) -> None:
        self.session = session

    @property
    def bytes_read(self) -> int:
        return self.session.bytes_read

    def iter_chunks(self) -> Iterator[bytes]:
        while True:
            with self.session.condition:
                self.session._wait(
                    lambda: (
                        self.session.producer_attached
                        and bool(self.session.buffer)
                    )
                    or self.session.producer_finished,
                    "producer",
                )
                if self.session.error is not None:
                    raise self.session.error
                if not self.session.buffer and self.session.producer_finished:
                    break
                chunk = self.session.buffer.popleft()
                self.session.buffered_bytes -= len(chunk)
                self.session.bytes_read += len(chunk)
                self.session.condition.notify_all()
            yield chunk
        self.session._close_if_finished()


class RelayRegistry:
    def __init__(
        self,
        *,
        max_buffer_bytes: int = 4 * 1024 * 1024,
        rendezvous_timeout: float = 30.0,
    ) -> None:
        self.max_buffer_bytes = max(1, int(max_buffer_bytes))
        self.rendezvous_timeout = max(0.01, float(rendezvous_timeout))
        self._lock = threading.Lock()
        self._sessions: dict[str, _RelaySession] = {}

    def _session(self, attempt_id: str) -> _RelaySession:
        identifier = str(attempt_id or "").strip()
        if not identifier:
            raise ValueError("attempt_id is required")
        with self._lock:
            return self._sessions.setdefault(identifier, _RelaySession(
                identifier,
                max_buffer_bytes=self.max_buffer_bytes,
                rendezvous_timeout=self.rendezvous_timeout,
                on_close=self._remove,
            ))

    def _remove(self, attempt_id: str, session: _RelaySession) -> None:
        with self._lock:
            if self._sessions.get(attempt_id) is session:
                self._sessions.pop(attempt_id, None)

    def attach_producer(
        self, attempt_id: str, *, expected_bytes: int,
    ) -> RelayProducer:
        return self._session(attempt_id).attach_producer(expected_bytes)

    def attach_consumer(self, attempt_id: str) -> RelayConsumer:
        return self._session(attempt_id).attach_consumer()

    def get(self, attempt_id: str) -> _RelaySession | None:
        with self._lock:
            return self._sessions.get(str(attempt_id))
