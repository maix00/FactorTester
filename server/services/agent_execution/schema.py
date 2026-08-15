"""SQLite schema for durable Agent execution identities."""

from __future__ import annotations

from pathlib import Path
import sqlite3

from tools.data.sqlite.db import connect_sqlite


EXECUTION_TABLES = frozenset({"agent_executions"})
EXECUTION_COLUMNS = frozenset({
    "execution_id",
    "owner_user_id",
    "agent_id",
    "actor_role",
    "authority_scope",
    "task_ref",
    "purpose",
    "agent_principal_hash",
    "lineage_hash",
    "created_at",
})


def connect_agent_execution(db_path: str | Path) -> sqlite3.Connection:
    return connect_sqlite(db_path, foreign_keys=True)


def ensure_schema(db_path: str | Path) -> None:
    with connect_agent_execution(db_path) as conn:
        tables = _tables(conn)
        if not tables:
            create_schema(conn)
            return
        if tables != EXECUTION_TABLES:
            raise RuntimeError(
                "Agent execution database contains unexpected tables: "
                + ", ".join(sorted(tables))
            )
        if table_columns(conn, "agent_executions") != EXECUTION_COLUMNS:
            raise RuntimeError(
                "Agent execution database has an unsupported schema"
            )


def create_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_executions (
            execution_id TEXT PRIMARY KEY,
            owner_user_id TEXT NOT NULL,
            agent_id TEXT NOT NULL,
            actor_role TEXT NOT NULL,
            authority_scope TEXT NOT NULL,
            task_ref TEXT NOT NULL DEFAULT '',
            purpose TEXT NOT NULL DEFAULT '',
            agent_principal_hash TEXT NOT NULL,
            lineage_hash TEXT NOT NULL,
            created_at REAL NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_agent_executions_owner
        ON agent_executions(owner_user_id, agent_id, created_at)
        """
    )


def table_columns(
    conn: sqlite3.Connection,
    table: str,
) -> frozenset[str]:
    return frozenset(
        str(row["name"])
        for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
    )


def _tables(conn: sqlite3.Connection) -> frozenset[str]:
    return frozenset(
        str(row["name"])
        for row in conn.execute(
            """
            SELECT name FROM sqlite_master
            WHERE type='table' AND name NOT LIKE 'sqlite_%'
            """
        ).fetchall()
    )
