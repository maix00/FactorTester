"""Read-only access to the Manager's existing local SQLite account table."""

from __future__ import annotations

import json
import secrets
import sqlite3
import time
from typing import Mapping

from server.manager.domain.organization_scope import canonical_username
from server.manager.storage.control_db import ControlDatabaseUnavailable
from tools.data.sqlite.account_manager.user import (
    ensure_user_schema,
    load_accounts as _load_accounts,
)
from tools.data.sqlite.account_manager.user_level import (
    ensure_user_level_schema,
    load_levels as _load_levels,
    load_organizations as _load_organizations,
)
from tools.data.sqlite.db import connect_sqlite


PENDING_REGISTRATIONS_TABLE = "pending_account_registrations"


class LocalAccountStore:
    """Expose local ``accounts`` rows through the authentication store seam.

    The existing SQLite account-management schema is the only local account
    fallback.  Its one write-side extension is a small outbox for accounts
    created while PostgreSQL is unavailable; it is not a device or auth-cache
    table.
    """

    def load_accounts(self) -> list[dict[str, object]]:
        try:
            return [dict(item) for item in _load_accounts()]
        except (OSError, sqlite3.Error) as exc:
            raise ControlDatabaseUnavailable(
                "local account database is unavailable"
            ) from exc

    def organizations(self) -> list[dict[str, object]]:
        try:
            return [dict(item) for item in _load_organizations()]
        except (OSError, sqlite3.Error) as exc:
            raise ControlDatabaseUnavailable(
                "local organization database is unavailable"
            ) from exc

    def levels(self) -> list[dict[str, object]]:
        try:
            return [dict(item) for item in _load_levels()]
        except (OSError, sqlite3.Error) as exc:
            raise ControlDatabaseUnavailable(
                "local hierarchy database is unavailable"
            ) from exc

    @staticmethod
    def unique_registration_username(
        organization_id: str,
        alias: str,
        accounts: list[Mapping[str, object]],
    ) -> str:
        """Allocate an opaque numeric suffix safe for multi-node offline use."""
        existing = {
            str(item.get("username") or "")
            for item in accounts
            if isinstance(item, Mapping)
        }
        for _attempt in range(32):
            suffix = secrets.randbelow(900_000_000_000) + 100_000_000_000
            candidate = canonical_username(organization_id, alias, suffix)
            if candidate not in existing:
                return candidate
        raise ControlDatabaseUnavailable(
            "could not allocate a unique offline account username"
        )

    def _connect(self) -> sqlite3.Connection:
        connection = connect_sqlite(_cache_db_path(), timeout=5.0)
        ensure_user_schema(connection)
        ensure_user_level_schema(connection)
        connection.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {PENDING_REGISTRATIONS_TABLE} (
                username TEXT PRIMARY KEY,
                payload_json TEXT NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                last_error TEXT NOT NULL DEFAULT ''
            )
            """
        )
        return connection

    def add_pending_account(self, account: Mapping[str, object]) -> dict[str, object]:
        """Atomically add a local account and an eventual-sync outbox row."""
        value = dict(account)
        username = str(value.get("username") or "").strip()
        if not username:
            raise ValueError("account username is required")
        now = time.time()
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                existing = connection.execute(
                    "SELECT 1 FROM accounts WHERE username=?",
                    (username,),
                ).fetchone()
                if existing is not None:
                    raise ValueError("username is already registered locally")
                connection.execute(
                    """
                    INSERT INTO accounts (
                        username, alias, salt, hash, role, is_admin,
                        is_developer, organization_id, organization_name,
                        level_id, parent_username, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        username,
                        str(value.get("alias") or ""),
                        str(value.get("salt") or ""),
                        str(value.get("hash") or ""),
                        str(value.get("role") or "user"),
                        1 if bool(value.get("is_admin")) else 0,
                        1 if bool(value.get("is_developer")) else 0,
                        str(value.get("organization_id") or "default"),
                        str(value.get("organization_name") or ""),
                        str(value.get("level_id") or ""),
                        str(value.get("parent_username") or ""),
                        now,
                    ),
                )
                connection.execute(
                    f"""
                    INSERT INTO {PENDING_REGISTRATIONS_TABLE} (
                        username, payload_json, created_at, updated_at, last_error
                    ) VALUES (?, ?, ?, ?, '')
                    """,
                    (
                        username,
                        json.dumps(value, ensure_ascii=False, sort_keys=True),
                        now,
                        now,
                    ),
                )
        except ValueError:
            raise
        except (OSError, sqlite3.Error) as exc:
            raise ControlDatabaseUnavailable(
                "local account database is unavailable"
            ) from exc
        return value

    def pending_accounts(self) -> list[dict[str, object]]:
        try:
            with connect_sqlite(_cache_db_path(), timeout=5.0) as connection:
                exists = connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                    (PENDING_REGISTRATIONS_TABLE,),
                ).fetchone()
                if exists is None:
                    return []
                rows = connection.execute(
                    f"SELECT username, payload_json FROM {PENDING_REGISTRATIONS_TABLE} "
                    "ORDER BY created_at, username"
                ).fetchall()
        except (OSError, sqlite3.Error) as exc:
            raise ControlDatabaseUnavailable(
                "local account outbox is unavailable"
            ) from exc
        result: list[dict[str, object]] = []
        for row in rows:
            try:
                payload = json.loads(str(row["payload_json"] or "{}"))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if isinstance(payload, dict):
                result.append(payload)
        return result

    def remove_pending(self, username: str) -> None:
        try:
            with self._connect() as connection:
                connection.execute(
                    f"DELETE FROM {PENDING_REGISTRATIONS_TABLE} WHERE username=?",
                    (str(username or "").strip(),),
                )
        except (OSError, sqlite3.Error) as exc:
            raise ControlDatabaseUnavailable(
                "local account outbox is unavailable"
            ) from exc

    def remove_account(self, username: str) -> None:
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    "DELETE FROM accounts WHERE username=?",
                    (str(username or "").strip(),),
                )
                connection.execute(
                    f"DELETE FROM {PENDING_REGISTRATIONS_TABLE} WHERE username=?",
                    (str(username or "").strip(),),
                )
        except (OSError, sqlite3.Error) as exc:
            raise ControlDatabaseUnavailable(
                "local account database is unavailable"
            ) from exc

    def sync_pending(self, control_store: object) -> dict[str, int]:
        """Lazily push pending registrations after PostgreSQL recovers."""
        synced = 0
        rejected = 0
        for account in self.pending_accounts():
            username = str(account.get("username") or "").strip()
            if not username:
                continue
            try:
                control_store.create_account(account)
            except ControlDatabaseUnavailable:
                raise
            except ControlDatabaseError:
                raise
            except (TypeError, ValueError):
                # A central conflict means this local account cannot become
                # authoritative.  Remove only this pending local registration;
                # unrelated local accounts remain intact.
                self.remove_account(username)
                rejected += 1
            else:
                self.remove_pending(username)
                synced += 1
        return {"synced": synced, "rejected": rejected}


def _cache_db_path():
    import settings as Settings

    return Settings.CACHE_DB_PATH
