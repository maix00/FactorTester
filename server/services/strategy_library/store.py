"""Small SQLite store for Strategy metadata, revisions, and shares."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from tools.data.sqlite.db import connect_sqlite


class StrategyLibraryStore:
    """Keep source revisions separate from request and UI projections."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path).expanduser().resolve()
        self._lock = threading.RLock()
        self.ensure_schema()

    def ensure_schema(self) -> None:
        with self._lock, connect_sqlite(self.db_path, timeout=10) as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS strategy_library_entries (
                    strategy_ref TEXT PRIMARY KEY,
                    owner_ref TEXT NOT NULL,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL,
                    visibility TEXT NOT NULL,
                    current_revision_ref TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    deleted_at REAL NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS strategy_library_revisions (
                    revision_ref TEXT PRIMARY KEY,
                    strategy_ref TEXT NOT NULL,
                    revision_number INTEGER NOT NULL,
                    source_sha256 TEXT NOT NULL,
                    source_code TEXT NOT NULL,
                    entrypoint TEXT NOT NULL,
                    hooks_json TEXT NOT NULL,
                    requirements_json TEXT NOT NULL,
                    created_by TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    UNIQUE(strategy_ref, revision_number)
                );
                CREATE TABLE IF NOT EXISTS strategy_library_shares (
                    strategy_ref TEXT NOT NULL,
                    principal_ref TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    PRIMARY KEY(strategy_ref, principal_ref)
                );
                CREATE INDEX IF NOT EXISTS idx_strategy_library_owner
                    ON strategy_library_entries(owner_ref, updated_at);
                CREATE INDEX IF NOT EXISTS idx_strategy_library_visibility
                    ON strategy_library_entries(visibility, updated_at);
                CREATE INDEX IF NOT EXISTS idx_strategy_library_revision
                    ON strategy_library_revisions(strategy_ref, revision_number);
                CREATE INDEX IF NOT EXISTS idx_strategy_library_share_principal
                    ON strategy_library_shares(principal_ref, strategy_ref);
                """
            )

    @staticmethod
    def _entry(row: Any) -> dict[str, Any]:
        return {
            "strategy_ref": str(row["strategy_ref"]),
            "owner_ref": str(row["owner_ref"]),
            "name": str(row["name"]),
            "description": str(row["description"]),
            "visibility": str(row["visibility"]),
            "current_revision_ref": str(row["current_revision_ref"]),
            "created_at": float(row["created_at"]),
            "updated_at": float(row["updated_at"]),
        }

    @staticmethod
    def _revision(row: Any, *, include_source: bool = True) -> dict[str, Any]:
        value: dict[str, Any] = {
            "revision_ref": str(row["revision_ref"]),
            "strategy_ref": str(row["strategy_ref"]),
            "revision_number": int(row["revision_number"]),
            "source_sha256": str(row["source_sha256"]),
            "entrypoint": str(row["entrypoint"]),
            "hooks": json.loads(str(row["hooks_json"] or "[]")),
            "requirements": json.loads(str(row["requirements_json"] or "{}")),
            "created_by": str(row["created_by"]),
            "created_at": float(row["created_at"]),
        }
        if include_source:
            value["source_code"] = str(row["source_code"])
        return value

    def list_visible_entries(
        self,
        *,
        principal: str,
        scope: str,
        subordinate_users: set[str],
        query: str = "",
        page: int = 1,
        limit: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        """Page visible summaries with one SQL read for entries and revisions."""
        scope_sql, scope_params = self._scope_sql(
            scope, principal, subordinate_users,
        )
        needle = str(query or "").strip().lower()
        query_sql = ""
        query_params: list[Any] = []
        if needle:
            query_sql = " AND (lower(e.name) LIKE ? OR lower(e.strategy_ref) LIKE ?)"
            query_params = [f"%{needle}%", f"%{needle}%"]
        from_sql = """
            FROM strategy_library_entries AS e
            JOIN strategy_library_revisions AS r
              ON r.revision_ref = e.current_revision_ref
            LEFT JOIN strategy_library_shares AS s
              ON s.strategy_ref = e.strategy_ref AND s.principal_ref = ?
        """
        where_sql = f"""
            WHERE e.deleted_at = 0
              {query_sql}
              AND ({scope_sql})
        """
        base_params = [principal, *query_params, *scope_params]
        page = max(1, int(page))
        limit = max(1, min(100, int(limit)))
        offset = (page - 1) * limit
        with self._lock, connect_sqlite(self.db_path, readonly=True) as db:
            total = int(db.execute(
                f"SELECT COUNT(*) AS total {from_sql} {where_sql}",
                base_params,
            ).fetchone()["total"])
            rows = db.execute(
                f"""
                SELECT e.strategy_ref, e.owner_ref, e.name, e.description,
                       e.visibility, e.current_revision_ref, e.created_at,
                       e.updated_at, r.revision_ref,
                       r.strategy_ref AS revision_strategy_ref,
                       r.revision_number, r.source_sha256, r.entrypoint,
                       r.hooks_json, r.requirements_json, r.created_by,
                       r.created_at AS revision_created_at,
                       s.strategy_ref AS shared_strategy_ref
                {from_sql}
                {where_sql}
                ORDER BY e.updated_at DESC, e.strategy_ref
                LIMIT ? OFFSET ?
                """,
                [*base_params, limit, offset],
            ).fetchall()
        return [self._visible_entry(row) for row in rows], total

    @staticmethod
    def _scope_sql(
        scope: str,
        principal: str,
        subordinate_users: set[str],
    ) -> tuple[str, list[Any]]:
        if scope == "mine":
            return "e.owner_ref = ?", [principal]
        if scope == "subordinates":
            if not subordinate_users:
                return "0", []
            placeholders = ", ".join("?" for _ in subordinate_users)
            return f"e.owner_ref IN ({placeholders})", sorted(subordinate_users)
        if scope == "shared":
            return (
                "e.owner_ref <> ? AND e.visibility IN ('shared', 'public') "
                "AND (e.visibility = 'public' OR s.strategy_ref IS NOT NULL)",
                [principal],
            )
        if scope == "all":
            owner_sql = ["e.owner_ref = ?"]
            params: list[Any] = [principal]
            if subordinate_users:
                placeholders = ", ".join("?" for _ in subordinate_users)
                owner_sql.append(f"e.owner_ref IN ({placeholders})")
                params.extend(sorted(subordinate_users))
            owner_sql.extend([
                "e.visibility = 'public'",
                "(e.visibility = 'shared' AND s.strategy_ref IS NOT NULL)",
            ])
            return " OR ".join(f"({value})" for value in owner_sql), params
        raise ValueError("strategy scope must be mine, subordinates, shared, or all")

    @classmethod
    def _visible_entry(cls, row: Any) -> dict[str, Any]:
        return {
            "entry": cls._entry(row),
            "revision": {
                "revision_ref": str(row["revision_ref"]),
                "strategy_ref": str(row["revision_strategy_ref"]),
                "revision_number": int(row["revision_number"]),
                "source_sha256": str(row["source_sha256"]),
                "entrypoint": str(row["entrypoint"]),
                "hooks": json.loads(str(row["hooks_json"] or "[]")),
                "requirements": json.loads(str(row["requirements_json"] or "{}")),
                "created_by": str(row["created_by"]),
                "created_at": float(row["revision_created_at"]),
            },
            "explicitly_shared": row["shared_strategy_ref"] is not None,
        }

    def get_entry(self, strategy_ref: str) -> dict[str, Any] | None:
        with self._lock, connect_sqlite(self.db_path, readonly=True) as db:
            row = db.execute(
                "SELECT * FROM strategy_library_entries WHERE strategy_ref=? AND deleted_at=0",
                (strategy_ref,),
            ).fetchone()
        return self._entry(row) if row is not None else None

    def create(
        self,
        *,
        owner_ref: str,
        name: str,
        description: str,
        visibility: str,
        source_sha256: str,
        source_code: str,
        entrypoint: str,
        hooks: list[dict[str, Any]],
        requirements: dict[str, Any],
        created_by: str,
    ) -> dict[str, Any]:
        now = time.time()
        strategy_ref = f"strategy:{uuid4().hex}"
        revision_ref = f"strategy-revision:{uuid4().hex}"
        with self._lock, connect_sqlite(self.db_path, timeout=10) as db:
            db.execute(
                """INSERT INTO strategy_library_entries
                   (strategy_ref, owner_ref, name, description, visibility,
                    current_revision_ref, created_at, updated_at, deleted_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)""",
                (strategy_ref, owner_ref, name, description, visibility,
                 revision_ref, now, now),
            )
            db.execute(
                """INSERT INTO strategy_library_revisions
                   (revision_ref, strategy_ref, revision_number, source_sha256,
                    source_code, entrypoint, hooks_json, requirements_json,
                    created_by, created_at)
                   VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?, ?)""",
                (revision_ref, strategy_ref, source_sha256, source_code,
                 entrypoint, json.dumps(hooks, ensure_ascii=False),
                 json.dumps(requirements, ensure_ascii=False), created_by, now),
            )
        return {"strategy_ref": strategy_ref, "revision_ref": revision_ref}

    def update_entry_with_revision(
        self,
        strategy_ref: str,
        *,
        name: str,
        description: str,
        visibility: str,
        expected_revision_ref: str,
        revision: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Update metadata and, when needed, its current revision atomically."""
        now = time.time()
        with self._lock, connect_sqlite(self.db_path, timeout=10) as db:
            current = db.execute(
                """SELECT current_revision_ref
                   FROM strategy_library_entries
                   WHERE strategy_ref=? AND deleted_at=0""",
                (strategy_ref,),
            ).fetchone()
            if current is None:
                raise KeyError("strategy not found")
            current_ref = str(current["current_revision_ref"])
            if current_ref != str(expected_revision_ref):
                raise ValueError("strategy revision changed")

            revision_ref = current_ref
            revision_number = None
            if revision is not None:
                row = db.execute(
                    """SELECT COALESCE(MAX(revision_number), 0) AS number
                       FROM strategy_library_revisions
                       WHERE strategy_ref=?""",
                    (strategy_ref,),
                ).fetchone()
                revision_number = int(row["number"] or 0) + 1
                revision_ref = f"strategy-revision:{uuid4().hex}"
                db.execute(
                    """INSERT INTO strategy_library_revisions
                       (revision_ref, strategy_ref, revision_number, source_sha256,
                        source_code, entrypoint, hooks_json, requirements_json,
                        created_by, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        revision_ref, strategy_ref, revision_number,
                        revision["source_sha256"], revision["source_code"],
                        revision["entrypoint"],
                        json.dumps(revision["hooks"], ensure_ascii=False),
                        json.dumps(revision["requirements"], ensure_ascii=False),
                        revision["created_by"], now,
                    ),
                )

            result = db.execute(
                """UPDATE strategy_library_entries
                   SET name=?, description=?, visibility=?,
                       current_revision_ref=?, updated_at=?
                   WHERE strategy_ref=? AND current_revision_ref=? AND deleted_at=0""",
                (
                    name, description, visibility, revision_ref, now,
                    strategy_ref, current_ref,
                ),
            )
            if result.rowcount != 1:
                raise ValueError("strategy revision changed")
        return {
            "revision_ref": revision_ref,
            "revision_number": revision_number,
        }

    def get_revision(
        self, revision_ref: str, *, include_source: bool = True,
    ) -> dict[str, Any] | None:
        with self._lock, connect_sqlite(self.db_path, readonly=True) as db:
            row = db.execute(
                "SELECT * FROM strategy_library_revisions WHERE revision_ref=?",
                (revision_ref,),
            ).fetchone()
        return self._revision(row, include_source=include_source) if row is not None else None

    def list_revisions(self, strategy_ref: str) -> list[dict[str, Any]]:
        with self._lock, connect_sqlite(self.db_path, readonly=True) as db:
            rows = db.execute(
                "SELECT * FROM strategy_library_revisions WHERE strategy_ref=? ORDER BY revision_number DESC",
                (strategy_ref,),
            ).fetchall()
        return [self._revision(row, include_source=False) for row in rows]

    def delete(self, strategy_ref: str) -> bool:
        with self._lock, connect_sqlite(self.db_path, timeout=10) as db:
            result = db.execute(
                "UPDATE strategy_library_entries SET deleted_at=?, updated_at=? WHERE strategy_ref=? AND deleted_at=0",
                (time.time(), time.time(), strategy_ref),
            )
        return result.rowcount == 1

    def shares(self, strategy_ref: str) -> list[str]:
        with self._lock, connect_sqlite(self.db_path, readonly=True) as db:
            rows = db.execute(
                "SELECT principal_ref FROM strategy_library_shares WHERE strategy_ref=? ORDER BY principal_ref",
                (strategy_ref,),
            ).fetchall()
        return [str(row["principal_ref"]) for row in rows]

    def grant(self, strategy_ref: str, principal_ref: str) -> None:
        with self._lock, connect_sqlite(self.db_path, timeout=10) as db:
            db.execute(
                "INSERT OR IGNORE INTO strategy_library_shares(strategy_ref, principal_ref, created_at) VALUES (?, ?, ?)",
                (strategy_ref, principal_ref, time.time()),
            )

    def revoke(self, strategy_ref: str, principal_ref: str) -> bool:
        with self._lock, connect_sqlite(self.db_path, timeout=10) as db:
            result = db.execute(
                "DELETE FROM strategy_library_shares WHERE strategy_ref=? AND principal_ref=?",
                (strategy_ref, principal_ref),
            )
        return result.rowcount == 1
