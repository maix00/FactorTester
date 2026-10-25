"""Durable transactional outbox for FactorTester Job dispatch.

The outbox is written in the same SQLite transaction as the Job state change.
A dispatcher publishes the small :class:`DispatchMessage` to RabbitMQ and only
marks the row sent after the broker confirms.  Duplicate delivery is expected;
the worker claims by ``(job_id, attempt)`` idempotently.
"""

from __future__ import annotations

from dataclasses import dataclass
import sqlite3
import time
from pathlib import Path
from typing import Any

import orjson

from tools.data.sqlite.db import connect_sqlite

from .contract import DispatchMessage

PENDING = "pending"
PUBLISHING = "publishing"
SENT = "sent"
FAILED = "failed"
DEAD = "dead"

_STATUSES = (PENDING, PUBLISHING, SENT, FAILED, DEAD)
_DEFAULT_MAX_ATTEMPTS = 8
_CLAIM_LEASE_SECONDS = 30.0


def ensure_dispatch_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS research_job_dispatch_outbox (
            job_id TEXT NOT NULL,
            attempt INTEGER NOT NULL,
            deployment_id TEXT NOT NULL,
            run_spec_hash TEXT NOT NULL,
            job_spec_hash TEXT NOT NULL,
            schema_version INTEGER NOT NULL,
            message_json TEXT NOT NULL,
            message_hash TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            attempts INTEGER NOT NULL DEFAULT 0,
            available_at REAL NOT NULL,
            lease_until REAL,
            created_at REAL NOT NULL,
            sent_at REAL,
            last_error TEXT NOT NULL DEFAULT '',
            PRIMARY KEY (job_id, attempt),
            CHECK (attempt >= 1),
            CHECK (schema_version >= 1),
            CHECK (status IN ('pending', 'publishing', 'sent', 'failed', 'dead'))
        );
        CREATE INDEX IF NOT EXISTS idx_job_dispatch_ready
            ON research_job_dispatch_outbox(status, available_at, created_at);
        """
    )


def enqueue(
    conn: sqlite3.Connection,
    message: DispatchMessage,
    *,
    now: float | None = None,
) -> None:
    """Insert one outbox row in the caller's transaction (idempotent)."""

    timestamp = time.time() if now is None else float(now)
    wire = orjson.dumps(message.to_dict(), option=orjson.OPT_SORT_KEYS).decode()
    conn.execute(
        """
        INSERT OR IGNORE INTO research_job_dispatch_outbox (
            job_id, attempt, deployment_id, run_spec_hash, job_spec_hash,
            schema_version, message_json, message_hash, status, attempts,
            available_at, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', 0, ?, ?)
        """,
        (
            message.job_id,
            message.attempt,
            message.deployment_id,
            message.run_spec_hash,
            message.job_spec_hash,
            message.schema_version,
            wire,
            message.digest(),
            timestamp,
            timestamp,
        ),
    )


def cancel_job_in_connection(
    conn: sqlite3.Connection, job_id: str, attempt: int,
    *, reason: str = "job_cancelled",
) -> None:
    """Cancel inside an existing Job transaction (same commit boundary)."""
    conn.execute(
        """
        UPDATE research_job_dispatch_outbox
        SET status='dead', lease_until=NULL, last_error=?
        WHERE job_id=? AND attempt=? AND status IN ('pending', 'failed', 'publishing')
        """,
        (str(reason)[:2000], str(job_id), int(attempt)),
    )


@dataclass(frozen=True, slots=True)
class OutboxRecord:
    job_id: str
    attempt: int
    deployment_id: str
    message: DispatchMessage
    status: str
    attempts: int

    @property
    def identity(self) -> tuple[str, int]:
        return self.job_id, self.attempt


class DispatchOutbox:
    """Small SQLite repository for dispatch rows; no broker imports here."""

    def __init__(
        self,
        db_path: str | Path,
        *,
        max_attempts: int = _DEFAULT_MAX_ATTEMPTS,
        lease_seconds: float = _CLAIM_LEASE_SECONDS,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        self.db_path = Path(db_path)
        self.max_attempts = int(max_attempts)
        self.lease_seconds = max(1.0, float(lease_seconds))

    def ensure_schema(self) -> None:
        with connect_sqlite(self.db_path) as conn:
            ensure_dispatch_schema(conn)

    def enqueue(self, message: DispatchMessage, *, now: float | None = None) -> None:
        with connect_sqlite(self.db_path) as conn:
            ensure_dispatch_schema(conn)
            enqueue(conn, message, now=now)

    def claim(
        self, *, limit: int = 1, now: float | None = None,
    ) -> list[OutboxRecord]:
        """Lease ready rows.  Concurrent dispatchers cannot claim the same row."""

        if limit < 1:
            return []
        timestamp = time.time() if now is None else float(now)
        records: list[OutboxRecord] = []
        conn = connect_sqlite(self.db_path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            ensure_dispatch_schema(conn)
            rows = conn.execute(
                """
                SELECT * FROM research_job_dispatch_outbox
                WHERE (
                    status IN ('pending', 'failed') AND available_at <= ?
                ) OR (
                    status='publishing' AND lease_until IS NOT NULL
                    AND lease_until <= ?
                )
                ORDER BY created_at, job_id, attempt
                LIMIT ?
                """,
                (timestamp, timestamp, int(limit)),
            ).fetchall()
            for row in rows:
                conn.execute(
                    """
                    UPDATE research_job_dispatch_outbox
                    SET status='publishing', lease_until=?, attempts=attempts+1
                    WHERE job_id=? AND attempt=? AND status=?
                    """,
                    (
                        timestamp + self.lease_seconds,
                        row["job_id"],
                        row["attempt"],
                        row["status"],
                    ),
                )
                attempts = int(row["attempts"]) + 1
                message = DispatchMessage.from_dict(orjson.loads(row["message_json"]))
                records.append(
                    OutboxRecord(
                        job_id=row["job_id"],
                        attempt=int(row["attempt"]),
                        deployment_id=row["deployment_id"],
                        message=message,
                        status=PUBLISHING,
                        attempts=attempts,
                    )
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        return records

    def cancel_job(self, job_id: str, attempt: int, *, reason: str = "job_cancelled") -> None:
        """Terminally close an unsent row when the Job is cancelled."""
        with connect_sqlite(self.db_path) as conn:
            ensure_dispatch_schema(conn)
            conn.execute(
                """
                UPDATE research_job_dispatch_outbox
                SET status='dead', lease_until=NULL, last_error=?
                WHERE job_id=? AND attempt=? AND status IN ('pending', 'failed', 'publishing')
                """,
                (str(reason)[:2000], str(job_id), int(attempt)),
            )

    def mark_sent(
        self, identity: tuple[str, int], *, now: float | None = None,
    ) -> None:
        timestamp = time.time() if now is None else float(now)
        with connect_sqlite(self.db_path) as conn:
            ensure_dispatch_schema(conn)
            conn.execute(
                """
                UPDATE research_job_dispatch_outbox
                SET status='sent', sent_at=?, lease_until=NULL, last_error=''
                WHERE job_id=? AND attempt=? AND status='publishing'
                """,
                (timestamp, identity[0], identity[1]),
            )

    def mark_failed(
        self,
        identity: tuple[str, int],
        error: str,
        *,
        now: float | None = None,
        retry_delay: float = 5.0,
    ) -> str:
        """Return the resulting status; exhausted rows become dead, not retried."""

        timestamp = time.time() if now is None else float(now)
        with connect_sqlite(self.db_path) as conn:
            ensure_dispatch_schema(conn)
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT attempts FROM research_job_dispatch_outbox
                WHERE job_id=? AND attempt=?
                """,
                identity,
            ).fetchone()
            if row is None:
                raise KeyError(f"dispatch row not found: {identity!r}")
            attempts = int(row["attempts"])
            status = DEAD if attempts >= self.max_attempts else FAILED
            conn.execute(
                """
                UPDATE research_job_dispatch_outbox
                SET status=?, available_at=?, lease_until=NULL, last_error=?
                WHERE job_id=? AND attempt=?
                """,
                (
                    status,
                    timestamp + max(0.0, float(retry_delay)),
                    str(error)[:2000],
                    identity[0],
                    identity[1],
                ),
            )
            conn.commit()
        return status

    def requeue(self, identity: tuple[str, int], *, now: float | None = None) -> None:
        """Manually return a failed/dead row to the dispatcher."""
        timestamp = time.time() if now is None else float(now)
        with connect_sqlite(self.db_path) as conn:
            ensure_dispatch_schema(conn)
            cursor = conn.execute(
                """
                UPDATE research_job_dispatch_outbox
                SET status='pending', available_at=?, lease_until=NULL,
                    last_error='', attempts=0
                WHERE job_id=? AND attempt=? AND status IN ('failed', 'dead')
                """,
                (timestamp, identity[0], identity[1]),
            )
            if cursor.rowcount != 1:
                raise ValueError("only failed or dead dispatch rows can be requeued")

    def get(self, identity: tuple[str, int]) -> OutboxRecord | None:
        conn = connect_sqlite(self.db_path)
        try:
            ensure_dispatch_schema(conn)
            row = conn.execute(
                """
                SELECT * FROM research_job_dispatch_outbox
                WHERE job_id=? AND attempt=?
                """,
                identity,
            ).fetchone()
        finally:
            conn.close()
        if row is None:
            return None
        return OutboxRecord(
            job_id=row["job_id"],
            attempt=int(row["attempt"]),
            deployment_id=row["deployment_id"],
            message=DispatchMessage.from_dict(orjson.loads(row["message_json"])),
            status=row["status"],
            attempts=int(row["attempts"]),
        )

    def counts(self) -> dict[str, int]:
        conn = connect_sqlite(self.db_path)
        try:
            ensure_dispatch_schema(conn)
            rows = conn.execute(
                """
                SELECT status, COUNT(*) AS total
                FROM research_job_dispatch_outbox
                GROUP BY status
                """
            ).fetchall()
        finally:
            conn.close()
        result = {status: 0 for status in _STATUSES}
        for row in rows:
            result[str(row["status"])] = int(row["total"])
        return result
