"""SQLite storage for factor-library parameter configs."""

from __future__ import annotations

import json
import sqlite3
import time
from typing import Any

import settings as Settings
from tools.data.sqlite.db import connect_sqlite

DEFAULT_SCOPE_KEY = "default"


def normalize_product_group(product_group: str | None) -> str:
    if product_group is None:
        return DEFAULT_SCOPE_KEY
    value = str(product_group).strip()
    return value or DEFAULT_SCOPE_KEY


def ensure_factor_param_config_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS account_factor_param_scopes (
            username TEXT NOT NULL,
            scope_key TEXT NOT NULL,
            updated_at REAL NOT NULL,
            PRIMARY KEY (username, scope_key)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS account_factor_param_configs (
            username TEXT NOT NULL,
            scope_key TEXT NOT NULL,
            ff_alias TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            updated_at REAL NOT NULL,
            PRIMARY KEY (username, scope_key, ff_alias)
        )
        """
    )


def ensure_scope_exists(username: str, scope_key: str = DEFAULT_SCOPE_KEY) -> str:
    scope_key = normalize_product_group(scope_key)
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        ensure_factor_param_config_schema(conn)
        conn.execute(
            """
            INSERT INTO account_factor_param_scopes (username, scope_key, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(username, scope_key)
            DO UPDATE SET updated_at = excluded.updated_at
            """,
            (username, scope_key, time.time()),
        )
    return scope_key


def load_factor_param_config(username: str, ff_alias: str, scope_key: str = DEFAULT_SCOPE_KEY) -> dict[str, Any] | None:
    scope_key = normalize_product_group(scope_key)
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        ensure_factor_param_config_schema(conn)
        row = conn.execute(
            """
            SELECT payload_json
            FROM account_factor_param_configs
            WHERE username = ? AND scope_key = ? AND ff_alias = ?
            """,
            (username, scope_key, ff_alias),
        ).fetchone()
    if row is None:
        return None
    try:
        payload = json.loads(row["payload_json"])
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def save_factor_param_config(
    username: str,
    ff_alias: str,
    params_list: list,
    scope_key: str = DEFAULT_SCOPE_KEY,
    *,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    scope_key = ensure_scope_exists(username, scope_key)
    config = {
        "id": username,
        "scope": "user_product_group",
        "scope_key": scope_key,
        "product_group": scope_key,
        "scope_user_id": username,
        "name": username,
        "params_list": params_list,
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
    }
    if metadata:
        config["metadata"] = metadata
    save_factor_param_config_payload(username, ff_alias, config, scope_key)
    return config


def save_factor_param_config_payload(
    username: str,
    ff_alias: str,
    config: dict[str, Any],
    scope_key: str = DEFAULT_SCOPE_KEY,
) -> None:
    scope_key = ensure_scope_exists(username, scope_key)
    now = time.time()
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        ensure_factor_param_config_schema(conn)
        conn.execute(
            """
            INSERT INTO account_factor_param_configs (
                username, scope_key, ff_alias, payload_json, updated_at
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(username, scope_key, ff_alias)
            DO UPDATE SET payload_json = excluded.payload_json, updated_at = excluded.updated_at
            """,
            (
                username,
                scope_key,
                ff_alias,
                json.dumps(config, ensure_ascii=False, separators=(",", ":")),
                now,
            ),
        )


def delete_factor_param_config(username: str, ff_alias: str, scope_key: str = DEFAULT_SCOPE_KEY) -> bool:
    scope_key = normalize_product_group(scope_key)
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        ensure_factor_param_config_schema(conn)
        cursor = conn.execute(
            """
            DELETE FROM account_factor_param_configs
            WHERE username = ? AND scope_key = ? AND ff_alias = ?
            """,
            (username, scope_key, ff_alias),
        )
    return bool(cursor.rowcount)


def delete_factor_family_configs(
    ff_alias: str, *, username: str | None = None,
) -> list[dict[str, Any]]:
    """Atomically delete every registered factor row for one family.

    A custom family is restricted to its owner.  A public family passes no
    username because registrations may belong to any account.
    """
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        ensure_factor_param_config_schema(conn)
        where = "ff_alias = ?"
        params: tuple[Any, ...] = (ff_alias,)
        if username is not None:
            where += " AND username = ?"
            params = (ff_alias, username)
        rows = conn.execute(
            f"SELECT username, scope_key, payload_json "
            f"FROM account_factor_param_configs WHERE {where}",
            params,
        ).fetchall()
        conn.execute(
            f"DELETE FROM account_factor_param_configs WHERE {where}", params,
        )
    deleted = []
    for row in rows:
        try:
            payload = json.loads(row["payload_json"])
        except Exception:
            payload = {}
        params_list = payload.get("params_list") if isinstance(payload, dict) else []
        deleted.append({
            "username": str(row["username"]),
            "scope_key": str(row["scope_key"]),
            "factor_count": len(params_list) if isinstance(params_list, list) else 0,
        })
    return deleted


def list_factor_family_dependency_configs(
    ff_alias: str, *, owner_ref: str,
) -> list[dict[str, Any]]:
    """List outer registrations that freeze factors from one family."""
    target_owner = str(owner_ref or '').removeprefix('principal:')
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        ensure_factor_param_config_schema(conn)
        rows = conn.execute(
            "SELECT username, scope_key, ff_alias, payload_json "
            "FROM account_factor_param_configs"
        ).fetchall()
    result = []
    for row in rows:
        try:
            payload = json.loads(row['payload_json'])
        except (TypeError, ValueError):
            continue
        metadata = payload.get('metadata') if isinstance(payload, dict) else {}
        dependencies = metadata.get('factor_dependencies') if isinstance(metadata, dict) else []
        matches = []
        for dependency in dependencies if isinstance(dependencies, list) else []:
            identity = dependency.get('identity') if isinstance(dependency, dict) else {}
            dependency_owner = str(
                dependency.get('owner_ref') if isinstance(dependency, dict) else ''
            ).removeprefix('principal:')
            if (
                isinstance(identity, dict)
                and str(identity.get('family_alias') or '') == ff_alias
                and dependency_owner == target_owner
            ):
                matches.append(str(dependency.get('ref') or ''))
        if matches:
            result.append({
                'username': str(row['username']),
                'scope_key': str(row['scope_key']),
                'outer_family_alias': str(row['ff_alias']),
                'factor_refs': sorted(set(matches)),
            })
    return result


def list_factor_param_config_aliases(username: str, scope_key: str = DEFAULT_SCOPE_KEY) -> list[str]:
    scope_key = normalize_product_group(scope_key)
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        ensure_factor_param_config_schema(conn)
        rows = conn.execute(
            """
            SELECT ff_alias
            FROM account_factor_param_configs
            WHERE username = ? AND scope_key = ?
            ORDER BY ff_alias
            """,
            (username, scope_key),
        ).fetchall()
    return [str(row["ff_alias"]) for row in rows]


def list_factor_param_config_scopes(username: str) -> list[str]:
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        ensure_factor_param_config_schema(conn)
        rows = conn.execute(
            """
            SELECT scope_key
            FROM account_factor_param_scopes
            WHERE username = ?
            ORDER BY CASE WHEN scope_key = ? THEN 0 ELSE 1 END, scope_key
            """,
            (username, DEFAULT_SCOPE_KEY),
        ).fetchall()
    scopes = [str(row["scope_key"]) for row in rows]
    return scopes if scopes else [DEFAULT_SCOPE_KEY]


def list_all_factor_param_aliases_across_scopes(username: str) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for scope_key in list_factor_param_config_scopes(username):
        aliases = list_factor_param_config_aliases(username, scope_key)
        if aliases:
            result[scope_key] = aliases
    if not result:
        result[DEFAULT_SCOPE_KEY] = []
    return result


def rename_scope(username: str, old_scope_key: str, new_scope_key: str) -> bool:
    old_scope_key = normalize_product_group(old_scope_key)
    new_scope_key = normalize_product_group(new_scope_key)
    if old_scope_key == new_scope_key:
        return True
    now = time.time()
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        ensure_factor_param_config_schema(conn)
        exists = conn.execute(
            """
            SELECT 1
            FROM account_factor_param_scopes
            WHERE username = ? AND scope_key = ?
            """,
            (username, old_scope_key),
        ).fetchone()
        target = conn.execute(
            """
            SELECT 1
            FROM account_factor_param_scopes
            WHERE username = ? AND scope_key = ?
            """,
            (username, new_scope_key),
        ).fetchone()
        if exists is None or target is not None:
            return False
        conn.execute(
            """
            UPDATE account_factor_param_scopes
            SET scope_key = ?, updated_at = ?
            WHERE username = ? AND scope_key = ?
            """,
            (new_scope_key, now, username, old_scope_key),
        )
        rows = conn.execute(
            """
            SELECT ff_alias, payload_json
            FROM account_factor_param_configs
            WHERE username = ? AND scope_key = ?
            """,
            (username, old_scope_key),
        ).fetchall()
        conn.execute(
            """
            DELETE FROM account_factor_param_configs
            WHERE username = ? AND scope_key = ?
            """,
            (username, old_scope_key),
        )
        for row in rows:
            try:
                payload = json.loads(row["payload_json"])
            except Exception:
                payload = {}
            if isinstance(payload, dict):
                payload["scope_key"] = new_scope_key
                payload["product_group"] = new_scope_key
            conn.execute(
                """
                INSERT INTO account_factor_param_configs (
                    username, scope_key, ff_alias, payload_json, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    username,
                    new_scope_key,
                    str(row["ff_alias"]),
                    json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                    now,
                ),
            )
    return True


def delete_scope(username: str, scope_key: str) -> bool:
    scope_key = normalize_product_group(scope_key)
    if scope_key == DEFAULT_SCOPE_KEY:
        return False
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        ensure_factor_param_config_schema(conn)
        conn.execute(
            """
            DELETE FROM account_factor_param_configs
            WHERE username = ? AND scope_key = ?
            """,
            (username, scope_key),
        )
        cursor = conn.execute(
            """
            DELETE FROM account_factor_param_scopes
            WHERE username = ? AND scope_key = ?
            """,
            (username, scope_key),
        )
    return bool(cursor.rowcount)
