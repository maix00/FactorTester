"""SQLite Store 兼容层 — 委托给 DataHub。

此模块保留原有 API（SQLiteStore, register_store, iter_stores, list_stores,
list_tables, read_table, STORES），内部全部委托给 DataHub 单例。

新代码应直接使用 DataHub.get_instance() 而非此模块。
"""

from __future__ import annotations

from typing import Any

from tools.data.hub import DataHub, SQLiteStore  # noqa: F401


def _hub() -> DataHub:
    return DataHub.get_instance()


# ── 初始化：注册统一本地数据 store ───────────────────────────────

def _sqlite_store_path() -> str:
    import settings as Settings
    return str(Settings.CACHE_DB_PATH)


def _ensure_sqlite_store() -> str:
    from sources.OpenCTP.client import ensure_sqlite_store
    return ensure_sqlite_store()


_hub().register_sqlite_store(SQLiteStore(
    key="openctp",
    label="统一主库 (unifieddata.sqlite)",
    path_getter=_sqlite_store_path,
    ensure=_ensure_sqlite_store,
))


# ── 兼容 API ──────────────────────────────────────────────────────

def register_store(store: SQLiteStore) -> SQLiteStore:
    return _hub().register_sqlite_store(store)


def iter_stores() -> list[SQLiteStore]:
    return _hub().iter_sqlite_stores()


def list_stores() -> list[dict[str, Any]]:
    return _hub().list_stores()


def list_tables(store_key: str) -> list[dict[str, Any]]:
    return _hub().list_tables(store_key)


def read_table(store_key: str, table_name: str,
               *, limit: int = 200, offset: int = 0) -> dict[str, Any]:
    return _hub().read_table(store_key, table_name, limit=limit, offset=offset)


STORES = {}  # 废弃，保留仅向后兼容
