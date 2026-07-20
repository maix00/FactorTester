"""SQLite schema and connection policy for Maintenance Cases."""

from __future__ import annotations

from pathlib import Path
import sqlite3

from tools.data.sqlite.db import connect_sqlite


def connect_maintenance_cases(
    db_path: str | Path,
) -> sqlite3.Connection:
    return connect_sqlite(db_path)


def create_schema(conn: sqlite3.Connection) -> None:
    """Create the sole Maintenance Case owner in a caller transaction."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS research_maintenance_cases (
            case_id TEXT PRIMARY KEY,
            owner_user_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            descriptor_hash TEXT NOT NULL,
            status TEXT NOT NULL CHECK (
                status IN ('open', 'claimed', 'blocked', 'resolved', 'rejected')
            ),
            affected_refs_json TEXT NOT NULL,
            change_refs_json TEXT NOT NULL,
            conversation_ref TEXT NOT NULL DEFAULT '',
            claimed_agent_id TEXT NOT NULL DEFAULT '',
            latest_result_ref TEXT NOT NULL DEFAULT '',
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            claimed_at REAL,
            closed_at REAL,
            CHECK (
                (
                    status = 'open'
                    AND claimed_agent_id = ''
                    AND claimed_at IS NULL
                )
                OR (
                    status IN ('claimed', 'blocked', 'resolved', 'rejected')
                    AND claimed_agent_id != ''
                    AND claimed_at IS NOT NULL
                )
            ),
            CHECK (
                (status IN ('resolved', 'rejected') AND closed_at IS NOT NULL)
                OR (status NOT IN ('resolved', 'rejected') AND closed_at IS NULL)
            ),
            UNIQUE (owner_user_id, descriptor_hash)
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_maintenance_cases_queue
        ON research_maintenance_cases(
            owner_user_id, status, kind, updated_at
        )
        """
    )


def ensure_schema(db_path: str | Path) -> None:
    with connect_maintenance_cases(db_path) as conn:
        create_schema(conn)
