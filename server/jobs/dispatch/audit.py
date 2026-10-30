"""Append-only audit records for dispatch operations."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path


def append_audit(db_path: str | Path, *, action: str, actor: str,
                 job_id: str = "", attempt: int = 0, detail: str = "",
                 idempotent: bool = False) -> None:
    if idempotent and not str(job_id or "").strip():
        raise ValueError("idempotent audit requires an operation identity")
    with sqlite3.connect(db_path) as conn:
        if idempotent:
            conn.execute("BEGIN IMMEDIATE")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS job_dispatch_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action TEXT NOT NULL,
                actor TEXT NOT NULL,
                job_id TEXT NOT NULL DEFAULT '',
                attempt INTEGER NOT NULL DEFAULT 0,
                detail TEXT NOT NULL DEFAULT '',
                created_at REAL NOT NULL
            )
        """)
        if idempotent:
            row = conn.execute(
                "SELECT detail FROM job_dispatch_audit WHERE action=? AND actor=? AND job_id=? LIMIT 1",
                (str(action), str(actor), str(job_id)),
            ).fetchone()
            if row is not None:
                if row[0] != str(detail):
                    raise ValueError("audit operation identity was reused with different details")
                return
        conn.execute(
            "INSERT INTO job_dispatch_audit (action,actor,job_id,attempt,detail,created_at) "
            "VALUES (?,?,?,?,?,?)",
            (str(action), str(actor), str(job_id), int(attempt), str(detail), time.time()),
        )


def list_audit(db_path: str | Path, *, limit: int = 50) -> list[dict]:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT * FROM job_dispatch_audit ORDER BY id DESC LIMIT ?", (int(limit),),
            ).fetchall()
        except sqlite3.OperationalError:
            return []
    return [dict(row) for row in rows]
