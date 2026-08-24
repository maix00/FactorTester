"""Durable per-server state for public factor source replication."""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Iterable
from pathlib import Path

from tools.data.sqlite.db import connect_sqlite


class PublicFactorReplicationStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser().resolve()
        with connect_sqlite(self.path) as connection:
            self._ensure_schema(connection)

    @staticmethod
    def _ensure_schema(connection: sqlite3.Connection) -> None:
        connection.executescript("""
            CREATE TABLE IF NOT EXISTS public_factor_replications(
                factor_id TEXT NOT NULL,
                source_sha256 TEXT NOT NULL,
                source_bytes INTEGER NOT NULL,
                target_server_id TEXT NOT NULL,
                principal TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                attempts INTEGER NOT NULL DEFAULT 0,
                last_error TEXT NOT NULL DEFAULT '',
                updated_at REAL NOT NULL,
                PRIMARY KEY(factor_id, target_server_id)
            );
            CREATE INDEX IF NOT EXISTS public_factor_replications_status
                ON public_factor_replications(status, updated_at);
        """)

    def declare(
        self,
        factors: Iterable[dict[str, object]],
        targets: Iterable[str],
        *,
        principal: str,
        local_server_id: str,
    ) -> None:
        now = time.time()
        with connect_sqlite(self.path) as connection:
            self._ensure_schema(connection)
            for factor in factors:
                factor_id = str(factor.get("factor_id") or "").strip()
                digest = str(factor.get("source_sha256") or "").strip().lower()
                size = int(factor.get("source_bytes") or -1)
                if not factor_id or len(digest) != 64 or size < 0:
                    raise ValueError("public factor replication descriptor is invalid")
                for target in dict.fromkeys(str(item).strip() for item in targets):
                    if not target:
                        continue
                    status = "completed" if target == local_server_id else "pending"
                    connection.execute("""
                        INSERT INTO public_factor_replications(
                            factor_id, source_sha256, source_bytes,
                            target_server_id, principal, status, attempts,
                            last_error, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, 0, '', ?)
                        ON CONFLICT(factor_id, target_server_id) DO UPDATE SET
                            source_sha256=excluded.source_sha256,
                            source_bytes=excluded.source_bytes,
                            principal=excluded.principal,
                            status=CASE
                                WHEN public_factor_replications.source_sha256
                                     = excluded.source_sha256
                                THEN public_factor_replications.status
                                ELSE excluded.status
                            END,
                            attempts=CASE
                                WHEN public_factor_replications.source_sha256
                                     = excluded.source_sha256
                                THEN public_factor_replications.attempts
                                ELSE 0
                            END,
                            last_error=CASE
                                WHEN public_factor_replications.source_sha256
                                     = excluded.source_sha256
                                THEN public_factor_replications.last_error
                                ELSE ''
                            END,
                            updated_at=excluded.updated_at
                    """, (
                        factor_id, digest, size, target, principal,
                        status, now,
                    ))

    def pending(self, *, limit: int = 256) -> list[dict[str, object]]:
        with connect_sqlite(self.path) as connection:
            self._ensure_schema(connection)
            rows = connection.execute("""
                SELECT factor_id, source_sha256, source_bytes,
                       target_server_id, principal, status, attempts,
                       last_error, updated_at
                FROM public_factor_replications
                WHERE status != 'completed'
                ORDER BY updated_at, factor_id, target_server_id
                LIMIT ?
            """, (max(1, min(1000, int(limit))),)).fetchall()
        return [dict(row) for row in rows]

    def publications(self) -> list[dict[str, object]]:
        """Return each factor's latest declared publication descriptor."""
        with connect_sqlite(self.path) as connection:
            self._ensure_schema(connection)
            rows = connection.execute("""
                SELECT factor_id, source_sha256, source_bytes, principal
                FROM public_factor_replications AS current
                WHERE updated_at = (
                    SELECT MAX(candidate.updated_at)
                    FROM public_factor_replications AS candidate
                    WHERE candidate.factor_id = current.factor_id
                )
                GROUP BY factor_id
                ORDER BY factor_id
            """).fetchall()
        return [dict(row) for row in rows]

    def record(
        self,
        factor_id: str,
        target_server_id: str,
        *,
        status: str,
        error: str = "",
    ) -> None:
        with connect_sqlite(self.path) as connection:
            self._ensure_schema(connection)
            connection.execute("""
                UPDATE public_factor_replications
                SET status=?, attempts=attempts + 1,
                    last_error=?, updated_at=?
                WHERE factor_id=? AND target_server_id=?
            """, (
                status, str(error or "")[:1000], time.time(),
                factor_id, target_server_id,
            ))

    def summary(self, factor_ids: Iterable[str]) -> dict[str, object]:
        selected = list(dict.fromkeys(str(item).strip() for item in factor_ids))
        if not selected:
            return {"complete": True, "targets": []}
        placeholders = ",".join("?" for _ in selected)
        with connect_sqlite(self.path) as connection:
            self._ensure_schema(connection)
            rows = connection.execute(f"""
                SELECT factor_id, source_sha256, target_server_id,
                       status, attempts, last_error
                FROM public_factor_replications
                WHERE factor_id IN ({placeholders})
                ORDER BY target_server_id, factor_id
            """, selected).fetchall()
        targets = [dict(row) for row in rows]
        return {
            "complete": bool(targets) and all(
                row["status"] == "completed" for row in targets
            ),
            "targets": targets,
        }


__all__ = ["PublicFactorReplicationStore"]
