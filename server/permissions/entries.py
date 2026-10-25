"""Managed permission entries; default deny, explicit scopes."""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

RESOURCE_TYPES = {"report", "factor_version", "strategy_version", "job", "workspace"}
ACTIONS = {"read", "write", "publish", "approve", "delete", "share"}
SCOPES = {"self", "subtree", "organization", "explicit"}
EFFECTS = {"allow", "deny"}


@dataclass(frozen=True)
class PermissionEntry:
    subject: str
    resource_type: str
    resource_ref: str
    action: str
    scope: str = "explicit"
    effect: str = "allow"
    created_by: str = ""
    reason: str = ""

    def __post_init__(self) -> None:
        if not self.subject or not self.resource_ref:
            raise ValueError("subject and resource_ref are required")
        if self.resource_type not in RESOURCE_TYPES:
            raise ValueError("invalid resource_type")
        if self.action not in ACTIONS:
            raise ValueError("invalid action")
        if self.scope not in SCOPES:
            raise ValueError("invalid scope")
        if self.effect not in EFFECTS:
            raise ValueError("invalid effect")


class PermissionStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("""
            CREATE TABLE IF NOT EXISTS permission_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subject TEXT NOT NULL,
                resource_type TEXT NOT NULL,
                resource_ref TEXT NOT NULL,
                action TEXT NOT NULL,
                scope TEXT NOT NULL,
                effect TEXT NOT NULL,
                created_by TEXT NOT NULL,
                reason TEXT NOT NULL DEFAULT '',
                created_at REAL NOT NULL
            )
        """)
        return conn

    def add(self, entry: PermissionEntry) -> int:
        with self._conn() as conn:
            cur = conn.execute(
                """INSERT INTO permission_entries
                (subject,resource_type,resource_ref,action,scope,effect,created_by,reason,created_at)
                VALUES (?,?,?,?,?,?,?,?,?)""",
                (entry.subject, entry.resource_type, entry.resource_ref,
                 entry.action, entry.scope, entry.effect, entry.created_by,
                 entry.reason, time.time()),
            )
            return int(cur.lastrowid)

    def list(self, *, subject: str = "") -> list[PermissionEntry]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM permission_entries "
                + ("WHERE subject=? " if subject else "")
                + "ORDER BY id",
                ((subject,) if subject else ()),
            ).fetchall()
        return [PermissionEntry(
            subject=r["subject"], resource_type=r["resource_type"],
            resource_ref=r["resource_ref"], action=r["action"],
            scope=r["scope"], effect=r["effect"], created_by=r["created_by"],
            reason=r["reason"],
        ) for r in rows]

    def allows(self, *, subject: str, resource_type: str,
               resource_ref: str, action: str) -> bool:
        for entry in self.list(subject=subject):
            if (entry.resource_type == resource_type
                    and entry.resource_ref in {resource_ref, "*"}
                    and entry.action == action):
                return entry.effect == "allow"
        return False
