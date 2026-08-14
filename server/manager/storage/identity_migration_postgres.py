"""PostgreSQL account-identity planning and transactional migration."""

from __future__ import annotations

from server.manager.storage.identity_migration_common import (
    POSTGRES_USER_REFERENCES,
    cursor_rows_as_dicts,
)


def postgres_identity_plan(connection: object, *, old_username: str) -> dict[str, object]:
    """Read a bounded central-account plan without changing PostgreSQL."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT username, alias, organization_id, role, active
            FROM control_users ORDER BY username
            """
        )
        accounts = cursor_rows_as_dicts(cursor)
        target = next(
            (row for row in accounts if row["username"] == old_username),
            None,
        )
        if target is None:
            raise ValueError(f"PostgreSQL account not found: {old_username}")
        references: dict[str, int] = {}
        cleanup_references: dict[str, int] = {}
        for table, column in POSTGRES_USER_REFERENCES:
            cursor.execute(
                "SELECT to_regclass(%s)",
                (table,),
            )
            if cursor.fetchone()[0] is None:
                continue
            cursor.execute(
                f'SELECT COUNT(*) FROM "{table}" WHERE "{column}"=%s',
                (old_username,),
            )
            references[f"{table}.{column}"] = int(cursor.fetchone()[0])
            cursor.execute(
                f'SELECT COUNT(*) FROM "{table}" WHERE '
                f'COALESCE("{column}", \'\')<>%s '
                f'AND "{column}"<>%s',
                ("", old_username),
            )
            cleanup_references[f"{table}.{column}"] = int(cursor.fetchone()[0])
    return {
        "old_username": old_username,
        "account_count": len(accounts),
        "other_account_count": max(0, len(accounts) - 1),
        "target_account": {
            "username": target["username"],
            "alias": target.get("alias") or "",
            "organization_id": target.get("organization_id") or "",
            "role": target.get("role") or "user",
            "active": bool(target.get("active", True)),
        },
        "referenced_rows": references,
        "cleanup_reference_rows": cleanup_references,
    }


def apply_postgres_identity_migration(
    connection: object,
    *,
    old_username: str,
    new_username: str,
    organization_id: str,
    organization_name: str,
    alias: str,
) -> dict[str, int]:
    """Migrate auth/device rows and remove all other central accounts."""
    counts = {"renamed_references": 0, "deleted_references": 0}
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT 1 FROM control_users WHERE username=%s",
            (old_username,),
        )
        if cursor.fetchone() is None:
            raise ValueError(f"PostgreSQL account not found: {old_username}")
        cursor.execute(
            "SELECT 1 FROM control_users WHERE username=%s",
            (new_username,),
        )
        if cursor.fetchone() is not None:
            raise ValueError(f"PostgreSQL username already exists: {new_username}")
        cursor.execute(
            "SELECT pg_advisory_xact_lock(hashtext(%s))",
            ("factortester:identity-reset",),
        )
        cursor.execute(
            """
            INSERT INTO control_organizations(id, name, description)
            VALUES (%s, %s, '')
            ON CONFLICT(id) DO UPDATE SET name=EXCLUDED.name,
                updated_at=CURRENT_TIMESTAMP
            """,
            (organization_id, organization_name),
        )
        cursor.execute(
            """
            INSERT INTO control_levels(
                id, organization_id, name, parent_level_id, manager_username
            ) VALUES (%s, %s, '默认层级', '', '')
            ON CONFLICT(id) DO NOTHING
            """,
            (f"{organization_id}__ROOT", organization_id),
        )
        cursor.execute(
            """
            UPDATE control_users
            SET username=%s, alias=%s, organization_id=%s,
                organization_name=%s, level_id=%s,
                updated_at=CURRENT_TIMESTAMP
            WHERE username=%s
            """,
            (
                new_username, alias, organization_id, organization_name,
                f"{organization_id}__ROOT", old_username,
            ),
        )
        for table, column in POSTGRES_USER_REFERENCES:
            cursor.execute("SELECT to_regclass(%s)", (table,))
            if cursor.fetchone()[0] is None:
                continue
            renamed = cursor.execute(
                f'UPDATE "{table}" SET "{column}"=%s '
                f'WHERE "{column}"=%s',
                (new_username, old_username),
            ).rowcount
            deleted = cursor.execute(
                f'DELETE FROM "{table}" WHERE "{column}"<>%s '
                f'AND "{column}"<>%s',
                (new_username, ""),
            ).rowcount
            counts["renamed_references"] += max(0, int(renamed))
            counts["deleted_references"] += max(0, int(deleted))
        cursor.execute(
            "DELETE FROM control_users WHERE username<>%s",
            (new_username,),
        )
        counts["deleted_accounts"] = max(0, int(cursor.rowcount))
        residuals: list[str] = []
        for table, column in POSTGRES_USER_REFERENCES:
            cursor.execute("SELECT to_regclass(%s)", (table,))
            if cursor.fetchone()[0] is None:
                continue
            cursor.execute(
                f'SELECT COUNT(*) FROM "{table}" WHERE '
                f'COALESCE("{column}", \'\')<>%s '
                f'AND "{column}"<>%s',
                ("", new_username),
            )
            remaining = int(cursor.fetchone()[0])
            if remaining:
                residuals.append(f"{table}.{column}={remaining}")
        if residuals:
            raise RuntimeError(
                "PostgreSQL identity cleanup left user references: "
                + ", ".join(residuals)
            )
    connection.commit()
    return counts
