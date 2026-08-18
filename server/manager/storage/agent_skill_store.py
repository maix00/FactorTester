"""Manager-local Profile Skill selections."""

from __future__ import annotations

import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from tools.data.sqlite.db import connect_sqlite
TABLE = "manager_profile_skill_selections"


class AgentSkillStore:
    """Persist only the selected Skill ids, never copied Skill files."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path).expanduser().resolve()
        self._lock = threading.RLock()
        self._initialize()

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            connection = connect_sqlite(self.db_path, timeout=5.0)
            try:
                with connection:
                    yield connection
            finally:
                connection.close()

    def _initialize(self) -> None:
        with self._connection() as db:
            db.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {TABLE} (
                    principal TEXT NOT NULL,
                    profile_id TEXT NOT NULL,
                    skill_id TEXT NOT NULL,
                    selected_at REAL NOT NULL,
                    PRIMARY KEY (principal, profile_id, skill_id)
                )
                """
            )

    @staticmethod
    def _text(value: object, field: str) -> str:
        result = str(value or "").strip()
        if not result:
            raise ValueError(f"{field} is required")
        if len(result) > 256:
            raise ValueError(f"{field} is too long")
        return result

    def selected(self, principal: str, profile_id: str) -> list[str]:
        owner = self._text(principal, "principal")
        profile = self._text(profile_id, "profile_id")
        with self._connection() as db:
            rows = db.execute(
                f"""SELECT skill_id FROM {TABLE}
                    WHERE principal = ? AND profile_id = ?
                    ORDER BY skill_id""",
                (owner, profile),
            ).fetchall()
        return [str(row[0]) for row in rows]

    def replace(
        self,
        principal: str,
        profile_id: str,
        skill_ids: list[str],
        *,
        now: float | None = None,
    ) -> list[str]:
        owner = self._text(principal, "principal")
        profile = self._text(profile_id, "profile_id")
        normalized = sorted({self._text(value, "skill_id") for value in skill_ids})
        current = float(time.time() if now is None else now)
        with self._connection() as db:
            db.execute(
                f"DELETE FROM {TABLE} WHERE principal = ? AND profile_id = ?",
                (owner, profile),
            )
            db.executemany(
                f"""INSERT INTO {TABLE} (
                    principal, profile_id, skill_id, selected_at
                ) VALUES (?, ?, ?, ?)""",
                [(owner, profile, skill_id, current) for skill_id in normalized],
            )
        return normalized
