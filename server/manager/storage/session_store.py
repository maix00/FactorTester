"""SQLite persistence for Manager authentication sessions.

The session database is deliberately local to one Manager.  PostgreSQL owns
accounts and devices, but it is not on the request path for an already-issued
session.  The legacy ``sessions.json`` file is intentionally not read here;
deployments may retain it as a rollback artifact until the new store is
verified.
"""

from __future__ import annotations

import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from collections.abc import Iterator, Mapping
from pathlib import Path

from tools.data.sqlite.db import connect_sqlite


SESSION_TABLE = "manager_sessions"
SESSION_COLUMNS = (
    "token_hash",
    "principal",
    "role",
    "authentication",
    "origin",
    "alias",
    "created_at",
    "last_seen_at",
    "expires_at",
)


def configured_manager_sqlite_path() -> Path:
    """Return the existing Manager-local SQLite database from ``.settings``.

    Local accounts, factors, research projections, and the data-plane job
    repository already use this database. Session records add a dedicated
    table to that database instead of creating another SQLite file beside
    Manager state files.
    """
    import settings as Settings

    return Path(Settings.CACHE_DB_PATH).expanduser().resolve()


class ManagerSessionStore:
    """Persist session records in a protected, Manager-local SQLite file."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        return connect_sqlite(self.path, timeout=5.0)

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            connection = self._connect()
            try:
                with connection:
                    yield connection
            finally:
                connection.close()

    def _initialize(self) -> None:
        with self._connection() as db:
            db.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {SESSION_TABLE} (
                    token_hash TEXT PRIMARY KEY,
                    principal TEXT NOT NULL,
                    role TEXT NOT NULL,
                    authentication TEXT NOT NULL DEFAULT 'password',
                    origin TEXT NOT NULL DEFAULT '',
                    alias TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    last_seen_at REAL NOT NULL,
                    expires_at REAL NOT NULL
                )
                """
            )
            db.execute(
                f"""CREATE INDEX IF NOT EXISTS {SESSION_TABLE}_expiry
                    ON {SESSION_TABLE}(expires_at)"""
            )
            db.execute(
                f"""CREATE INDEX IF NOT EXISTS {SESSION_TABLE}_idle
                    ON {SESSION_TABLE}(last_seen_at)"""
            )
            db.execute(
                f"""CREATE INDEX IF NOT EXISTS {SESSION_TABLE}_principal
                    ON {SESSION_TABLE}(principal)"""
            )
        # Session material is authentication state even though token values
        # are never stored.  Make the SQLite file owner-only on every startup.
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            # A read-only test fixture can still be queried; the first write
            # will surface the underlying SQLite error to the caller.
            pass

    @staticmethod
    def _timestamp(value: object, fallback: float) -> float:
        try:
            return float(value)
        except (TypeError, ValueError, OverflowError):
            return fallback

    @classmethod
    def _record_values(
        cls,
        token_hash: str,
        value: tuple[object, ...],
        *,
        now: float | None = None,
    ) -> tuple[object, ...]:
        current = float(time.time() if now is None else now)
        principal = str(value[0] if len(value) >= 1 else "")
        role = str(value[1] if len(value) >= 2 else "")
        expires_at = cls._timestamp(
            value[2] if len(value) >= 3 else 0,
            current,
        )
        authentication = str(
            value[3] if len(value) >= 4 else "password"
        ) or "password"
        origin = str(value[4] if len(value) >= 5 else "").strip().rstrip("/")
        alias = str(value[5] if len(value) >= 6 else "").strip()
        created_at = cls._timestamp(
            value[6] if len(value) >= 7 else current,
            current,
        )
        last_seen_at = cls._timestamp(
            value[7] if len(value) >= 8 else current,
            current,
        )
        return (
            str(token_hash),
            principal,
            role,
            authentication,
            origin,
            alias,
            created_at,
            last_seen_at,
            expires_at,
        )

    @staticmethod
    def _tuple(row: sqlite3.Row) -> tuple[object, ...]:
        return (
            str(row["principal"] or ""),
            str(row["role"] or ""),
            float(row["expires_at"] or 0),
            str(row["authentication"] or "password"),
            str(row["origin"] or "").strip().rstrip("/"),
            str(row["alias"] or "").strip(),
            float(row["created_at"] or 0),
            float(row["last_seen_at"] or 0),
        )

    def load(
        self,
        *,
        now: float | None = None,
        idle_ttl: float | None = None,
    ) -> dict[str, tuple[object, ...]]:
        """Load live records and remove expired/long-idle rows atomically."""
        current = float(time.time() if now is None else now)
        idle_cutoff = (
            current - float(idle_ttl)
            if idle_ttl is not None and float(idle_ttl) > 0
            else None
        )
        with self._connection() as db:
            self._delete_inactive(db, current, idle_cutoff)
            rows = db.execute(
                f"""SELECT token_hash, principal, role, authentication,
                           origin, alias, created_at, last_seen_at, expires_at
                    FROM {SESSION_TABLE}"""
            ).fetchall()
        return {str(row["token_hash"]): self._tuple(row) for row in rows}

    @staticmethod
    def _delete_inactive(
        db: sqlite3.Connection,
        now: float,
        idle_cutoff: float | None,
    ) -> int:
        if idle_cutoff is None:
            cursor = db.execute(
                f"DELETE FROM {SESSION_TABLE} WHERE expires_at <= ?",
                (now,),
            )
        else:
            cursor = db.execute(
                f"""DELETE FROM {SESSION_TABLE}
                    WHERE expires_at <= ? OR last_seen_at <= ?""",
                (now, idle_cutoff),
            )
        return int(cursor.rowcount or 0)

    def cleanup(
        self,
        *,
        now: float | None = None,
        idle_ttl: float | None = None,
    ) -> int:
        """Delete only expired or explicitly long-idle sessions."""
        current = float(time.time() if now is None else now)
        idle_cutoff = (
            current - float(idle_ttl)
            if idle_ttl is not None and float(idle_ttl) > 0
            else None
        )
        with self._connection() as db:
            return self._delete_inactive(db, current, idle_cutoff)

    def upsert(
        self,
        token_hash: str,
        value: tuple[object, ...],
        *,
        now: float | None = None,
    ) -> None:
        values = self._record_values(token_hash, value, now=now)
        with self._connection() as db:
            db.execute(
                f"""INSERT INTO {SESSION_TABLE} ({', '.join(SESSION_COLUMNS)})
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(token_hash) DO UPDATE SET
                        principal=excluded.principal,
                        role=excluded.role,
                        authentication=excluded.authentication,
                        origin=excluded.origin,
                        alias=excluded.alias,
                        created_at=excluded.created_at,
                        last_seen_at=excluded.last_seen_at,
                        expires_at=excluded.expires_at""",
                values,
            )

    def replace(
        self,
        records: Mapping[str, tuple[object, ...]],
        *,
        now: float | None = None,
    ) -> None:
        current = float(time.time() if now is None else now)
        values = [
            self._record_values(token_hash, value, now=current)
            for token_hash, value in records.items()
        ]
        with self._connection() as db:
            db.execute(f"DELETE FROM {SESSION_TABLE}")
            if values:
                db.executemany(
                    f"""INSERT INTO {SESSION_TABLE}
                        ({', '.join(SESSION_COLUMNS)})
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    values,
                )

    def delete(self, token_hash: str) -> None:
        with self._connection() as db:
            db.execute(
                f"DELETE FROM {SESSION_TABLE} WHERE token_hash=?",
                (str(token_hash),),
            )
