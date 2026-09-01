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

    def list_entries(self, *, query: str = "") -> list[dict[str, Any]]:
        needle = str(query or "").strip().lower()
        with self._lock, connect_sqlite(self.db_path, readonly=True) as db:
            rows = db.execute(
                """SELECT * FROM strategy_library_entries
                   WHERE deleted_at=0
                     AND (?='' OR lower(name) LIKE ? OR lower(strategy_ref) LIKE ?)
                   ORDER BY updated_at DESC, strategy_ref""",
                (needle, f"%{needle}%", f"%{needle}%"),
            ).fetchall()
        return [self._entry(row) for row in rows]

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

    def update_entry(
        self, strategy_ref: str, *, name: str, description: str,
        visibility: str,
    ) -> None:
        with self._lock, connect_sqlite(self.db_path, timeout=10) as db:
            db.execute(
                """UPDATE strategy_library_entries
                   SET name=?, description=?, visibility=?, updated_at=?
                   WHERE strategy_ref=? AND deleted_at=0""",
                (name, description, visibility, time.time(), strategy_ref),
            )

    def add_revision(
        self,
        strategy_ref: str,
        *,
        source_sha256: str,
        source_code: str,
        entrypoint: str,
        hooks: list[dict[str, Any]],
        requirements: dict[str, Any],
        created_by: str,
    ) -> dict[str, Any]:
        now = time.time()
        revision_ref = f"strategy-revision:{uuid4().hex}"
        with self._lock, connect_sqlite(self.db_path, timeout=10) as db:
            row = db.execute(
                "SELECT COALESCE(MAX(revision_number), 0) AS number FROM strategy_library_revisions WHERE strategy_ref=?",
                (strategy_ref,),
            ).fetchone()
            number = int(row["number"] or 0) + 1
            db.execute(
                """INSERT INTO strategy_library_revisions
                   (revision_ref, strategy_ref, revision_number, source_sha256,
                    source_code, entrypoint, hooks_json, requirements_json,
                    created_by, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (revision_ref, strategy_ref, number, source_sha256, source_code,
                 entrypoint, json.dumps(hooks, ensure_ascii=False),
                 json.dumps(requirements, ensure_ascii=False), created_by, now),
            )
            db.execute(
                "UPDATE strategy_library_entries SET current_revision_ref=?, updated_at=? WHERE strategy_ref=? AND deleted_at=0",
                (revision_ref, now, strategy_ref),
            )
        return {"revision_ref": revision_ref, "revision_number": number}

    def get_revision(self, revision_ref: str) -> dict[str, Any] | None:
        with self._lock, connect_sqlite(self.db_path, readonly=True) as db:
            row = db.execute(
                "SELECT * FROM strategy_library_revisions WHERE revision_ref=?",
                (revision_ref,),
            ).fetchone()
        return self._revision(row) if row is not None else None

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

