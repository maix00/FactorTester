"""Manager-local conversation catalog for research Profiles.

Conversation identity belongs to an authenticated principal and Profile.  A
provider-specific thread id is only a resumable runtime binding, so changing
or stopping an Agent does not remove the conversation.  Message content stays
solely in the Provider thread and is never mirrored into this SQLite catalog.
"""

from __future__ import annotations

import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from tools.data.sqlite.db import connect_sqlite


TABLE = "manager_agent_conversations"
ITEM_TABLE = "manager_agent_conversation_items"
SHARING_TABLE = "manager_agent_profile_conversation_sharing"
_COLUMNS = {
    "conversation_id",
    "principal",
    "profile_id",
    "provider_id",
    "provider_thread_id",
    "title",
    "preview",
    "created_at",
    "updated_at",
    "active",
}
_RUNTIME_COLUMNS = {
    "model_id": "TEXT NOT NULL DEFAULT ''",
    "reasoning_effort": "TEXT NOT NULL DEFAULT ''",
    "service_tier": "TEXT NOT NULL DEFAULT ''",
    "actual_model": "TEXT NOT NULL DEFAULT ''",
    "model_context_window": "INTEGER NOT NULL DEFAULT 0",
    "total_tokens": "INTEGER NOT NULL DEFAULT 0",
    "last_tokens": "INTEGER NOT NULL DEFAULT 0",
    "compaction_count": "INTEGER NOT NULL DEFAULT 0",
}

class AgentConversationStore:
    """Persist and list multiple conversations for one Profile."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path).expanduser().resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
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

    @staticmethod
    def _create_table(db: sqlite3.Connection) -> None:
        db.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {TABLE} (
                conversation_id TEXT PRIMARY KEY,
                principal TEXT NOT NULL,
                profile_id TEXT NOT NULL,
                provider_id TEXT NOT NULL DEFAULT '',
                provider_thread_id TEXT NOT NULL DEFAULT '',
                title TEXT NOT NULL DEFAULT '',
                preview TEXT NOT NULL DEFAULT '',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                active INTEGER NOT NULL DEFAULT 0,
                model_id TEXT NOT NULL DEFAULT '',
                reasoning_effort TEXT NOT NULL DEFAULT '',
                service_tier TEXT NOT NULL DEFAULT '',
                actual_model TEXT NOT NULL DEFAULT '',
                model_context_window INTEGER NOT NULL DEFAULT 0,
                total_tokens INTEGER NOT NULL DEFAULT 0,
                last_tokens INTEGER NOT NULL DEFAULT 0,
                compaction_count INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        db.execute(
            f"""CREATE INDEX IF NOT EXISTS {TABLE}_profile_updated
                ON {TABLE}(principal, profile_id, updated_at DESC)"""
        )
        db.execute(
            f"""CREATE INDEX IF NOT EXISTS {TABLE}_active
                ON {TABLE}(principal, profile_id, active)"""
        )
        # Remove the legacy transcript mirror.  Provider threads are the sole
        # authority and are read through the source Manager on demand.
        db.execute(f"DROP TABLE IF EXISTS {ITEM_TABLE}")
        db.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {SHARING_TABLE} (
                principal TEXT NOT NULL,
                profile_id TEXT NOT NULL,
                share_to_parent INTEGER NOT NULL DEFAULT 0,
                updated_at REAL NOT NULL,
                PRIMARY KEY (principal, profile_id)
            )
            """
        )

    def _initialize(self) -> None:
        with self._connection() as db:
            existing = {
                str(row[1])
                for row in db.execute(f"PRAGMA table_info({TABLE})").fetchall()
            }
            if existing and not _COLUMNS.issubset(existing):
                legacy = f"{TABLE}_legacy_{uuid.uuid4().hex[:10]}"
                db.execute(f"ALTER TABLE {TABLE} RENAME TO {legacy}")
                self._create_table(db)
                old_columns = {
                    str(row[1])
                    for row in db.execute(f"PRAGMA table_info({legacy})").fetchall()
                }
                if {"principal", "profile_id", "thread_id"}.issubset(old_columns):
                    rows = db.execute(
                        f"""SELECT principal, profile_id, thread_id,
                                   title, created_at, updated_at
                            FROM {legacy}"""
                    ).fetchall()
                    for row in rows:
                        conversation_id = f"conversation-{uuid.uuid4().hex}"
                        db.execute(
                            f"""INSERT INTO {TABLE} (
                                    conversation_id, principal, profile_id,
                                    provider_thread_id, title, created_at,
                                    updated_at, active
                                ) VALUES (?, ?, ?, ?, ?, ?, ?, 1)""",
                            (
                                conversation_id,
                                str(row[0] or ""),
                                str(row[1] or ""),
                                str(row[2] or ""),
                                str(row[3] or ""),
                                float(row[4] or time.time()),
                                float(row[5] or time.time()),
                            ),
                        )
                db.execute(f"DROP TABLE {legacy}")
            # The auxiliary tables are idempotent and are created after the
            # legacy migration as well as for new Manager SQLite files.
            self._create_table(db)
            columns = {
                str(row[1])
                for row in db.execute(f"PRAGMA table_info({TABLE})").fetchall()
            }
            for name, declaration in _RUNTIME_COLUMNS.items():
                if name not in columns:
                    db.execute(
                        f"ALTER TABLE {TABLE} ADD COLUMN {name} {declaration}"
                    )

    @staticmethod
    def _required(value: object, field: str, limit: int = 512) -> str:
        result = str(value or "").strip()
        if not result:
            raise ValueError(f"{field} is required")
        if len(result) > limit:
            raise ValueError(f"{field} is too long")
        return result

    @classmethod
    def _row(cls, row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        return {
            "conversation_id": str(row["conversation_id"] or ""),
            "principal": str(row["principal"] or ""),
            "profile_id": str(row["profile_id"] or ""),
            "provider_id": str(row["provider_id"] or ""),
            "provider_thread_id": str(row["provider_thread_id"] or ""),
            "title": str(row["title"] or ""),
            "preview": str(row["preview"] or ""),
            "created_at": float(row["created_at"] or 0),
            "updated_at": float(row["updated_at"] or 0),
            "active": bool(row["active"]),
            "model_id": str(row["model_id"] or ""),
            "reasoning_effort": str(row["reasoning_effort"] or ""),
            "service_tier": str(row["service_tier"] or ""),
            "actual_model": str(row["actual_model"] or ""),
            "model_context_window": int(row["model_context_window"] or 0),
            "total_tokens": int(row["total_tokens"] or 0),
            "last_tokens": int(row["last_tokens"] or 0),
            "compaction_count": int(row["compaction_count"] or 0),
        }

    @classmethod
    def _rows(cls, rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
        return [value for row in rows if (value := cls._row(row)) is not None]

    def create(
        self,
        principal: str,
        profile_id: str,
        *,
        conversation_id: str = "",
        title: str = "",
        active: bool = True,
        model_id: str = "",
        reasoning_effort: str = "",
        service_tier: str = "",
    ) -> dict[str, Any]:
        owner = self._required(principal, "principal")
        profile = self._required(profile_id, "profile_id")
        identifier = str(conversation_id or "").strip()
        if not identifier:
            identifier = f"conversation-{uuid.uuid4().hex}"
        identifier = self._required(identifier, "conversation_id", 256)
        now = time.time()
        label = str(title or "").strip()[:512]
        model = str(model_id or "").strip()[:256]
        effort = str(reasoning_effort or "").strip()[:64]
        tier = str(service_tier or "").strip()[:64]
        with self._connection() as db:
            existing = db.execute(
                f"SELECT principal, profile_id FROM {TABLE} WHERE conversation_id = ?",
                (identifier,),
            ).fetchone()
            if existing is not None and (
                str(existing["principal"] or "") != owner
                or str(existing["profile_id"] or "") != profile
            ):
                raise ValueError("conversation id is already owned by another Profile")
            if active:
                db.execute(
                    f"""UPDATE {TABLE} SET active = 0
                        WHERE principal = ? AND profile_id = ?""",
                    (owner, profile),
                )
            db.execute(
                f"""INSERT INTO {TABLE} (
                        conversation_id, principal, profile_id, title,
                        created_at, updated_at, active, model_id,
                        reasoning_effort, service_tier
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(conversation_id) DO UPDATE SET
                        title = excluded.title,
                        updated_at = excluded.updated_at,
                        active = excluded.active,
                        model_id = excluded.model_id,
                        reasoning_effort = excluded.reasoning_effort,
                        service_tier = excluded.service_tier""",
                (
                    identifier, owner, profile, label, now, now, int(active),
                    model, effort, tier,
                ),
            )
            row = db.execute(
                f"SELECT * FROM {TABLE} WHERE conversation_id = ?",
                (identifier,),
            ).fetchone()
        value = self._row(row)
        if value is None:  # pragma: no cover - guarded by the upsert above
            raise RuntimeError("Agent conversation was not created")
        return value

    def list(self, principal: str, profile_id: str) -> list[dict[str, Any]]:
        owner = self._required(principal, "principal")
        profile = self._required(profile_id, "profile_id")
        with self._connection() as db:
            rows = db.execute(
                f"""SELECT * FROM {TABLE}
                    WHERE principal = ? AND profile_id = ?
                    ORDER BY active DESC, updated_at DESC""",
                (owner, profile),
            ).fetchall()
        return self._rows(rows)

    def get(
        self,
        principal: str,
        profile_id: str,
        conversation_id: str,
    ) -> dict[str, Any] | None:
        owner = self._required(principal, "principal")
        profile = self._required(profile_id, "profile_id")
        identifier = self._required(conversation_id, "conversation_id", 256)
        with self._connection() as db:
            row = db.execute(
                f"""SELECT * FROM {TABLE}
                    WHERE conversation_id = ? AND principal = ? AND profile_id = ?""",
                (identifier, owner, profile),
            ).fetchone()
        return self._row(row)

    def get_by_provider_thread(
        self,
        principal: str,
        profile_id: str,
        provider_thread_id: str,
    ) -> dict[str, Any] | None:
        owner = self._required(principal, "principal")
        profile = self._required(profile_id, "profile_id")
        thread = self._required(provider_thread_id, "provider_thread_id", 512)
        with self._connection() as db:
            row = db.execute(
                f"""SELECT * FROM {TABLE}
                    WHERE principal = ? AND profile_id = ?
                      AND provider_thread_id = ?
                    ORDER BY updated_at DESC LIMIT 1""",
                (owner, profile, thread),
            ).fetchone()
        return self._row(row)

    def active(self, principal: str, profile_id: str) -> dict[str, Any] | None:
        owner = self._required(principal, "principal")
        profile = self._required(profile_id, "profile_id")
        with self._connection() as db:
            row = db.execute(
                f"""SELECT * FROM {TABLE}
                    WHERE principal = ? AND profile_id = ? AND active = 1
                    ORDER BY updated_at DESC LIMIT 1""",
                (owner, profile),
            ).fetchone()
        return self._row(row)

    def select(
        self,
        principal: str,
        profile_id: str,
        conversation_id: str,
    ) -> dict[str, Any]:
        owner = self._required(principal, "principal")
        profile = self._required(profile_id, "profile_id")
        identifier = self._required(conversation_id, "conversation_id", 256)
        now = time.time()
        with self._connection() as db:
            row = db.execute(
                f"""SELECT * FROM {TABLE}
                    WHERE conversation_id = ? AND principal = ? AND profile_id = ?""",
                (identifier, owner, profile),
            ).fetchone()
            if row is None:
                raise ValueError("conversation not found")
            db.execute(
                f"""UPDATE {TABLE} SET active = 0
                    WHERE principal = ? AND profile_id = ?""",
                (owner, profile),
            )
            db.execute(
                f"""UPDATE {TABLE} SET active = 1, updated_at = ?
                    WHERE conversation_id = ?""",
                (now, identifier),
            )
            row = db.execute(
                f"SELECT * FROM {TABLE} WHERE conversation_id = ?",
                (identifier,),
            ).fetchone()
        value = self._row(row)
        if value is None:  # pragma: no cover - guarded by the update above
            raise RuntimeError("Agent conversation disappeared")
        return value

    def save_thread(
        self,
        principal: str,
        profile_id: str,
        conversation_id: str,
        provider_thread_id: str,
        *,
        provider_id: str = "",
        title: str = "",
        preview: str = "",
        created_at: float | None = None,
        updated_at: float | None = None,
    ) -> dict[str, Any]:
        owner = self._required(principal, "principal")
        profile = self._required(profile_id, "profile_id")
        identifier = self._required(conversation_id, "conversation_id", 256)
        thread = self._required(provider_thread_id, "provider_thread_id", 512)
        now = float(time.time() if updated_at is None else updated_at)
        created = float(now if created_at is None else created_at)
        provider = str(provider_id or "").strip()[:256]
        label = str(title or "").strip()[:512]
        summary = str(preview or "").strip()[:2000]
        with self._connection() as db:
            row = db.execute(
                f"""SELECT created_at, title, preview, provider_id
                    FROM {TABLE}
                    WHERE conversation_id = ? AND principal = ? AND profile_id = ?""",
                (identifier, owner, profile),
            ).fetchone()
            if row is None:
                raise ValueError("conversation not found")
            if not label:
                label = str(row["title"] or "")
            if not summary:
                summary = str(row["preview"] or "")
            if not provider:
                provider = str(row["provider_id"] or "")
            created = float(row["created_at"] or created)
            db.execute(
                f"""UPDATE {TABLE} SET
                        provider_id = ?, provider_thread_id = ?, title = ?,
                        preview = ?, created_at = ?, updated_at = ?, active = 1
                    WHERE conversation_id = ? AND principal = ? AND profile_id = ?""",
                (
                    provider, thread, label, summary, created, now,
                    identifier, owner, profile,
                ),
            )
            db.execute(
                f"""UPDATE {TABLE} SET active = 0
                    WHERE principal = ? AND profile_id = ?
                      AND conversation_id <> ?""",
                (owner, profile, identifier),
            )
            result = db.execute(
                f"SELECT * FROM {TABLE} WHERE conversation_id = ?",
                (identifier,),
            ).fetchone()
        value = self._row(result)
        if value is None:  # pragma: no cover - guarded by the update above
            raise RuntimeError("Agent conversation was not saved")
        return value

    def update(
        self,
        principal: str,
        profile_id: str,
        conversation_id: str,
        *,
        title: str | None = None,
        preview: str | None = None,
    ) -> dict[str, Any]:
        owner = self._required(principal, "principal")
        profile = self._required(profile_id, "profile_id")
        identifier = self._required(conversation_id, "conversation_id", 256)
        now = time.time()
        with self._connection() as db:
            row = db.execute(
                f"""SELECT * FROM {TABLE}
                    WHERE conversation_id = ? AND principal = ? AND profile_id = ?""",
                (identifier, owner, profile),
            ).fetchone()
            if row is None:
                raise ValueError("conversation not found")
            next_title = str(row["title"] or "") if title is None else str(title).strip()[:512]
            next_preview = str(row["preview"] or "") if preview is None else str(preview).strip()[:2000]
            db.execute(
                f"""UPDATE {TABLE} SET title = ?, preview = ?, updated_at = ?
                    WHERE conversation_id = ?""",
                (next_title, next_preview, now, identifier),
            )
            result = db.execute(
                f"SELECT * FROM {TABLE} WHERE conversation_id = ?",
                (identifier,),
            ).fetchone()
        value = self._row(result)
        if value is None:  # pragma: no cover
            raise RuntimeError("Agent conversation disappeared")
        return value

    def update_runtime_settings(
        self,
        principal: str,
        profile_id: str,
        conversation_id: str,
        *,
        model_id: str,
        reasoning_effort: str,
        service_tier: str,
    ) -> dict[str, Any]:
        """Persist conversation-local model choices without changing Provider defaults."""
        owner = self._required(principal, "principal")
        profile = self._required(profile_id, "profile_id")
        identifier = self._required(conversation_id, "conversation_id", 256)
        model = str(model_id or "").strip()[:256]
        effort = str(reasoning_effort or "").strip()[:64]
        tier = str(service_tier or "").strip()[:64]
        with self._connection() as db:
            cursor = db.execute(
                f"""UPDATE {TABLE} SET model_id = ?, reasoning_effort = ?,
                            service_tier = ?, updated_at = ?
                    WHERE conversation_id = ? AND principal = ? AND profile_id = ?""",
                (model, effort, tier, time.time(), identifier, owner, profile),
            )
            if cursor.rowcount != 1:
                raise ValueError("conversation not found")
            row = db.execute(
                f"SELECT * FROM {TABLE} WHERE conversation_id = ?",
                (identifier,),
            ).fetchone()
        value = self._row(row)
        if value is None:  # pragma: no cover
            raise RuntimeError("Agent conversation disappeared")
        return value

    def update_runtime_observation(
        self,
        principal: str,
        profile_id: str,
        conversation_id: str,
        *,
        actual_model: str | None = None,
        model_context_window: int | None = None,
        total_tokens: int | None = None,
        last_tokens: int | None = None,
        compaction_count: int | None = None,
    ) -> dict[str, Any]:
        """Persist small runtime metadata used to restore conversation status UI."""
        owner = self._required(principal, "principal")
        profile = self._required(profile_id, "profile_id")
        identifier = self._required(conversation_id, "conversation_id", 256)
        assignments: list[str] = []
        values: list[object] = []
        candidates = {
            "actual_model": (
                None if actual_model is None else str(actual_model).strip()[:256]
            ),
            "model_context_window": model_context_window,
            "total_tokens": total_tokens,
            "last_tokens": last_tokens,
            "compaction_count": compaction_count,
        }
        for name, value in candidates.items():
            if value is None:
                continue
            assignments.append(f"{name} = ?")
            values.append(max(0, int(value)) if name != "actual_model" else value)
        if not assignments:
            current = self.get(owner, profile, identifier)
            if current is None:
                raise ValueError("conversation not found")
            return current
        values.extend((identifier, owner, profile))
        with self._connection() as db:
            cursor = db.execute(
                f"""UPDATE {TABLE} SET {', '.join(assignments)}
                    WHERE conversation_id = ? AND principal = ? AND profile_id = ?""",
                values,
            )
            if cursor.rowcount != 1:
                raise ValueError("conversation not found")
            row = db.execute(
                f"SELECT * FROM {TABLE} WHERE conversation_id = ?",
                (identifier,),
            ).fetchone()
        value = self._row(row)
        if value is None:  # pragma: no cover
            raise RuntimeError("Agent conversation disappeared")
        return value

    def increment_compaction(
        self,
        principal: str,
        profile_id: str,
        conversation_id: str,
    ) -> dict[str, Any]:
        owner = self._required(principal, "principal")
        profile = self._required(profile_id, "profile_id")
        identifier = self._required(conversation_id, "conversation_id", 256)
        with self._connection() as db:
            cursor = db.execute(
                f"""UPDATE {TABLE}
                    SET compaction_count = compaction_count + 1
                    WHERE conversation_id = ? AND principal = ? AND profile_id = ?""",
                (identifier, owner, profile),
            )
            if cursor.rowcount != 1:
                raise ValueError("conversation not found")
            row = db.execute(
                f"SELECT * FROM {TABLE} WHERE conversation_id = ?",
                (identifier,),
            ).fetchone()
        value = self._row(row)
        if value is None:  # pragma: no cover
            raise RuntimeError("Agent conversation disappeared")
        return value

    def touch(
        self,
        principal: str,
        profile_id: str,
        conversation_id: str,
        *,
        preview: str = "",
    ) -> dict[str, Any]:
        return self.update(
            principal,
            profile_id,
            conversation_id,
            preview=preview or None,
        )

    def set_parent_sharing(
        self, principal: str, profile_id: str, enabled: bool,
    ) -> bool:
        owner = self._required(principal, "principal")
        profile = self._required(profile_id, "profile_id")
        with self._connection() as db:
            db.execute(
                f"""INSERT INTO {SHARING_TABLE}(
                        principal, profile_id, share_to_parent, updated_at
                    ) VALUES (?, ?, ?, ?)
                    ON CONFLICT(principal, profile_id) DO UPDATE SET
                        share_to_parent=excluded.share_to_parent,
                        updated_at=excluded.updated_at""",
                (owner, profile, int(bool(enabled)), time.time()),
            )
        return bool(enabled)

    def parent_sharing(self, principal: str, profile_id: str) -> bool:
        owner = self._required(principal, "principal")
        profile = self._required(profile_id, "profile_id")
        with self._connection() as db:
            row = db.execute(
                f"""SELECT share_to_parent FROM {SHARING_TABLE}
                    WHERE principal = ? AND profile_id = ?""",
                (owner, profile),
            ).fetchone()
        return bool(row and row["share_to_parent"])

    def clear(self, principal: str, profile_id: str, conversation_id: str) -> bool:
        owner = self._required(principal, "principal")
        profile = self._required(profile_id, "profile_id")
        identifier = self._required(conversation_id, "conversation_id", 256)
        with self._connection() as db:
            cursor = db.execute(
                f"""DELETE FROM {TABLE}
                    WHERE conversation_id = ? AND principal = ? AND profile_id = ?""",
                (identifier, owner, profile),
            )
        return bool(cursor.rowcount)


__all__ = [
    "AgentConversationStore",
    "ITEM_TABLE",
    "SHARING_TABLE",
    "TABLE",
]
