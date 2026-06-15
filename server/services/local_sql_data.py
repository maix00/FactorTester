"""Registry for local SQL stores exposed through the data browser."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True)
class SQLiteStore:
    key: str
    label: str
    path_getter: Callable[[], str]
    ensure: Callable[[], str] | None = None

    def path(self) -> str:
        if self.ensure is not None:
            return self.ensure()
        return self.path_getter()


def _openctp_store_path() -> str:
    from sources.OpenCTP.client import CACHE_DB_PATH
    return str(CACHE_DB_PATH)


def _ensure_openctp_store() -> str:
    from sources.OpenCTP.client import ensure_sqlite_store
    return ensure_sqlite_store()


_STORE_REGISTRY: dict[str, SQLiteStore] = {
    "openctp": SQLiteStore(
        key="openctp",
        label="本地数据 (onlinedata.sqlite)",
        path_getter=_openctp_store_path,
        ensure=_ensure_openctp_store,
    ),
}


def register_store(store: SQLiteStore) -> SQLiteStore:
    _STORE_REGISTRY[store.key] = store
    return store


def iter_stores() -> list[SQLiteStore]:
    return [store for _, store in sorted(_STORE_REGISTRY.items(), key=lambda item: item[0])]


STORES = _STORE_REGISTRY


def list_stores() -> list[dict[str, Any]]:
    return [
        {
            "key": store.key,
            "label": store.label,
            "database": store.path(),
            "tables": len(list_tables(store.key)),
        }
        for store in iter_stores()
    ]


def _store_or_raise(store_key: str) -> SQLiteStore:
    store = _STORE_REGISTRY.get(store_key)
    if store is None:
        raise ValueError(f"Unknown SQL store: {store_key}")
    return store


def _connect(store_key: str) -> sqlite3.Connection:
    store = _store_or_raise(store_key)
    path = Path(store.path())
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def list_tables(store_key: str) -> list[dict[str, Any]]:
    with _connect(store_key) as conn:
        rows = conn.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
            ORDER BY name
            """
        ).fetchall()
        result = []
        for row in rows:
            name = str(row["name"])
            count = conn.execute(f'SELECT COUNT(*) AS n FROM "{name}"').fetchone()["n"]
            result.append({"name": name, "rows": int(count)})
    return result


def read_table(store_key: str, table_name: str, *, limit: int = 200, offset: int = 0) -> dict[str, Any]:
    allowed = {item["name"] for item in list_tables(store_key)}
    if table_name not in allowed:
        raise ValueError(f"Unknown SQL table: {table_name}")
    store = _store_or_raise(store_key)
    limit = max(1, min(int(limit), 1000))
    offset = max(0, int(offset))
    with _connect(store_key) as conn:
        columns = [row["name"] for row in conn.execute(f'PRAGMA table_info("{table_name}")').fetchall()]
        count = int(conn.execute(f'SELECT COUNT(*) AS n FROM "{table_name}"').fetchone()["n"])
        rows = conn.execute(
            f'SELECT * FROM "{table_name}" LIMIT ? OFFSET ?',
            (limit, offset),
        ).fetchall()
    return {
        "store": store.key,
        "store_label": store.label,
        "table": table_name,
        "columns": columns,
        "rows": [dict(row) for row in rows],
        "total": count,
        "limit": limit,
        "offset": offset,
        "database": store.path(),
    }
