"""Small manager-owned index for cross-port job summaries.

Service instances remain authoritative for job details.  This index only
stores the latest summary observed by Manager, so a slow or stopped port does
not make the already-known list disappear.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Iterable


class ManagerJobIndex:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._connection() as db:
            db.execute(
                """CREATE TABLE IF NOT EXISTS jobs (
                    principal TEXT NOT NULL,
                    port INTEGER NOT NULL,
                    job_id TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT '',
                    payload TEXT NOT NULL,
                    PRIMARY KEY (principal, port, job_id)
                )"""
            )
            db.execute(
                """CREATE INDEX IF NOT EXISTS jobs_order
                   ON jobs(principal, updated_at DESC)"""
            )

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        return db

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        """Close each connection after its transaction scope completes."""
        db = self._connect()
        try:
            with db:
                yield db
        finally:
            db.close()

    def upsert(self, principal: str, jobs: Iterable[dict[str, Any]]) -> None:
        rows = []
        for job in jobs:
            job_id = str(job.get("job_id") or "").strip()
            port = job.get("port")
            if not job_id or not isinstance(port, int):
                continue
            rows.append((
                principal, port, job_id,
                str(job.get("updated_at") or ""),
                json.dumps(job, ensure_ascii=False, separators=(",", ":")),
            ))
        if not rows:
            return
        with self._lock, self._connection() as db:
            db.executemany(
                """INSERT INTO jobs(principal, port, job_id, updated_at, payload)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(principal, port, job_id) DO UPDATE SET
                     updated_at=excluded.updated_at, payload=excluded.payload""",
                rows,
            )

    def list(self, principal: str, limit: int = 200) -> list[dict[str, Any]]:
        with self._lock, self._connection() as db:
            rows = db.execute(
                """SELECT payload FROM jobs WHERE principal=?
                   ORDER BY updated_at DESC LIMIT ?""",
                (principal, max(1, min(limit, 2000))),
            ).fetchall()
        result = []
        for row in rows:
            try:
                value = json.loads(row["payload"])
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if isinstance(value, dict):
                result.append(value)
        return result

    def page(
        self, principal: str, *, page: int = 1, limit: int = 20,
    ) -> dict[str, Any]:
        return self.page_for_principals(
            [principal], page=page, limit=limit,
        )

    def page_for_principals(
        self, principals: Iterable[str], *, page: int = 1, limit: int = 20,
    ) -> dict[str, Any]:
        bounded_limit = max(1, min(int(limit), 100))
        requested_page = max(1, int(page))
        values = [str(item).strip() for item in principals if str(item).strip()]
        if not values:
            return {
                "jobs": [], "page": requested_page, "page_size": 0,
                "total": 0, "total_pages": 1, "has_more": False,
                "next_cursor": None,
            }
        placeholders = ",".join("?" for _ in values)
        start = (requested_page - 1) * bounded_limit
        with self._lock, self._connection() as db:
            total = int(db.execute(
                f"SELECT COUNT(DISTINCT job_id) FROM jobs WHERE principal IN ({placeholders})",
                values,
            ).fetchone()[0])
            rows = db.execute(
                f"""
                SELECT payload FROM (
                    SELECT payload, job_id, updated_at, port,
                           ROW_NUMBER() OVER (
                               PARTITION BY job_id
                               ORDER BY updated_at DESC, port DESC
                           ) AS row_number
                    FROM jobs
                    WHERE principal IN ({placeholders})
                )
                WHERE row_number = 1
                ORDER BY updated_at DESC, job_id DESC
                LIMIT ? OFFSET ?
                """,
                [*values, bounded_limit, start],
            ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            try:
                value = json.loads(row["payload"])
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if isinstance(value, dict):
                result.append(value)
        return {
            "jobs": result,
            "page": requested_page,
            "page_size": len(result),
            "total": total,
            "total_pages": max(1, (total + bounded_limit - 1) // bounded_limit),
            "has_more": start + len(result) < total,
            "next_cursor": None,
        }

    def list_all(self, limit: int = 200) -> list[dict[str, Any]]:
        """Return the newest distinct jobs observed across principals.

        Manager may observe the same public job under its public projection
        and the submitting user's private projection.  De-duplicate by job
        ID so a stale public projection cannot hide a newer observed summary.
        """
        bounded = max(1, min(int(limit), 2000))
        with self._lock, self._connection() as db:
            rows = db.execute(
                """SELECT payload FROM jobs
                   ORDER BY updated_at DESC LIMIT ?""",
                (min(2000, max(bounded * 4, bounded)),),
            ).fetchall()
        result: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in rows:
            try:
                value = json.loads(row["payload"])
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if not isinstance(value, dict):
                continue
            job_id = str(value.get("job_id") or "").strip()
            if not job_id or job_id in seen:
                continue
            seen.add(job_id)
            result.append(value)
            if len(result) >= bounded:
                break
        return result

    def ports_for(self, principal: str, job_id: str) -> list[int]:
        """Return cached origins for a known job, newest first.

        The index is routing metadata only; the service remains authoritative
        for the detail response.  A stopped cached port is still useful to
        try before falling back to the currently running services.
        """
        with self._lock, self._connection() as db:
            rows = db.execute(
                """SELECT port FROM jobs
                   WHERE principal=? AND job_id=?
                   ORDER BY updated_at DESC""",
                (principal, str(job_id)),
            ).fetchall()
        return [int(row["port"]) for row in rows]
