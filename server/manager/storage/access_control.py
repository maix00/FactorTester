"""PostgreSQL repositories for Manager access-control administration."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

def _row_value(row: object, key: str, index: int = 0, default: object = None) -> object:
    if isinstance(row, Mapping):
        return row.get(key, default)
    try:
        return row[index]  # type: ignore[index]
    except (IndexError, KeyError, TypeError):
        return default


class VisitorAccessControlMixin:
    """Account directory and per-server public visitor policy."""

    def admin_account_directory(self) -> list[dict[str, Any]]:
        """Return the non-secret account directory for super-admin pages."""
        self.ensure_schema()
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT username, alias, role, is_admin, is_developer,
                       organization_id, organization_name, level_id,
                       parent_username, active, created_at, updated_at
                FROM control_users
                ORDER BY organization_id, alias, username
                """
            ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            value = dict(row) if isinstance(row, Mapping) else {
                "username": _row_value(row, "username", 0, ""),
                "alias": _row_value(row, "alias", 1, ""),
                "role": _row_value(row, "role", 2, "user"),
                "is_admin": _row_value(row, "is_admin", 3, False),
                "is_developer": _row_value(row, "is_developer", 4, False),
                "organization_id": _row_value(row, "organization_id", 5, "default"),
                "organization_name": _row_value(row, "organization_name", 6, ""),
                "level_id": _row_value(row, "level_id", 7, ""),
                "parent_username": _row_value(row, "parent_username", 8, ""),
                "active": _row_value(row, "active", 9, True),
                "created_at": _row_value(row, "created_at", 10, None),
                "updated_at": _row_value(row, "updated_at", 11, None),
            }
            for key in ("created_at", "updated_at"):
                if hasattr(value.get(key), "isoformat"):
                    value[key] = value[key].isoformat()
            result.append(value)
        return result

    @staticmethod
    def _visitor_allowlist_value(row: object) -> dict[str, Any]:
        value = dict(row) if isinstance(row, Mapping) else {
            "server_id": _row_value(row, "server_id", 0, ""),
            "username": _row_value(row, "username", 1, ""),
            "enabled": _row_value(row, "enabled", 2, False),
            "created_by": _row_value(row, "created_by", 3, ""),
            "created_at": _row_value(row, "created_at", 4, None),
            "updated_at": _row_value(row, "updated_at", 5, None),
            "alias": _row_value(row, "alias", 6, ""),
            "organization_id": _row_value(row, "organization_id", 7, ""),
            "organization_name": _row_value(row, "organization_name", 8, ""),
            "role": _row_value(row, "role", 9, ""),
            "is_admin": _row_value(row, "is_admin", 10, False),
            "account_active": _row_value(row, "account_active", 11, False),
        }
        for key in ("created_at", "updated_at"):
            if hasattr(value.get(key), "isoformat"):
                value[key] = value[key].isoformat()
        return value

    def list_public_visitor_allowlist(
        self, *, server_id: str, include_disabled: bool = True,
    ) -> list[dict[str, Any]]:
        self.ensure_schema()
        server = str(server_id or "").strip()
        if not server:
            raise ValueError("server_id is required")
        predicates = ["a.server_id=%s"]
        parameters: list[Any] = [server]
        if not include_disabled:
            predicates.append("a.enabled=TRUE")
        with self._connection() as connection:
            rows = connection.execute(
                f"""
                SELECT a.server_id, a.username, a.enabled, a.created_by,
                       a.created_at, a.updated_at,
                       u.alias, u.organization_id, u.organization_name,
                       u.role, u.is_admin, u.active AS account_active
                FROM control_public_visitor_allowlist AS a
                LEFT JOIN control_users AS u ON u.username=a.username
                WHERE {' AND '.join(predicates)}
                ORDER BY a.enabled DESC, u.alias, a.username
                """, tuple(parameters),
            ).fetchall()
        return [self._visitor_allowlist_value(row) for row in rows]

    def add_public_visitor_allowlist(
        self, *, server_id: str, username: str, created_by: str,
    ) -> dict[str, Any]:
        self.ensure_schema()
        server = str(server_id or "").strip()
        principal = str(username or "").strip()
        actor = str(created_by or "").strip()
        if not server or not principal or not actor:
            raise ValueError("server_id, username, and created_by are required")
        with self._connection() as connection:
            account = connection.execute(
                "SELECT role, is_admin, active FROM control_users WHERE username=%s",
                (principal,),
            ).fetchone()
            role = str(_row_value(account, "role", 0, "") or "") if account else ""
            if (
                account is None
                or not bool(_row_value(account, "active", 2, False))
                or bool(_row_value(account, "is_admin", 1, False))
                or role != "user"
            ):
                raise ValueError("only active ordinary users can be added to the visitor allowlist")
            row = connection.execute(
                """
                INSERT INTO control_public_visitor_allowlist(
                    server_id, username, enabled, created_by, updated_at
                ) VALUES (%s, %s, TRUE, %s, CURRENT_TIMESTAMP)
                ON CONFLICT(server_id, username) DO UPDATE SET
                    enabled=TRUE, created_by=EXCLUDED.created_by,
                    updated_at=CURRENT_TIMESTAMP
                RETURNING server_id, username, enabled, created_by,
                          created_at, updated_at,
                          (SELECT alias FROM control_users WHERE username=%s) AS alias,
                          (SELECT organization_id FROM control_users WHERE username=%s) AS organization_id,
                          (SELECT organization_name FROM control_users WHERE username=%s) AS organization_name,
                          (SELECT role FROM control_users WHERE username=%s) AS role,
                          (SELECT is_admin FROM control_users WHERE username=%s) AS is_admin,
                          (SELECT active FROM control_users WHERE username=%s) AS account_active
                """,
                (server, principal, actor, principal, principal, principal,
                 principal, principal, principal),
            ).fetchone()
        if row is None:
            raise RuntimeError("visitor allowlist update returned no row")
        return self._visitor_allowlist_value(row)

    def remove_public_visitor_allowlist(
        self, *, server_id: str, username: str,
    ) -> dict[str, Any] | None:
        self.ensure_schema()
        server = str(server_id or "").strip()
        principal = str(username or "").strip()
        if not server or not principal:
            raise ValueError("server_id and username are required")
        with self._connection() as connection:
            row = connection.execute(
                """
                UPDATE control_public_visitor_allowlist
                SET enabled=FALSE, updated_at=CURRENT_TIMESTAMP
                WHERE server_id=%s AND username=%s
                RETURNING server_id, username, enabled, created_by,
                          created_at, updated_at,
                          (SELECT alias FROM control_users WHERE username=%s) AS alias,
                          (SELECT organization_id FROM control_users WHERE username=%s) AS organization_id,
                          (SELECT organization_name FROM control_users WHERE username=%s) AS organization_name,
                          (SELECT role FROM control_users WHERE username=%s) AS role,
                          (SELECT is_admin FROM control_users WHERE username=%s) AS is_admin,
                          (SELECT active FROM control_users WHERE username=%s) AS account_active
                """,
                (server, principal, principal, principal, principal,
                 principal, principal, principal),
            ).fetchone()
        return None if row is None else self._visitor_allowlist_value(row)

    def public_visitor_login_accounts(
        self, *, server_id: str,
    ) -> list[dict[str, Any]]:
        self.ensure_schema()
        server = str(server_id or "").strip()
        if not server:
            raise ValueError("server_id is required")
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT u.username, u.alias, u.salt, u.password_hash AS hash,
                       u.role, u.is_admin, u.is_developer, u.organization_id,
                       u.organization_name, u.level_id, u.parent_username,
                       u.active, u.updated_at
                FROM control_public_visitor_allowlist AS a
                JOIN control_users AS u ON u.username=a.username
                WHERE a.server_id=%s AND a.enabled=TRUE AND u.active=TRUE
                      AND u.role='user' AND u.is_admin=FALSE
                ORDER BY u.username
                """, (server,),
            ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            value = dict(row) if isinstance(row, Mapping) else {
                "username": _row_value(row, "username", 0, ""),
                "alias": _row_value(row, "alias", 1, ""),
                "salt": _row_value(row, "salt", 2, ""),
                "hash": _row_value(row, "hash", 3, ""),
                "role": _row_value(row, "role", 4, "user"),
                "is_admin": _row_value(row, "is_admin", 5, False),
                "is_developer": _row_value(row, "is_developer", 6, False),
                "organization_id": _row_value(row, "organization_id", 7, "default"),
                "organization_name": _row_value(row, "organization_name", 8, ""),
                "level_id": _row_value(row, "level_id", 9, ""),
                "parent_username": _row_value(row, "parent_username", 10, ""),
                "active": _row_value(row, "active", 11, True),
                "updated_at": _row_value(row, "updated_at", 12, None),
            }
            if hasattr(value.get("updated_at"), "isoformat"):
                value["updated_at"] = value["updated_at"].isoformat()
            result.append(value)
        return result
