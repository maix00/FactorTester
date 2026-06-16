"""SQLite mirror for the generated data dictionary."""
from __future__ import annotations

import sqlite3
import time
from typing import Any

import Settings
from tools.data.sqlite.db import connect_sqlite, replace_rows


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS data_dictionary_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS data_dictionary_data_columns (
            name TEXT PRIMARY KEY,
            code TEXT NOT NULL,
            description TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS data_dictionary_frequency_types (
            name TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            alias TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS data_dictionary_data_sources (
            alias TEXT PRIMARY KEY,
            freq TEXT NOT NULL,
            timezone TEXT NOT NULL,
            columns_count INTEGER NOT NULL,
            columns_list TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS data_dictionary_param_types (
            name TEXT PRIMARY KEY,
            alias TEXT NOT NULL,
            description TEXT NOT NULL,
            default_example TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS data_dictionary_factors (
            name TEXT PRIMARY KEY,
            desc TEXT NOT NULL,
            description TEXT NOT NULL,
            math_expr TEXT NOT NULL,
            category TEXT NOT NULL,
            source_file TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS data_dictionary_factor_params (
            factor_name TEXT NOT NULL,
            param_index INTEGER NOT NULL,
            alias TEXT NOT NULL,
            type TEXT NOT NULL,
            default_value TEXT NOT NULL,
            description TEXT NOT NULL,
            PRIMARY KEY (factor_name, param_index)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS data_dictionary_settings (
            name TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            description TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS data_dictionary_factor_categories (
            prefix TEXT PRIMARY KEY,
            name TEXT NOT NULL
        )
        """
    )
def sync_data_dictionary_sqlite_store() -> str:
    """Build and persist the current data dictionary snapshot."""
    from server.services.data_dictionary import build_data_dictionary

    dd = build_data_dictionary()
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        _ensure_schema(conn)
        conn.execute(
            "INSERT OR REPLACE INTO data_dictionary_meta (key, value) VALUES (?, ?)",
            ("generated_at", dd.generated_at),
        )
        replace_rows(
            conn,
            "data_dictionary_data_columns",
            ["name", "code", "description"],
            [(item.name, item.code, item.description) for item in dd.data_columns],
        )
        replace_rows(
            conn,
            "data_dictionary_frequency_types",
            ["name", "value", "alias"],
            [(item["name"], item["value"], item["alias"]) for item in dd.frequency_types],
        )
        replace_rows(
            conn,
            "data_dictionary_data_sources",
            ["alias", "freq", "timezone", "columns_count", "columns_list"],
            [(item.alias, item.freq, item.timezone, item.columns_count, item.columns_list) for item in dd.data_sources],
        )
        replace_rows(
            conn,
            "data_dictionary_param_types",
            ["name", "alias", "description", "default_example"],
            [(item.name, item.alias, item.description, item.default_example) for item in dd.param_types],
        )
        replace_rows(
            conn,
            "data_dictionary_factors",
            ["name", "desc", "description", "math_expr", "category", "source_file"],
            [(item.name, item.desc, item.description, item.math_expr, item.category, item.source_file) for item in dd.factors],
        )
        conn.execute("DELETE FROM data_dictionary_factor_params")
        for factor in dd.factors:
            for idx, param in enumerate(factor.params):
                conn.execute(
                    """
                    INSERT OR REPLACE INTO data_dictionary_factor_params (
                        factor_name, param_index, alias, type, default_value, description
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (factor.name, idx, param.alias, param.type, param.default_value, param.description),
                )
        replace_rows(
            conn,
            "data_dictionary_settings",
            ["name", "value", "description"],
            [(item.name, item.value, item.description) for item in dd.settings],
        )
        replace_rows(
            conn,
            "data_dictionary_factor_categories",
            ["prefix", "name"],
            [(prefix, name) for prefix, name in dd.factor_categories.items()],
        )
    return str(Settings.CACHE_DB_PATH)


def ensure_data_dictionary_sqlite_store() -> str:
    return sync_data_dictionary_sqlite_store()


def load_data_dictionary_snapshot() -> dict[str, Any] | None:
    """Load the cached data dictionary snapshot if present."""
    from server.services.data_dictionary import DataColumnEntry, DataDictionary, DataSourceEntry, FactorEntry, ParamEntry, ParamTypeEntry, SettingEntry

    try:
        with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
            _ensure_schema(conn)
            generated_at_row = conn.execute(
                "SELECT value FROM data_dictionary_meta WHERE key = 'generated_at'"
            ).fetchone()
            if generated_at_row is None:
                return None
            generated_at = str(generated_at_row["value"] or "")

            data_columns = [
                DataColumnEntry(name=row["name"], code=row["code"], description=row["description"])
                for row in conn.execute(
                    "SELECT name, code, description FROM data_dictionary_data_columns ORDER BY name"
                ).fetchall()
            ]
            frequency_types = [
                {"name": row["name"], "value": row["value"], "alias": row["alias"]}
                for row in conn.execute(
                    "SELECT name, value, alias FROM data_dictionary_frequency_types ORDER BY name"
                ).fetchall()
            ]
            data_sources = [
                DataSourceEntry(
                    alias=row["alias"],
                    freq=row["freq"],
                    timezone=row["timezone"],
                    columns_count=int(row["columns_count"]),
                    columns_list=row["columns_list"],
                )
                for row in conn.execute(
                    "SELECT alias, freq, timezone, columns_count, columns_list FROM data_dictionary_data_sources ORDER BY alias"
                ).fetchall()
            ]
            param_types = [
                ParamTypeEntry(
                    name=row["name"],
                    alias=row["alias"],
                    description=row["description"],
                    default_example=row["default_example"],
                )
                for row in conn.execute(
                    "SELECT name, alias, description, default_example FROM data_dictionary_param_types ORDER BY name"
                ).fetchall()
            ]
            factors = []
            factor_rows = conn.execute(
                "SELECT name, desc, description, math_expr, category, source_file FROM data_dictionary_factors ORDER BY name"
            ).fetchall()
            for row in factor_rows:
                params = [
                    ParamEntry(
                        alias=param_row["alias"],
                        type=param_row["type"],
                        default_value=param_row["default_value"],
                        description=param_row["description"],
                    )
                    for param_row in conn.execute(
                        """
                        SELECT alias, type, default_value, description
                        FROM data_dictionary_factor_params
                        WHERE factor_name = ?
                        ORDER BY param_index
                        """,
                        (row["name"],),
                    ).fetchall()
                ]
                factors.append(
                    FactorEntry(
                        name=row["name"],
                        desc=row["desc"],
                        description=row["description"],
                        math_expr=row["math_expr"],
                        category=row["category"],
                        source_file=row["source_file"],
                        params=params,
                    )
                )
            settings = [
                SettingEntry(name=row["name"], value=row["value"], description=row["description"])
                for row in conn.execute(
                    "SELECT name, value, description FROM data_dictionary_settings ORDER BY name"
                ).fetchall()
            ]
            factor_categories = {
                row["prefix"]: row["name"]
                for row in conn.execute(
                    "SELECT prefix, name FROM data_dictionary_factor_categories ORDER BY prefix"
                ).fetchall()
            }
    except Exception:
        return None

    from server.services.data_dictionary import DataDictionary

    dd = DataDictionary(
        generated_at=generated_at,
        data_columns=data_columns,
        frequency_types=frequency_types,
        data_sources=data_sources,
        param_types=param_types,
        factors=factors,
        settings=settings,
        factor_categories=factor_categories,
    )
    return {
        "generated_at": dd.generated_at,
        "data_columns": [
            {"name": item.name, "code": item.code, "description": item.description}
            for item in dd.data_columns
        ],
        "frequency_types": dd.frequency_types,
        "data_sources": [
            {
                "alias": item.alias,
                "freq": item.freq,
                "timezone": item.timezone,
                "columns_count": item.columns_count,
                "columns_list": item.columns_list,
            }
            for item in dd.data_sources
        ],
        "param_types": [
            {
                "name": item.name,
                "alias": item.alias,
                "description": item.description,
                "default_example": item.default_example,
            }
            for item in dd.param_types
        ],
        "factors": [
            {
                "name": item.name,
                "desc": item.desc,
                "description": item.description,
                "math_expr": item.math_expr,
                "category": item.category,
                "source_file": item.source_file,
                "params": [
                    {
                        "alias": param.alias,
                        "type": param.type,
                        "default_value": param.default_value,
                        "description": param.description,
                    }
                    for param in item.params
                ],
            }
            for item in dd.factors
        ],
        "settings": [
            {"name": item.name, "value": item.value, "description": item.description}
            for item in dd.settings
        ],
        "factor_categories": dd.factor_categories,
    }
