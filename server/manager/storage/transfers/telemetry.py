"""Persistent summaries for the Manager-local transfer byte plane."""

from __future__ import annotations

from dataclasses import dataclass
import secrets
import threading
import time

from server.manager.storage.transfers.database import TransferDatabase
from server.manager.storage.transfers.telemetry_constants import (
    ACTIVE_STREAM_STALE_SECONDS,
    ACTIVE_UPDATE_BYTES,
    ACTIVE_UPDATE_SECONDS,
    MAX_FAILURE_REASON_LENGTH,
    TELEMETRY_RETENTION_SECONDS,
)


@dataclass
class TransferTelemetryHandle:
    """One accepted or pending data-plane HTTP stream."""

    stream_id: str
    attempt_id: str
    transfer_id: str
    server_id: str
    object_kind: str
    operation: str
    mode: str
    surface: str
    action: str
    source_server_id: str
    destination_server_id: str
    expected_bytes: int
    process_instance_id: str
    started_at: float
    transferred_bytes: int = 0
    authorized: bool = False
    last_persist_at: float = 0.0
    last_persist_bytes: int = 0
    lock: threading.Lock | None = None


class TransferTelemetryStore(TransferDatabase):
    """Persist final Attempt metrics and lease-like active stream rows."""

    def begin(
        self,
        context,
        *,
        surface: str,
        action: str,
        process_instance_id: str,
        now: float | None = None,
    ) -> TransferTelemetryHandle:
        current = time.time() if now is None else float(now)
        transfer = context.transfer
        attempt = context.attempt
        return TransferTelemetryHandle(
            stream_id=secrets.token_hex(16),
            attempt_id=str(attempt.attempt_id),
            transfer_id=str(transfer.transfer_id),
            server_id=self.server_id,
            object_kind=str(transfer.object_kind or "job_artifact"),
            operation=str(transfer.operation.value),
            mode=str(attempt.mode.value),
            surface=str(surface or "client"),
            action=str(action),
            source_server_id=str(transfer.source_server_id),
            destination_server_id=str(transfer.destination_server_id),
            expected_bytes=max(
                0,
                int(attempt.expected_size) - int(attempt.resume_offset),
            ),
            process_instance_id=str(process_instance_id),
            started_at=current,
            last_persist_at=current,
            lock=threading.Lock(),
        )

    def authorize(self, handle: TransferTelemetryHandle) -> None:
        """Persist an active row only after the bearer ticket is valid."""
        if handle.authorized:
            return
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO transfer_active_streams(
                    stream_id, attempt_id, transfer_id, server_id,
                    object_kind, operation, mode, surface, action,
                    expected_bytes, transferred_bytes, started_at,
                    last_seen_at, process_instance_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    handle.stream_id,
                    handle.attempt_id,
                    handle.transfer_id,
                    handle.server_id,
                    handle.object_kind,
                    handle.operation,
                    handle.mode,
                    handle.surface,
                    handle.action,
                    handle.expected_bytes,
                    handle.transferred_bytes,
                    handle.started_at,
                    handle.started_at,
                    handle.process_instance_id,
                ),
            )
        handle.authorized = True

    def record_bytes(
        self,
        handle: TransferTelemetryHandle,
        count: int,
        *,
        now: float | None = None,
    ) -> None:
        value = int(count)
        if value < 0:
            raise ValueError("transferred byte count must not be negative")
        if value == 0:
            return
        lock = handle.lock
        if lock is None:
            lock = threading.Lock()
            handle.lock = lock
        with lock:
            handle.transferred_bytes += value
            if not handle.authorized:
                return
            current = time.time() if now is None else float(now)
            should_persist = (
                handle.transferred_bytes - handle.last_persist_bytes
                >= ACTIVE_UPDATE_BYTES
                or current - handle.last_persist_at >= ACTIVE_UPDATE_SECONDS
            )
            if should_persist:
                self._persist_active(handle, current)

    def set_expected_bytes(
        self,
        handle: TransferTelemetryHandle,
        expected_bytes: int,
        *,
        now: float | None = None,
    ) -> None:
        value = int(expected_bytes)
        if value < 0:
            raise ValueError("expected byte count must not be negative")
        current = time.time() if now is None else float(now)
        lock = handle.lock
        if lock is None:
            lock = threading.Lock()
            handle.lock = lock
        with lock:
            handle.expected_bytes = value
            if not handle.authorized:
                return
            with self._connect() as connection:
                connection.execute(
                    """
                    UPDATE transfer_active_streams
                    SET expected_bytes=?, last_seen_at=?
                    WHERE stream_id=?
                    """,
                    (value, current, handle.stream_id),
                )
            handle.last_persist_at = current

    def finish(
        self,
        handle: TransferTelemetryHandle,
        *,
        status: str,
        failure_reason: str = "",
        now: float | None = None,
    ) -> None:
        if not handle.authorized:
            return
        current = time.time() if now is None else float(now)
        lock = handle.lock
        if lock is None:
            lock = threading.Lock()
            handle.lock = lock
        with lock:
            self._persist_active(handle, current)
            reason = str(failure_reason or "").strip()
            reason = reason[:MAX_FAILURE_REASON_LENGTH]
            duration_ms = max(
                0, int(round((current - handle.started_at) * 1_000))
            )
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO transfer_telemetry(
                        attempt_id, transfer_id, server_id, object_kind,
                        operation, mode, surface, action, source_server_id,
                        destination_server_id, expected_bytes,
                        transferred_bytes, started_at, finished_at,
                        duration_ms, status, failure_reason
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(attempt_id) DO UPDATE SET
                        transfer_id=excluded.transfer_id,
                        server_id=excluded.server_id,
                        object_kind=excluded.object_kind,
                        operation=excluded.operation,
                        mode=excluded.mode,
                        surface=excluded.surface,
                        action=excluded.action,
                        source_server_id=excluded.source_server_id,
                        destination_server_id=excluded.destination_server_id,
                        expected_bytes=excluded.expected_bytes,
                        transferred_bytes=excluded.transferred_bytes,
                        started_at=excluded.started_at,
                        finished_at=excluded.finished_at,
                        duration_ms=excluded.duration_ms,
                        status=excluded.status,
                        failure_reason=excluded.failure_reason
                    """,
                    (
                        handle.attempt_id,
                        handle.transfer_id,
                        handle.server_id,
                        handle.object_kind,
                        handle.operation,
                        handle.mode,
                        handle.surface,
                        handle.action,
                        handle.source_server_id,
                        handle.destination_server_id,
                        handle.expected_bytes,
                        handle.transferred_bytes,
                        handle.started_at,
                        current,
                        duration_ms,
                        str(status or "failed"),
                        reason,
                    ),
                )
                connection.execute(
                    "DELETE FROM transfer_active_streams WHERE stream_id=?",
                    (handle.stream_id,),
                )
            handle.authorized = False

    def prune(
        self,
        *,
        now: float | None = None,
        retention_seconds: float = TELEMETRY_RETENTION_SECONDS,
        stale_seconds: float = ACTIVE_STREAM_STALE_SECONDS,
    ) -> None:
        current = time.time() if now is None else float(now)
        cutoff = current - max(60.0, float(retention_seconds))
        stale = current - max(5.0, float(stale_seconds))
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM transfer_telemetry WHERE finished_at < ?",
                (cutoff,),
            )
            connection.execute(
                "DELETE FROM transfer_active_streams WHERE last_seen_at < ?",
                (stale,),
            )

    def summary(
        self,
        *,
        object_kind: str = "",
        operation: str = "",
        since: float | None = None,
        until: float | None = None,
        now: float | None = None,
    ) -> dict[str, object]:
        from server.manager.storage.transfers.telemetry_summary import (
            build_summary,
        )

        return build_summary(
            self,
            object_kind=object_kind,
            operation=operation,
            since=since,
            until=until,
            now=now,
        )

    def _persist_active(
        self,
        handle: TransferTelemetryHandle,
        now: float,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE transfer_active_streams
                SET transferred_bytes=?, last_seen_at=?
                WHERE stream_id=?
                """,
                (handle.transferred_bytes, now, handle.stream_id),
            )
        handle.last_persist_at = now
        handle.last_persist_bytes = handle.transferred_bytes


__all__ = [
    "ACTIVE_STREAM_STALE_SECONDS",
    "TransferTelemetryHandle",
    "TransferTelemetryStore",
]
