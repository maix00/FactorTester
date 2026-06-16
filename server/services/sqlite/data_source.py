"""SQLite mirror for registered DataSource metadata and Parquet previews."""
from __future__ import annotations

import os
import sqlite3
import time
from typing import Any

import duckdb
import pandas as pd

import Settings
from server.services.data_dictionary import scan_data_sources
from tools.data.sqlite.db import connect_sqlite, replace_dataframe, safe_ident

PREVIEW_PRODUCTS_PER_SOURCE = 1
PREVIEW_ROW_LIMIT = 80


def _read_parquet_preview(path: str, limit: int) -> pd.DataFrame:
    try:
        escaped = path.replace("'", "''")
        con = duckdb.connect()
        try:
            return con.execute(
                f"SELECT * FROM read_parquet('{escaped}') LIMIT {int(limit)}"
            ).df()
        finally:
            con.close()
    except Exception:
        return pd.DataFrame()


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS data_sources (
            alias TEXT PRIMARY KEY,
            label TEXT,
            freq TEXT,
            timezone TEXT,
            columns_count INTEGER,
            columns_list TEXT,
            updated_at REAL NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS data_source_products (
            source_alias TEXT NOT NULL,
            product_name TEXT NOT NULL,
            product_alias TEXT,
            path TEXT,
            file_exists INTEGER NOT NULL,
            file_size INTEGER,
            mtime REAL,
            updated_at REAL NOT NULL,
            PRIMARY KEY (source_alias, product_name)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS data_source_previews (
            source_alias TEXT NOT NULL,
            product_name TEXT NOT NULL,
            table_name TEXT NOT NULL,
            path TEXT NOT NULL,
            row_count INTEGER NOT NULL,
            updated_at REAL NOT NULL,
            PRIMARY KEY (source_alias, product_name)
        )
        """
    )


def _clear_preview_tables(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table' AND name LIKE 'preview__%'
        """
    ).fetchall()
    for row in rows:
        conn.execute(f'DROP TABLE IF EXISTS "{row["name"]}"')
def _product_name(product: Any) -> str:
    return str(getattr(product, "name", getattr(product, "alias", product)))


def _product_alias(product: Any) -> str:
    return str(getattr(product, "alias", getattr(product, "name", product)))


def sync_data_source_sqlite_store() -> str:
    """Sync DataSource metadata and small Parquet previews into SQLite."""
    try:
        from sources import load_all_sources

        load_all_sources()
    except Exception:
        pass

    try:
        products = list(Settings.get_all_products())
    except Exception:
        products = []

    sources = scan_data_sources()
    source_objects = {}
    try:
        from tools.data import DataProviderProductTS
        from tools.data import _DataMultipleProviderMeta as DataSourceMeta

        registry = DataSourceMeta._ensure_registry(DataProviderProductTS)
        source_objects = dict(sorted(registry.items()))
    except Exception:
        source_objects = {}

    now = time.time()
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        _ensure_schema(conn)
        conn.execute("DELETE FROM data_sources")
        conn.execute("DELETE FROM data_source_products")
        conn.execute("DELETE FROM data_source_previews")
        _clear_preview_tables(conn)

        for source_entry in sources:
            source = source_objects.get(source_entry.alias)
            conn.execute(
                """
                INSERT OR REPLACE INTO data_sources (
                    alias, label, freq, timezone, columns_count, columns_list, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source_entry.alias,
                    source_entry.alias,
                    source_entry.freq,
                    source_entry.timezone,
                    source_entry.columns_count,
                    source_entry.columns_list,
                    now,
                ),
            )

            if source is None:
                continue

            preview_budget = PREVIEW_PRODUCTS_PER_SOURCE
            for product in products:
                try:
                    if product not in source:
                        continue
                    path = source.get_path(product)
                except Exception:
                    continue

                file_exists = bool(path and os.path.isfile(path))
                stat = os.stat(path) if file_exists else None
                conn.execute(
                    """
                    INSERT OR REPLACE INTO data_source_products (
                        source_alias, product_name, product_alias, path, file_exists,
                        file_size, mtime, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        source_entry.alias,
                        _product_name(product),
                        _product_alias(product),
                        path,
                        1 if file_exists else 0,
                        int(stat.st_size) if stat is not None else None,
                        float(stat.st_mtime) if stat is not None else None,
                        now,
                    ),
                )

                if preview_budget <= 0 or not file_exists:
                    continue

                preview = _read_parquet_preview(path, PREVIEW_ROW_LIMIT)
                if preview.empty:
                    continue

                preview_table = f"preview__{safe_ident(source_entry.alias)}__{safe_ident(_product_alias(product))}"
                preview = preview.copy()
                preview.insert(0, "__row_no__", range(1, len(preview) + 1))
                preview.insert(0, "__product__", _product_name(product))
                preview.insert(0, "__source__", source_entry.alias)
                replace_dataframe(conn, preview_table, preview)
                conn.execute(
                    """
                    INSERT OR REPLACE INTO data_source_previews (
                        source_alias, product_name, table_name, path, row_count, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        source_entry.alias,
                        _product_name(product),
                        preview_table,
                        path,
                        int(len(preview)),
                        now,
                    ),
                )
                preview_budget -= 1

    return str(Settings.CACHE_DB_PATH)


def ensure_data_source_sqlite_store() -> str:
    return sync_data_source_sqlite_store()
