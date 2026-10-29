"""Managed permission entries; default deny, explicit scopes."""

from __future__ import annotations

import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

RESOURCE_TYPES = {
    "report", "factor_version", "strategy_version", "job", "workspace",
    "admin_console", "agent_assistant",
}
ACTIONS = {
    "read", "write", "publish", "approve", "delete", "share", "manage",
    "use",
}
SCOPES = {"self", "subtree", "organization", "explicit"}
EFFECTS = {"allow", "deny"}
_SCHEMA_LOCK = threading.Lock()
_SCHEMA_READY: set[str] = set()


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
        database = str(self.db_path.expanduser().resolve())
        if database not in _SCHEMA_READY:
            with _SCHEMA_LOCK:
                if database not in _SCHEMA_READY:
                    self._initialize_schema(database)
                    _SCHEMA_READY.add(database)
        conn = sqlite3.connect(database, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 5000")
        return conn

    @staticmethod
    def _initialize_schema(database: str) -> None:
        # DDL runs once per database per Manager process, not on every
        # authorization lookup. PermissionStore instances are intentionally
        # short-lived at API boundaries.
        with sqlite3.connect(database, timeout=5.0) as conn:
            conn.execute("PRAGMA busy_timeout = 5000")
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
            conn.execute(
                "CREATE INDEX IF NOT EXISTS permission_entries_lookup "
                "ON permission_entries(subject, resource_type, action)"
            )
            conn.execute("""
                CREATE TABLE IF NOT EXISTS permission_entry_audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    subject TEXT NOT NULL,
                    resource_type TEXT NOT NULL,
                    resource_ref TEXT NOT NULL,
                    action TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    old_effect TEXT NOT NULL DEFAULT '',
                    new_effect TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    reason TEXT NOT NULL DEFAULT '',
                    changed_at REAL NOT NULL
                )
            """)

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

    def set_entry(self, entry: PermissionEntry) -> int:
        """Replace one exact rule and append an audit record atomically."""
        with self._conn() as conn:
            previous = conn.execute(
                "SELECT effect FROM permission_entries WHERE subject=? "
                "AND resource_type=? AND resource_ref=? AND action=? "
                "AND scope=? ORDER BY id DESC LIMIT 1",
                (entry.subject, entry.resource_type, entry.resource_ref,
                 entry.action, entry.scope),
            ).fetchone()
            old_effect = str(previous["effect"] or "") if previous else ""
            conn.execute(
                "DELETE FROM permission_entries WHERE subject=? "
                "AND resource_type=? AND resource_ref=? AND action=? "
                "AND scope=?",
                (entry.subject, entry.resource_type, entry.resource_ref,
                 entry.action, entry.scope),
            )
            cursor = conn.execute(
                """INSERT INTO permission_entries
                (subject,resource_type,resource_ref,action,scope,effect,created_by,reason,created_at)
                VALUES (?,?,?,?,?,?,?,?,?)""",
                (entry.subject, entry.resource_type, entry.resource_ref,
                 entry.action, entry.scope, entry.effect, entry.created_by,
                 entry.reason, time.time()),
            )
            conn.execute(
                """INSERT INTO permission_entry_audit
                (subject,resource_type,resource_ref,action,scope,old_effect,
                 new_effect,actor,reason,changed_at) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (entry.subject, entry.resource_type, entry.resource_ref,
                 entry.action, entry.scope, old_effect, entry.effect,
                 entry.created_by, entry.reason, time.time()),
            )
            return int(cursor.lastrowid)

    def remove_entry(
        self, *, subject: str, resource_type: str, resource_ref: str,
        action: str, scope: str, actor: str, reason: str,
    ) -> bool:
        """Remove one exact rule and audit the revocation atomically."""
        with self._conn() as conn:
            previous = conn.execute(
                "SELECT effect FROM permission_entries WHERE subject=? "
                "AND resource_type=? AND resource_ref=? AND action=? "
                "AND scope=? ORDER BY id DESC LIMIT 1",
                (subject, resource_type, resource_ref, action, scope),
            ).fetchone()
            if previous is None:
                return False
            conn.execute(
                "DELETE FROM permission_entries WHERE subject=? "
                "AND resource_type=? AND resource_ref=? AND action=? "
                "AND scope=?",
                (subject, resource_type, resource_ref, action, scope),
            )
            conn.execute(
                """INSERT INTO permission_entry_audit
                (subject,resource_type,resource_ref,action,scope,old_effect,
                 new_effect,actor,reason,changed_at) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (subject, resource_type, resource_ref, action, scope,
                 str(previous["effect"] or ""), "", actor, reason, time.time()),
            )
            return True

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

    @staticmethod
    def _matches(entry: PermissionEntry, resource_ref: str) -> bool:
        if entry.resource_ref == "*" or entry.resource_ref == resource_ref:
            return True
        if entry.scope == "subtree":
            return resource_ref.startswith(entry.resource_ref.rstrip(":") + ":")
        return False

    def allows(self, *, subject: str, resource_type: str,
               resource_ref: str, action: str) -> bool:
        return self.allows_any(
            subjects=(subject,), resource_type=resource_type,
            resource_ref=resource_ref, action=action,
        )

    def allows_any(
        self, *, subjects: tuple[str, ...] | list[str], resource_type: str,
        resource_ref: str, action: str,
    ) -> bool:
        """Evaluate all matching user/group/org rules with deny precedence."""
        normalized = tuple(dict.fromkeys(str(value) for value in subjects if value))
        if not normalized:
            return False
        placeholders = ",".join("?" for _ in normalized)
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT subject,resource_ref,scope,effect FROM permission_entries "
                f"WHERE subject IN ({placeholders}) AND resource_type=? AND action=?",
                (*normalized, resource_type, action),
            ).fetchall()
        matching_effects = [
            str(row["effect"] or "") for row in rows
            if self._matches(
                PermissionEntry(
                    subject=str(row["subject"]), resource_type=resource_type,
                    resource_ref=str(row["resource_ref"]), action=action,
                    scope=str(row["scope"]), effect=str(row["effect"]),
                ),
                resource_ref,
            )
        ]
        if "deny" in matching_effects:
            return False
        return "allow" in matching_effects

    def list_for_resource(
        self, *, resource_type: str, action: str,
    ) -> list[PermissionEntry]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM permission_entries WHERE resource_type=? "
                "AND action=? ORDER BY id",
                (resource_type, action),
            ).fetchall()
        return [PermissionEntry(
            subject=r["subject"], resource_type=r["resource_type"],
            resource_ref=r["resource_ref"], action=r["action"],
            scope=r["scope"], effect=r["effect"], created_by=r["created_by"],
            reason=r["reason"],
        ) for r in rows]

    def audit_for_resource(
        self, *, resource_type: str, action: str, limit: int = 50,
    ) -> list[dict[str, object]]:
        bounded = max(1, min(int(limit), 200))
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT subject,resource_ref,scope,action,old_effect,new_effect,"
                "actor,reason,changed_at FROM permission_entry_audit "
                "WHERE resource_type=? AND action=? ORDER BY id DESC LIMIT ?",
                (resource_type, action, bounded),
            ).fetchall()
        return [dict(row) for row in rows]
