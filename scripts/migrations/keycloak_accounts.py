#!/usr/bin/env python3
"""Read-only export of legacy identities and their organization hierarchy.

Password material is deliberately excluded. The exporter opens SQLite in
read-only mode and never creates missing tables or normalizes the source in
place. Missing organization assignments stay missing so the reviewed cutover
plan can block or explicitly remap them instead of inventing a default org.
"""

from __future__ import annotations

import argparse
from contextlib import closing
import json
import sqlite3
from pathlib import Path
from typing import Any
from uuid import UUID, uuid5


# Stable across Manager snapshots of the same legacy directory. The namespace
# is part of the migration contract; usernames are not exported into the ID.
_IDENTITY_NAMESPACE = UUID("fc21b813-8a88-5b1f-9f34-6fc88c0b09f7")


def stable_legacy_identity_id(username: str) -> str:
    """Derive a cutover ID from the legacy account's immutable primary key.

    The legacy account table is keyed by username and has no stable identity
    column. The reviewed export freezes this mapping as ``tr_identity_id``;
    later Keycloak username or organization changes do not re-derive it. The
    case-collision report remains a hard preflight gate across Manager exports.
    """
    account = str(username or "").strip().casefold()
    if not account:
        return ""
    return str(uuid5(_IDENTITY_NAMESPACE, account))


def _open_readonly(db_path: str | Path) -> sqlite3.Connection:
    path = Path(db_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    connection = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    return connection


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone() is not None


def _table_rows(
    conn: sqlite3.Connection, table: str, columns: tuple[str, ...],
) -> list[dict[str, Any]]:
    if not _table_exists(conn, table):
        return []
    available = {str(row[1]) for row in conn.execute(f'PRAGMA table_info("{table}")')}
    selected = [column for column in columns if column in available]
    if not selected:
        return []
    # `table` and `selected` are module constants, not user-controlled SQL.
    quoted = ", ".join('"' + name.replace('"', '""') + '"' for name in selected)
    sql = f'SELECT {quoted} FROM "{table}"'
    rows = [dict(row) for row in conn.execute(sql).fetchall()]
    sort_key = "username" if "username" in selected else "id" if "id" in selected else ""
    if sort_key:
        rows.sort(key=lambda row: str(row.get(sort_key) or ""))
    return rows


def _safe_flag(value: Any) -> bool | int | None:
    if value is None:
        return False
    if type(value) is int and value in (0, 1):
        return bool(value)
    if type(value) is bool:
        return value
    return value


def export_directory(db_path: str | Path) -> dict[str, list[dict[str, Any]]]:
    """Export accounts, organizations, and levels without secret columns."""
    with closing(_open_readonly(db_path)) as conn:
        raw_accounts = _table_rows(conn, "accounts", (
            "username", "alias", "role", "is_admin", "is_developer",
            "organization_id", "organization_name", "level_id",
            "parent_username", "active",
        ))
        organizations = _table_rows(conn, "organizations", (
            "id", "name", "description",
        ))
        levels = _table_rows(conn, "levels", (
            "id", "organization_id", "name", "parent_level_id",
            "manager_username",
        ))

    organization_by_id = {
        str(row.get("id") or "").strip(): row
        for row in organizations if str(row.get("id") or "").strip()
    }
    normalized_levels: list[dict[str, Any]] = []
    for row in levels:
        organization_id = str(row.get("organization_id") or "").strip()
        normalized_levels.append({
            "id": str(row.get("id") or "").strip(),
            "organization_id": organization_id,
            "name": str(row.get("name") or ""),
            "parent_level_id": str(row.get("parent_level_id") or "").strip(),
            "manager_username": str(row.get("manager_username") or "").strip(),
            **({"synthetic": True} if row.get("synthetic") else {}),
        })

    level_ids = {str(row.get("id") or "") for row in normalized_levels}
    for organization_id, organization in sorted(organization_by_id.items()):
        root_id = f"{organization_id}__ROOT"
        if root_id not in level_ids:
            normalized_levels.append({
                "id": root_id,
                "organization_id": organization_id,
                "name": "默认层级",
                "parent_level_id": "",
                "manager_username": "",
                "synthetic": True,
            })
            level_ids.add(root_id)

    accounts: list[dict[str, Any]] = []
    for row in raw_accounts:
        username = str(row.get("username") or "").strip()
        organization_id = str(row.get("organization_id") or "").strip()
        organization = organization_by_id.get(organization_id, {})
        accounts.append({
            "username": username,
            "tr_identity_id": stable_legacy_identity_id(username),
            "alias": str(row.get("alias") or ""),
            "role": str(row.get("role") or "user").strip(),
            "is_admin": _safe_flag(row.get("is_admin")),
            "is_developer": _safe_flag(row.get("is_developer")),
            "organization_id": organization_id,
            "organization": str(
                row.get("organization_name") or organization.get("name") or ""
            ),
            "level_id": str(row.get("level_id") or "").strip(),
            "parent_username": str(row.get("parent_username") or "").strip(),
            **({"active": _safe_flag(row["active"])} if "active" in row else {}),
        })

    organizations.sort(key=lambda row: str(row.get("id") or ""))
    normalized_levels.sort(key=lambda row: (
        str(row.get("organization_id") or ""), str(row.get("id") or ""),
    ))
    return {
        "accounts": accounts,
        "organizations": organizations,
        "levels": normalized_levels,
    }


def export_accounts(db_path: str | Path) -> list[dict[str, Any]]:
    """Compatibility wrapper for callers that only need account rows."""
    return export_directory(db_path)["accounts"]


def case_collisions(accounts: list[dict]) -> dict[str, list[str]]:
    buckets: dict[str, list[str]] = {}
    for account in accounts:
        username = str(account.get("username") or "")
        if username:
            buckets.setdefault(username.lower(), []).append(username)
    return {key: values for key, values in buckets.items() if len(values) > 1}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    directory = export_directory(args.db)
    payload = {
        **directory,
        "count": len(directory["accounts"]),
        "organization_count": len(directory["organizations"]),
        "level_count": len(directory["levels"]),
        "case_collisions": case_collisions(directory["accounts"]),
    }
    if args.dry_run:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    if args.output:
        args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    print(json.dumps({
        "count": len(directory["accounts"]),
        "organization_count": len(directory["organizations"]),
        "level_count": len(directory["levels"]),
        "output": str(args.output or ""),
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
