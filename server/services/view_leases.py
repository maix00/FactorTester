"""Durable browser-view observer leases."""

from __future__ import annotations

import os
import sqlite3
import time
from typing import Any

import settings as Settings
from tools.data.sqlite.db import connect_sqlite


VIEW_LEASE_GRACE_SECONDS = max(
    0.0,
    float(os.environ.get("GTHT_VIEW_LEASE_GRACE_SECONDS", "10.0")),
)


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS research_view_leases (
            view_uuid TEXT PRIMARY KEY,
            owner TEXT NOT NULL,
            workspace_id TEXT NOT NULL,
            status TEXT NOT NULL,
            last_heartbeat_at REAL NOT NULL,
            detached_at REAL,
            expires_at REAL,
            updated_at REAL NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_research_view_leases_expiry "
        "ON research_view_leases(status, expires_at)"
    )


def _payload(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "view_uuid": str(row["view_uuid"]),
        "owner": str(row["owner"]),
        "workspace_id": str(row["workspace_id"]),
        "status": str(row["status"]),
        "last_heartbeat_at": float(row["last_heartbeat_at"]),
        "detached_at": row["detached_at"],
        "expires_at": row["expires_at"],
    }


def renew(*, view_uuid: str, owner: str, workspace_id: str) -> dict[str, Any]:
    now = time.time()
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        _ensure_schema(conn)
        existing = conn.execute(
            "SELECT owner FROM research_view_leases WHERE view_uuid = ?",
            (view_uuid,),
        ).fetchone()
        if existing is not None and str(existing["owner"]) != owner:
            raise PermissionError("view lease belongs to another user")
        conn.execute(
            """
            INSERT INTO research_view_leases (
                view_uuid, owner, workspace_id, status, last_heartbeat_at,
                detached_at, expires_at, updated_at
            ) VALUES (?, ?, ?, 'active', ?, NULL, NULL, ?)
            ON CONFLICT(view_uuid) DO UPDATE SET
                workspace_id = excluded.workspace_id,
                status = 'active',
                last_heartbeat_at = excluded.last_heartbeat_at,
                detached_at = NULL,
                expires_at = NULL,
                updated_at = excluded.updated_at
            """,
            (view_uuid, owner, workspace_id, now, now),
        )
        row = conn.execute(
            "SELECT * FROM research_view_leases WHERE view_uuid = ?",
            (view_uuid,),
        ).fetchone()
        return _payload(row) or {}


def detach(*, view_uuid: str, owner: str) -> dict[str, Any] | None:
    now = time.time()
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        _ensure_schema(conn)
        row = conn.execute(
            "SELECT * FROM research_view_leases WHERE view_uuid = ? AND owner = ?",
            (view_uuid, owner),
        ).fetchone()
        if row is None:
            return None
        conn.execute(
            """
            UPDATE research_view_leases
            SET status = 'detaching', detached_at = ?, expires_at = ?, updated_at = ?
            WHERE view_uuid = ? AND owner = ?
            """,
            (now, now + VIEW_LEASE_GRACE_SECONDS, now, view_uuid, owner),
        )
        updated = conn.execute(
            "SELECT * FROM research_view_leases WHERE view_uuid = ?",
            (view_uuid,),
        ).fetchone()
        return _payload(updated)


def expire_due_leases(*, now: float | None = None) -> int:
    now = time.time() if now is None else float(now)
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        _ensure_schema(conn)
        rows = conn.execute(
            """
            SELECT view_uuid, owner
            FROM research_view_leases
            WHERE status = 'detaching' AND expires_at <= ?
            """,
            (now,),
        ).fetchall()
        conn.executemany(
            """
            UPDATE research_view_leases
            SET status = 'expired', updated_at = ?
            WHERE view_uuid = ? AND owner = ? AND status = 'detaching'
            """,
            [(now, row["view_uuid"], row["owner"]) for row in rows],
        )
    if rows:
        from server.services import test_jobs

        for row in rows:
            test_jobs.expire_view(str(row["view_uuid"]), str(row["owner"]))
    return len(rows)


def load(*, view_uuid: str, owner: str) -> dict[str, Any] | None:
    expire_due_leases()
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        _ensure_schema(conn)
        row = conn.execute(
            "SELECT * FROM research_view_leases WHERE view_uuid = ? AND owner = ?",
            (view_uuid, owner),
        ).fetchone()
        return _payload(row)
