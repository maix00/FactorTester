"""Manager-local conversation catalog for research Profiles.

Conversation identity belongs to an authenticated principal and Profile.  A
provider-specific thread id is only a resumable runtime binding, so changing
or stopping an Agent does not remove the conversation.  The catalog contains
a bounded text projection rather than the Provider's complete thread state.
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

def sanitize_conversation_text(value: object, *, limit: int = 12_000) -> str:
    """Prepare text for the bounded Manager projection.

    The name is kept for API compatibility. Credential and path redaction is
    intentionally not implemented yet; a future versioned policy can be
    inserted at this boundary without changing the conversation schema.
    """
    # Keep the Provider's Markdown structure intact.  In particular, ChatKit
    # needs newlines to render fenced code blocks and structured answers.
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    # Placeholder: add an explicit, versioned redaction policy here later.
    return text[:limit]


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
                active INTEGER NOT NULL DEFAULT 0
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
        db.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {ITEM_TABLE} (
                conversation_id TEXT NOT NULL,
                item_id TEXT NOT NULL,
                role TEXT NOT NULL,
                item_type TEXT NOT NULL DEFAULT 'message',
                text TEXT NOT NULL,
                created_at REAL NOT NULL,
                PRIMARY KEY (conversation_id, item_id),
                FOREIGN KEY (conversation_id) REFERENCES {TABLE}(conversation_id)
                    ON DELETE CASCADE
            )
            """
        )
        db.execute(
            f"""CREATE INDEX IF NOT EXISTS {ITEM_TABLE}_conversation
                ON {ITEM_TABLE}(conversation_id, created_at, item_id)"""
        )
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
    ) -> dict[str, Any]:
        owner = self._required(principal, "principal")
        profile = self._required(profile_id, "profile_id")
        identifier = str(conversation_id or "").strip()
        if not identifier:
            identifier = f"conversation-{uuid.uuid4().hex}"
        identifier = self._required(identifier, "conversation_id", 256)
        now = time.time()
        label = str(title or "").strip()[:512]
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
                        created_at, updated_at, active
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(conversation_id) DO UPDATE SET
                        title = excluded.title,
                        updated_at = excluded.updated_at,
                        active = excluded.active""",
                (identifier, owner, profile, label, now, now, int(active)),
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

    def append_item(
        self,
        principal: str,
        profile_id: str,
        conversation_id: str,
        *,
        role: str,
        text: object,
        item_id: str = "",
        item_type: str = "message",
        created_at: float | None = None,
    ) -> dict[str, Any]:
        """Persist one normalized user/assistant message for offline viewing."""
        owner = self._required(principal, "principal")
        profile = self._required(profile_id, "profile_id")
        identifier = self._required(conversation_id, "conversation_id", 256)
        normalized_role = str(role or "").strip().lower()
        if normalized_role not in {"user", "assistant"}:
            raise ValueError("conversation item role is invalid")
        normalized_text = sanitize_conversation_text(text)
        if not normalized_text:
            raise ValueError("conversation item text is required")
        item_identifier = str(item_id or "").strip() or f"item-{uuid.uuid4().hex}"
        item_identifier = self._required(item_identifier, "item_id", 256)
        kind = str(item_type or "message").strip()[:64] or "message"
        timestamp = float(time.time() if created_at is None else created_at)
        with self._connection() as db:
            owned = db.execute(
                f"""SELECT 1 FROM {TABLE}
                    WHERE conversation_id = ? AND principal = ? AND profile_id = ?""",
                (identifier, owner, profile),
            ).fetchone()
            if owned is None:
                raise ValueError("conversation not found")
            db.execute(
                f"""INSERT INTO {ITEM_TABLE}(
                        conversation_id, item_id, role, item_type, text, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(conversation_id, item_id) DO UPDATE SET
                        role=excluded.role, item_type=excluded.item_type,
                        text=excluded.text, created_at=excluded.created_at""",
                (identifier, item_identifier, normalized_role, kind,
                 normalized_text, timestamp),
            )
            # Keep local transcript growth bounded.  The metadata catalog is
            # still the source of truth for the full provider thread.
            db.execute(
                f"""DELETE FROM {ITEM_TABLE}
                    WHERE conversation_id = ? AND rowid NOT IN (
                        SELECT rowid FROM {ITEM_TABLE}
                        WHERE conversation_id = ?
                        ORDER BY created_at DESC, item_id DESC LIMIT 500
                    )""",
                (identifier, identifier),
            )
            row = db.execute(
                f"""SELECT item_id, role, item_type, text, created_at
                    FROM {ITEM_TABLE}
                    WHERE conversation_id = ? AND item_id = ?""",
                (identifier, item_identifier),
            ).fetchone()
        if row is None:  # pragma: no cover - guarded by the upsert above
            raise RuntimeError("conversation item was not saved")
        return {
            "id": str(row["item_id"] or ""),
            "role": str(row["role"] or ""),
            "item_type": str(row["item_type"] or "message"),
            "text": str(row["text"] or ""),
            "created_at": float(row["created_at"] or 0),
        }

    def items(
        self,
        principal: str,
        profile_id: str,
        conversation_id: str,
    ) -> list[dict[str, Any]]:
        owner = self._required(principal, "principal")
        profile = self._required(profile_id, "profile_id")
        identifier = self._required(conversation_id, "conversation_id", 256)
        with self._connection() as db:
            rows = db.execute(
                f"""SELECT i.item_id, i.role, i.item_type, i.text, i.created_at
                    FROM {ITEM_TABLE} i
                    JOIN {TABLE} c ON c.conversation_id = i.conversation_id
                    WHERE i.conversation_id = ? AND c.principal = ? AND c.profile_id = ?
                    ORDER BY i.created_at, i.item_id""",
                (identifier, owner, profile),
            ).fetchall()
        return [
            {
                "id": str(row["item_id"] or ""),
                "role": str(row["role"] or ""),
                "item_type": str(row["item_type"] or "message"),
                "text": str(row["text"] or ""),
                "created_at": float(row["created_at"] or 0),
            }
            for row in rows
        ]

    def replace_items(
        self,
        principal: str,
        profile_id: str,
        conversation_id: str,
        items: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Replace one transcript projection with Provider-authoritative items."""
        owner = self._required(principal, "principal")
        profile = self._required(profile_id, "profile_id")
        identifier = self._required(conversation_id, "conversation_id", 256)
        normalized: list[tuple[str, str, str, str, float]] = []
        for raw in items[-500:]:
            role = str(raw.get("role") or "").strip().lower()
            if role not in {"user", "assistant"}:
                raise ValueError("conversation item role is invalid")
            text = sanitize_conversation_text(raw.get("text"))
            if not text:
                raise ValueError("conversation item text is required")
            item_id = self._required(raw.get("item_id"), "item_id", 256)
            item_type = str(raw.get("item_type") or "message").strip()[:64]
            created_at = float(raw.get("created_at") or time.time())
            normalized.append((item_id, role, item_type, text, created_at))
        with self._connection() as db:
            owned = db.execute(
                f"""SELECT 1 FROM {TABLE}
                    WHERE conversation_id = ? AND principal = ? AND profile_id = ?""",
                (identifier, owner, profile),
            ).fetchone()
            if owned is None:
                raise ValueError("conversation not found")
            db.execute(
                f"DELETE FROM {ITEM_TABLE} WHERE conversation_id = ?",
                (identifier,),
            )
            db.executemany(
                f"""INSERT INTO {ITEM_TABLE}(
                        conversation_id, item_id, role, item_type, text, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)""",
                [
                    (identifier, item_id, role, item_type, text, created_at)
                    for item_id, role, item_type, text, created_at in normalized
                ],
            )
        return self.items(owner, profile, identifier)

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
    "sanitize_conversation_text",
]
