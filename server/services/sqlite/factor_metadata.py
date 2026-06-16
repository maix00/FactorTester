"""SQLite mirror for factor metadata.

This keeps the unified local database useful for catalog browsing and
sqlite-web inspection without depending only on in-memory scans.
"""
from __future__ import annotations

import sqlite3
import time
from typing import Any

import Settings
from tools.data.sqlite.db import connect_sqlite

CATALOG_TABLE = "factor_family_catalog"
CATALOG_PARAMS_TABLE = "factor_family_catalog_params"


def _load_public_factors() -> list[dict[str, Any]]:
    from server.modules.custom_factors.catalog import list_public_factors

    return list_public_factors()


def _load_custom_factors(username: str) -> list[dict[str, Any]]:
    from server.modules.custom_factors.catalog import list_custom_factors

    return list_custom_factors(username)


def _load_accounts() -> list[dict[str, Any]]:
    from server.services.accounts import load_accounts

    return load_accounts()


def _account_display_name(account: dict[str, Any]) -> str:
    from server.services.accounts import account_display_name

    return account_display_name(account)


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {CATALOG_TABLE} (
            source_kind TEXT NOT NULL,
            owner_username TEXT NOT NULL DEFAULT '',
            owner_alias TEXT NOT NULL DEFAULT '',
            factor_id TEXT NOT NULL,
            factor_name TEXT NOT NULL,
            factor_family TEXT NOT NULL,
            chinese_name TEXT,
            description TEXT,
            math_expr TEXT,
            category TEXT,
            source_file TEXT,
            is_public INTEGER NOT NULL,
            load_error INTEGER NOT NULL DEFAULT 0,
            updated_at REAL NOT NULL,
            PRIMARY KEY (source_kind, owner_username, factor_id)
        )
        """
    )
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {CATALOG_PARAMS_TABLE} (
            source_kind TEXT NOT NULL,
            owner_username TEXT NOT NULL DEFAULT '',
            factor_id TEXT NOT NULL,
            param_index INTEGER NOT NULL,
            alias TEXT,
            type TEXT,
            default_value TEXT,
            description TEXT,
            updated_at REAL NOT NULL,
            PRIMARY KEY (source_kind, owner_username, factor_id, param_index)
        )
        """
    )


def _account_map() -> dict[str, str]:
    result: dict[str, str] = {}
    try:
        for account in _load_accounts():
            username = str(account.get("username") or "").strip()
            if not username:
                continue
            result[username] = _account_display_name(account)
    except Exception:
        pass
    return result


def _insert_factor_rows(conn: sqlite3.Connection, rows: list[dict[str, Any]], *, source_kind: str, owner_username: str, owner_alias: str, now: float) -> None:
    for row in rows:
        conn.execute(
            """
            INSERT OR REPLACE INTO factor_family_catalog (
                source_kind, owner_username, owner_alias, factor_id, factor_name,
                factor_family, chinese_name, description, math_expr, category,
                source_file, is_public, load_error, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source_kind,
                owner_username,
                owner_alias,
                str(row.get("id") or row.get("name") or ""),
                str(row.get("name") or row.get("id") or ""),
                str(row.get("factor_family") or "FactorFamily"),
                str(row.get("chinese_name") or row.get("desc") or ""),
                str(row.get("description") or ""),
                str(row.get("math_expr") or ""),
                str(row.get("category") or ""),
                str(row.get("source_file") or ""),
                1 if row.get("is_public") else 0,
                1 if row.get("load_error") else 0,
                now,
            ),
        )

        params = row.get("params") or []
        if not isinstance(params, list):
            continue
        for param_index, param in enumerate(params):
            if not isinstance(param, dict):
                param = {}
            conn.execute(
                """
                INSERT OR REPLACE INTO factor_family_catalog_params (
                    source_kind, owner_username, factor_id, param_index,
                    alias, type, default_value, description, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source_kind,
                    owner_username,
                    str(row.get("id") or row.get("name") or ""),
                    int(param_index),
                    str(param.get("alias") or ""),
                    str(param.get("type") or ""),
                    str(param.get("default_value") or ""),
                    str(param.get("description") or ""),
                    now,
                ),
            )


def sync_factor_metadata_sqlite_store() -> str:
    """Sync public and custom factor metadata into the unified SQLite store."""
    now = time.time()
    owner_alias_by_username = _account_map()
    accounts = _load_accounts()

    public_factors = _load_public_factors()
    custom_factors_by_owner: dict[str, list[dict[str, Any]]] = {}
    for account in accounts:
        owner_username = str(account.get("username") or "").strip()
        if not owner_username:
            continue
        try:
            custom_factors_by_owner[owner_username] = _load_custom_factors(owner_username)
        except Exception:
            custom_factors_by_owner[owner_username] = []

    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        _ensure_schema(conn)
        conn.execute(f"DELETE FROM {CATALOG_TABLE}")
        conn.execute(f"DELETE FROM {CATALOG_PARAMS_TABLE}")

        _insert_factor_rows(
            conn,
            public_factors,
            source_kind="public",
            owner_username="",
            owner_alias="",
            now=now,
        )

        for account in accounts:
            owner_username = str(account.get("username") or "").strip()
            if not owner_username:
                continue
            owner_alias = owner_alias_by_username.get(owner_username) or str(account.get("alias") or owner_username)
            _insert_factor_rows(
                conn,
                custom_factors_by_owner.get(owner_username, []),
                source_kind="custom",
                owner_username=owner_username,
                owner_alias=owner_alias,
                now=now,
            )

    return str(Settings.CACHE_DB_PATH)


def ensure_factor_metadata_sqlite_store() -> str:
    """Ensure the factor metadata mirror exists and is current."""
    return sync_factor_metadata_sqlite_store()
