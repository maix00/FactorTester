"""SQLite account-identity planning and transactional migration."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from server.manager.storage.identity_migration_common import (
    SQLITE_USER_REFERENCES,
    SYSTEM_OWNER_VALUES,
    sqlite_integrity_check,
)
from tools.data.sqlite.db import connect_sqlite


def _sqlite_tables(connection: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }


def _sqlite_columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {
        str(row[1])
        for row in connection.execute(f'PRAGMA table_info("{table}")').fetchall()
    }


def sqlite_identity_plan(
    path: str | Path,
    *,
    old_username: str,
    new_username: str,
    organization_id: str,
    alias: str,
) -> dict[str, object]:
    """Return row counts and identity checks without writing the database."""
    database = Path(path).expanduser().resolve()
    with connect_sqlite(database) as connection:
        accounts = [dict(row) for row in connection.execute(
            "SELECT username, alias, organization_id FROM accounts ORDER BY username"
        ).fetchall()]
        old = next(
            (item for item in accounts if item["username"] == old_username),
            None,
        )
        if old is None:
            raise ValueError(f"SQLite account not found: {old_username}")
        if any(item["username"] == new_username for item in accounts):
            raise ValueError(f"SQLite username already exists: {new_username}")
        tables = _sqlite_tables(connection)
        references: dict[str, int] = {}
        cleanup_references: dict[str, int] = {}
        other_usernames = {
            str(item["username"])
            for item in accounts
            if str(item["username"]) != old_username
        }
        for table, columns in SQLITE_USER_REFERENCES:
            if table not in tables:
                continue
            available = _sqlite_columns(connection, table)
            for column in columns:
                if column not in available:
                    continue
                count = connection.execute(
                    f'SELECT COUNT(*) FROM "{table}" WHERE "{column}"=?',
                    (old_username,),
                ).fetchone()[0]
                references[f"{table}.{column}"] = int(count)
                cleanup_count = connection.execute(
                    f'SELECT COUNT(*) FROM "{table}" WHERE '
                    f'COALESCE("{column}", \'\')<>? '
                    f'AND "{column}"<>? '
                    f'AND "{column}" NOT IN ({",".join("?" for _ in SYSTEM_OWNER_VALUES)})',
                    ("", old_username, *sorted(SYSTEM_OWNER_VALUES)),
                ).fetchone()[0]
                cleanup_references[f"{table}.{column}"] = int(cleanup_count)
        return {
            "database": str(database),
            "old_username": old_username,
            "new_username": new_username,
            "organization_id": organization_id,
            "alias": alias,
            "account_count": len(accounts),
            "other_account_count": max(0, len(accounts) - 1),
            "target_account": {
                "username": old["username"],
                "alias": old["alias"] or "",
                "organization_id": old["organization_id"] or "",
            },
            "referenced_rows": references,
            "cleanup_reference_rows": cleanup_references,
            "other_usernames": sorted(other_usernames),
        }


def apply_sqlite_identity_migration(
    path: str | Path,
    *,
    old_username: str,
    new_username: str,
    organization_id: str,
    organization_name: str,
    alias: str,
) -> dict[str, int]:
    """Rename the target and remove all other account-owned SQLite rows."""
    database = Path(path).expanduser().resolve()
    counts = {"renamed_references": 0, "deleted_references": 0}
    with connect_sqlite(database) as connection:
        connection.execute("BEGIN IMMEDIATE")
        accounts = [dict(row) for row in connection.execute(
            "SELECT username FROM accounts ORDER BY username"
        ).fetchall()]
        if not any(row["username"] == old_username for row in accounts):
            raise ValueError(f"SQLite account not found: {old_username}")
        if any(row["username"] == new_username for row in accounts):
            raise ValueError(f"SQLite username already exists: {new_username}")
        tables = _sqlite_tables(connection)
        connection.execute(
            """
            INSERT INTO organizations (id, name, description, updated_at)
            VALUES (?, ?, ?, strftime('%s','now'))
            ON CONFLICT(id) DO UPDATE SET name=excluded.name,
                updated_at=excluded.updated_at
            """,
            (organization_id, organization_name, ""),
        )
        connection.execute(
            """
            INSERT INTO levels (
                id, organization_id, name, parent_level_id,
                manager_username, updated_at
            ) VALUES (?, ?, ?, '', '', strftime('%s','now'))
            ON CONFLICT(id) DO NOTHING
            """,
            (f"{organization_id}__ROOT", organization_id, "默认层级"),
        )
        connection.execute(
            """
            UPDATE accounts
            SET username=?, alias=?, organization_id=?, organization_name=?,
                level_id=?, parent_username=CASE WHEN parent_username=?
                    THEN ? ELSE parent_username END,
                updated_at=strftime('%s','now')
            WHERE username=?
            """,
            (
                new_username, alias, organization_id, organization_name,
                f"{organization_id}__ROOT", old_username, new_username,
                old_username,
            ),
        )
        for table, columns in SQLITE_USER_REFERENCES:
            if table not in tables:
                continue
            available = _sqlite_columns(connection, table)
            if "owner_username" in columns and "owner_alias" in available:
                connection.execute(
                    f'UPDATE "{table}" SET owner_alias=? '
                    'WHERE owner_username=?',
                    (alias, old_username),
                )
            for column in columns:
                if column not in available:
                    continue
                renamed = connection.execute(
                    f'UPDATE "{table}" SET "{column}"=? '
                    f'WHERE "{column}"=?',
                    (new_username, old_username),
                ).rowcount
                placeholders = ",".join("?" for _ in SYSTEM_OWNER_VALUES)
                deleted = connection.execute(
                    f'DELETE FROM "{table}" WHERE '
                    f'COALESCE("{column}", \'\')<>? '
                    f'AND "{column}"<>? '
                    f'AND "{column}" NOT IN ({placeholders})',
                    ("", new_username, *sorted(SYSTEM_OWNER_VALUES)),
                ).rowcount
                counts["renamed_references"] += max(0, int(renamed))
                counts["deleted_references"] += max(0, int(deleted))
        if "pending_account_registrations" in tables:
            connection.execute(
                "DELETE FROM pending_account_registrations WHERE username<>?",
                (new_username,),
            )
        deleted_accounts = connection.execute(
            "DELETE FROM accounts WHERE username<>?",
            (new_username,),
        ).rowcount
        counts["deleted_accounts"] = max(0, int(deleted_accounts))
        residuals: list[str] = []
        for table, columns in SQLITE_USER_REFERENCES:
            if table not in tables:
                continue
            available = _sqlite_columns(connection, table)
            for column in columns:
                if column not in available:
                    continue
                placeholders = ",".join("?" for _ in SYSTEM_OWNER_VALUES)
                remaining = connection.execute(
                    f'SELECT COUNT(*) FROM "{table}" WHERE '
                    f'COALESCE("{column}", \'\')<>? '
                    f'AND "{column}"<>? '
                    f'AND "{column}" NOT IN ({placeholders})',
                    ("", new_username, *sorted(SYSTEM_OWNER_VALUES)),
                ).fetchone()[0]
                if int(remaining) > 0:
                    residuals.append(f"{table}.{column}={remaining}")
        if residuals:
            raise RuntimeError(
                "SQLite identity cleanup left user references: "
                + ", ".join(residuals)
            )
        connection.commit()
    sqlite_integrity_check(database)
    return counts
