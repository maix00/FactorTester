"""Small manager-owned index for cross-port job summaries.

Service instances remain authoritative for job details.  This index only
stores the latest summary observed by Manager, so a slow or stopped port does
not make the already-known list disappear.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Iterable


class ManagerJobIndex:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._connect() as db:
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
        with self._lock, self._connect() as db:
            db.executemany(
                """INSERT INTO jobs(principal, port, job_id, updated_at, payload)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(principal, port, job_id) DO UPDATE SET
                     updated_at=excluded.updated_at, payload=excluded.payload""",
                rows,
            )

    def list(self, principal: str, limit: int = 200) -> list[dict[str, Any]]:
        with self._lock, self._connect() as db:
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
