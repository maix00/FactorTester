"""SQLite persistence for one active capability detour per branch."""

from __future__ import annotations

import sqlite3
from typing import Any

from .replay import reconstruct_from_trace
from .state import make_state, normalize_state


def create_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS research_graph_capability_detours (
            instance_id TEXT NOT NULL,
            branch_id TEXT NOT NULL,
            resume_node TEXT NOT NULL,
            origin_trace_id TEXT NOT NULL,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            PRIMARY KEY (instance_id, branch_id)
        )
        """
    )


def load_state(
    conn: sqlite3.Connection,
    *,
    instance_id: str,
    branch_id: str,
) -> dict[str, Any] | None:
    try:
        row = conn.execute(
            """
            SELECT resume_node, origin_trace_id
            FROM research_graph_capability_detours
            WHERE instance_id=? AND branch_id=?
            """,
            (instance_id, branch_id),
        ).fetchone()
    except sqlite3.OperationalError as exc:
        if "no such table" not in str(exc):
            raise
        return None
    return (
        make_state(row["resume_node"], row["origin_trace_id"])
        if row else None
    )


def load_or_reconstruct(
    conn: sqlite3.Connection,
    *,
    instance_id: str,
    branch_id: str,
) -> dict[str, Any] | None:
    return load_state(
        conn, instance_id=instance_id, branch_id=branch_id
    ) or reconstruct_from_trace(
        conn, instance_id=instance_id, branch_id=branch_id
    )


def persist_state(
    conn: sqlite3.Connection,
    *,
    instance_id: str,
    branch_id: str,
    state: dict[str, Any] | None,
    now: float,
) -> None:
    create_schema(conn)
    current = normalize_state(state)
    if current is None:
        conn.execute(
            """
            DELETE FROM research_graph_capability_detours
            WHERE instance_id=? AND branch_id=?
            """,
            (instance_id, branch_id),
        )
        return
    conn.execute(
        """
        INSERT INTO research_graph_capability_detours (
            instance_id, branch_id, resume_node, origin_trace_id,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(instance_id, branch_id) DO UPDATE SET
            resume_node=excluded.resume_node,
            origin_trace_id=excluded.origin_trace_id,
            updated_at=excluded.updated_at
        """,
        (
            instance_id, branch_id, current["resume_node"],
            current["origin_trace_id"], now, now,
        ),
    )
