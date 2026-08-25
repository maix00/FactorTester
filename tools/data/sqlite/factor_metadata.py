"""SQLite mirror for factor metadata.

This keeps the unified local database useful for catalog browsing and
sqlite-web inspection without depending only on in-memory scans.
"""
from __future__ import annotations

import importlib.util
import os
import sqlite3
import tempfile
import time
from typing import Any

import settings as Settings
from tools.data.sqlite.factor_source_store import list_factor_sources
from tools.data.sqlite.db import connect_sqlite
from tools.data.account_manage import account_display_name, load_accounts
from tools.factors import FactorFamily

CATALOG_TABLE = "factor_family_catalog"
CATALOG_PARAMS_TABLE = "factor_family_catalog_params"


def _load_accounts() -> list[dict[str, Any]]:
    return load_accounts()


def _account_display_name(account: dict[str, Any]) -> str:
    return account_display_name(account)


def _load_public_factors() -> list[dict[str, Any]]:
    return _public_factor_dicts()


def _load_custom_factors(username: str) -> list[dict[str, Any]]:
    return _custom_factor_dicts(username)


def _load_factor_family_from_source(source_code: str, module_name: str) -> tuple[type | None, object | None]:
    if not source_code:
        return None, None
    tmpdir = tempfile.mkdtemp(prefix="factor_metadata_")
    tmpfile = os.path.join(tmpdir, f"{module_name}.py")
    try:
        with open(tmpfile, "w", encoding="utf-8") as file:
            file.write(source_code)
        spec = importlib.util.spec_from_file_location(module_name, tmpfile)
        if spec is None or spec.loader is None:
            return None, None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        for attr_name in dir(module):
            obj = getattr(module, attr_name)
            if isinstance(obj, type) and issubclass(obj, FactorFamily) and obj is not FactorFamily:
                return obj, module
        return None, module
    except Exception:
        return None, None
    finally:
        import shutil

        shutil.rmtree(tmpdir, ignore_errors=True)


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


def _factor_family_name(factor_cls: type, default: str = "FactorFamily") -> str:
    for base in factor_cls.__bases__:
        if base is not FactorFamily and issubclass(base, FactorFamily):
            return base.__name__
    return default


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


def _public_factor_rows() -> list[dict[str, Any]]:
    return list_factor_sources("public")


def _public_factor_dicts() -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for row in _public_factor_rows():
        factor_id = str(row.get("factor_id") or "")
        source_code = str(row.get("source_code") or "")
        updated_at = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(float(row.get("updated_at") or time.time())))
        factor_cls, _ = _load_factor_family_from_source(source_code, factor_id)
        if factor_cls is None:
            result.append(
                {
                    "id": factor_id,
                    "name": factor_id,
                    "category": row.get("category") or "",
                    "factor_family": "FactorFamily",
                    "chinese_name": row.get("chinese_name") or "",
                    "description": row.get("description") or "",
                    "params": [],
                    "source_code": source_code,
                    "is_public": True,
                    "updated_at": updated_at,
                    "load_error": True,
                }
            )
            continue
        try:
            ff = factor_cls()
            result.append(
                {
                    "id": factor_id,
                    "name": factor_id,
                    "category": row.get("category") or _factor_family_name(factor_cls),
                    "factor_family": _factor_family_name(factor_cls),
                    "chinese_name": row.get("chinese_name") or "",
                    "description": row.get("description") or "",
                    "math_expr": getattr(ff, "math_expr", "") or "",
                    "source_code": source_code,
                    "params": [
                        {
                            "alias": getattr(param, "alias", ""),
                            "type": type(param).__name__,
                            "default_value": str(getattr(param, "default_value", "")),
                            "description": getattr(param, "desc", "") or "",
                        }
                        for param in getattr(ff, "params", [])
                    ],
                    "is_public": True,
                    "updated_at": updated_at,
                }
            )
        except Exception:
            result.append(
                {
                    "id": factor_id,
                    "name": factor_id,
                    "category": row.get("category") or "",
                    "factor_family": "FactorFamily",
                    "chinese_name": row.get("chinese_name") or "",
                    "description": row.get("description") or "",
                    "params": [],
                    "source_code": source_code,
                    "is_public": True,
                    "updated_at": updated_at,
                    "load_error": True,
                }
            )
    return result


def _custom_factor_dicts(owner_username: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    rows = [row for row in list_factor_sources("custom") if row.get("owner_username") == owner_username]
    for row in rows:
        factor_id = str(row.get("factor_id") or "")
        source_code = str(row.get("source_code") or "")
        updated_at = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(float(row.get("updated_at") or time.time())))
        factor_cls, _ = _load_factor_family_from_source(source_code, f"_cf_{owner_username}_{factor_id}")
        if factor_cls is None:
            result.append(
                {
                    "id": factor_id,
                    "name": factor_id,
                    "category": row.get("category") or "自编",
                    "factor_family": "FactorFamily",
                    "chinese_name": row.get("chinese_name") or "",
                    "description": row.get("description") or "",
                    "params": [],
                    "source_code": source_code,
                    "is_public": False,
                    "updated_at": updated_at,
                    "load_error": True,
                }
            )
            continue
        try:
            ff = factor_cls()
            result.append(
                {
                    "id": factor_id,
                    "name": factor_cls.__name__,
                    "category": row.get("category") or "自编",
                    "factor_family": _factor_family_name(factor_cls),
                    "chinese_name": row.get("chinese_name") or "",
                    "description": row.get("description") or "",
                    "math_expr": getattr(ff, "math_expr", "") or "",
                    "source_code": source_code,
                    "params": [
                        {
                            "alias": getattr(param, "alias", ""),
                            "type": type(param).__name__,
                            "default_value": str(getattr(param, "default_value", "")),
                            "description": getattr(param, "desc", "") or "",
                        }
                        for param in getattr(ff, "params", [])
                    ],
                    "is_public": False,
                    "updated_at": updated_at,
                }
            )
        except Exception:
            result.append(
                {
                    "id": factor_id,
                    "name": factor_id,
                    "category": row.get("category") or "自编",
                    "factor_family": "FactorFamily",
                    "chinese_name": row.get("chinese_name") or "",
                    "description": row.get("description") or "",
                    "params": [],
                    "source_code": source_code,
                    "is_public": False,
                    "updated_at": updated_at,
                    "load_error": True,
                }
            )
    return result


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
