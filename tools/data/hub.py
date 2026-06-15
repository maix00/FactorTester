"""DataHub — 统一数据中心。

职责：
  1. 管理所有本地 SQLite 数据库（注册/连接/schema/sync）
  2. 管理 DataFrame 加载器（按 namespace 注册），统一通过 IdleResourceManager 缓存
  3. 提供 SQLite Web 浏览器所需的 list_stores / list_tables / read_table 接口
  4. 全局单例：整个应用只应有一个 DataHub 实例

用法：
    hub = DataHub.get_instance()
    hub.init_stores()          # 初始化所有 SQLite 库的 schema
    hub.register_loader('datameta', _load_datameta)
    hub.register_loader('roller_info', _load_roller_info)

    df = hub.load('datameta', 'CTP:AG2506:MIN1')
    df = hub.load('roller_info', '/path/to/roller.parquet')

数据流向：
    调用方 → DataHub.load(ns, key) → IdleResourceManager.load(ns, key, reader)
                                          ↓
                                    命中缓存 → 返回 DataFrame
                                    未命中 → 调注册的 reader → 缓存 → 返回
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, List

import pandas as pd

if TYPE_CHECKING:
    from .providers.DataProvider import DataProvider, DataProviderSync

from tools.data.cache.IdleResourceManager import IdleResourceManager

logger = logging.getLogger(__name__)


# ── 数据结构 ───────────────────────────────────────────────────────
@dataclass(frozen=True)
class SQLiteStore:
    """描述一个本地 SQLite 数据库。"""
    key: str
    label: str
    path_getter: Callable[[], str]
    ensure: Callable[[], str] | None = None

    def path(self) -> str:
        if self.ensure is not None:
            return self.ensure()
        return self.path_getter()


@dataclass(frozen=True)
class VisitSource:
    """描述一个参与访问追踪的数据源。"""
    key: str
    label: str


class DataHub:

    _instance: 'DataHub | None' = None
    _instance_lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> 'DataHub':
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def __init__(self):
        if DataHub._instance is not None:
            raise RuntimeError("Use DataHub.get_instance()")
        # ── SQLite 管理 ──
        self._sqlite_stores: Dict[str, SQLiteStore] = {}  # store_key → SQLiteStore
        self._providers: dict[str, DataProvider] = {}
        self._visit_sources: Dict[str, VisitSource] = {}  # source_key → VisitSource

        # ── DataFrame 加载器 ──
        self._loaders: Dict[str, Callable[..., pd.DataFrame]] = {}
        self._idle_manager = IdleResourceManager.get_instance()

    # ═══════════════════════════════════════════════════════════════
    # SQLite Store 管理（替代 local_sql_data.py）
    # ═══════════════════════════════════════════════════════════════

    def register_sqlite_store(self, store: SQLiteStore) -> SQLiteStore:
        """注册一个 SQLiteStore。返回传入的 store。"""
        self._sqlite_stores[store.key] = store
        logger.info("SQLiteStore registered: %s (%s) → %s", store.key, store.label, store.path())
        return store

    def iter_sqlite_stores(self) -> List[SQLiteStore]:
        """返回所有已注册的 SQLiteStore（按 key 排序）。"""
        return [
            self._sqlite_stores[key]
            for key in sorted(self._sqlite_stores)
        ]

    def _get_sqlite_store(self, store_key: str) -> SQLiteStore:
        store = self._sqlite_stores.get(store_key)
        if store is None:
            raise ValueError(f"Unknown SQLite store: {store_key}")
        return store

    def _connect_sqlite(self, store_key: str) -> sqlite3.Connection:
        """打开指定 SQLiteStore 的数据库连接。"""
        store = self._get_sqlite_store(store_key)
        path = Path(store.path())
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path))
        conn.row_factory = sqlite3.Row
        return conn

    # ── SQLite Web 接口（供 sqlite_web_mount.py 和 core.py 使用）─

    def list_stores(self) -> List[Dict[str, Any]]:
        """列出所有 SQLite store（供 Web API / sqlite_web_mount 用）。"""
        result = []
        for store in self.iter_sqlite_stores():
            tables = self.list_tables(store.key)
            result.append({
                "key": store.key,
                "label": store.label,
                "database": store.path(),
                "tables": len(tables),
            })
        return result

    def list_tables(self, store_key: str) -> List[Dict[str, Any]]:
        """列出指定 store 的所有表（含行数）。"""
        with self._connect_sqlite(store_key) as conn:
            rows = conn.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type IN ('table', 'view') AND name NOT LIKE 'sqlite_%'
                ORDER BY name
                """
            ).fetchall()
            result = []
            for row in rows:
                name = str(row["name"])
                count = conn.execute(
                    f'SELECT COUNT(*) AS n FROM "{name}"'
                ).fetchone()["n"]
                result.append({"name": name, "rows": int(count)})
        return result

    def read_table(self, store_key: str, table_name: str,
                   *, limit: int = 200, offset: int = 0) -> Dict[str, Any]:
        """读取指定表的数据（分页）。"""
        allowed = {item["name"] for item in self.list_tables(store_key)}
        if table_name not in allowed:
            raise ValueError(f"Unknown SQL table: {table_name}")
        store = self._get_sqlite_store(store_key)
        limit = max(1, min(int(limit), 1000))
        offset = max(0, int(offset))
        with self._connect_sqlite(store_key) as conn:
            columns = [
                row["name"]
                for row in conn.execute(
                    f'PRAGMA table_info("{table_name}")'
                ).fetchall()
            ]
            count = int(
                conn.execute(
                    f'SELECT COUNT(*) AS n FROM "{table_name}"'
                ).fetchone()["n"]
            )
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

    # ═══════════════════════════════════════════════════════════════
    # Visit 访问追踪（替代 sources/visits/registry.py + _store.py）
    # ═══════════════════════════════════════════════════════════════

    def register_visit_source(self, key: str, label: str) -> VisitSource:
        """注册一个参与访问追踪的数据源。内置 ensure_schema 会自动建表。"""
        source = VisitSource(key=key, label=label)
        self._visit_sources[key] = source
        logger.info("VisitSource registered: %s (%s)", key, label)
        return source

    def iter_visit_sources(self) -> List[VisitSource]:
        """返回所有已注册的 VisitSource（按 key 排序）。"""
        return [
            self._visit_sources[key]
            for key in sorted(self._visit_sources)
        ]

    def ensure_visits_schema(self) -> None:
        """确保 source_visits 表存在于 openctp store 中。"""
        # 如果 openctp store 尚未注册，自动注册
        if "openctp" not in self._sqlite_stores:
            import Settings
            self.register_store("openctp", Settings.CACHE_DB_PATH)
        with self._connect_sqlite("openctp") as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS source_visits (
                    source_key TEXT PRIMARY KEY,
                    source_label TEXT NOT NULL,
                    last_access_date TEXT NOT NULL,
                    last_access_at REAL NOT NULL
                )
                """
            )

    def record_visit(self, source_key: str, *,
                     source_label: str,
                     access_date: date | str | None = None) -> str:
        """记录一次数据源访问。"""
        visit_date = (
            access_date.isoformat() if isinstance(access_date, date)
            else str(access_date or date.today().isoformat())
        )
        self.ensure_visits_schema()
        with self._connect_sqlite("openctp") as conn:
            conn.execute(
                """
                INSERT INTO source_visits (source_key, source_label, last_access_date, last_access_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(source_key) DO UPDATE SET
                    source_label = excluded.source_label,
                    last_access_date = excluded.last_access_date,
                    last_access_at = excluded.last_access_at
                """,
                (source_key, source_label, visit_date, time.time()),
            )
        return visit_date

    def get_visit(self, source_key: str) -> Dict[str, Any] | None:
        """查询某个数据源的最后访问记录。"""
        try:
            self.ensure_visits_schema()
            with self._connect_sqlite("openctp") as conn:
                row = conn.execute(
                    """
                    SELECT source_key, source_label, last_access_date, last_access_at
                    FROM source_visits
                    WHERE source_key = ?
                    """,
                    (source_key,),
                ).fetchone()
            if row is None:
                return None
            return dict(row)
        except Exception:
            return None

    def get_latest_access_date(self, source_key: str) -> str | None:
        """查询某数据源的最后访问日期字符串。"""
        visit = self.get_visit(source_key)
        if visit is None:
            return None
        return str(visit["last_access_date"])

    # ═══════════════════════════════════════════════════════════════
    # 旧 SQLite Store 管理（底层数据库路径，可选用）
    # ═══════════════════════════════════════════════════════════════

    def register_store(self, key: str, db_path: str | Path) -> None:
        """（旧接口）注册一个 SQLite 数据库路径，内部转为 SQLiteStore。"""
        store = SQLiteStore(key=key, label=key, path_getter=lambda p=str(db_path): p)
        self._sqlite_stores[key] = store
        logger.info("Store registered (legacy): %s → %s", key, db_path)

    def get_store_path(self, key: str) -> Path:
        """获取已注册的数据库路径。"""
        store = self._get_sqlite_store(key)
        return Path(store.path())

    def connect_store(self, store_key: str) -> sqlite3.Connection:
        """打开指定 store 的数据库连接（委托给 _connect_sqlite）。"""
        return self._connect_sqlite(store_key)

    def init_stores(self) -> None:
        """遍历所有注册的 DataProvider，确保各自的表/Schema 存在。"""
        for store_key in self._sqlite_stores:
            with self._connect_sqlite(store_key) as conn:
                for provider in self._providers.values():
                    try:
                        provider.ensure_schema(conn)
                    except Exception:
                        logger.exception("ensure_schema failed for %s on %s", provider.key, store_key)

    # ── DataProvider 管理 ──

    def register_provider(self, provider: DataProvider) -> DataProvider:
        if provider.key in self._providers:
            logger.warning("DataProvider %s already registered, skipping", provider.key)
            return self._providers[provider.key]
        self._providers[provider.key] = provider
        logger.info("DataProvider registered: %s (%s)", provider.key, provider.label)
        return provider

    def unregister_provider(self, key: str) -> None:
        self._providers.pop(key, None)

    def get_provider(self, key: str) -> DataProvider | None:
        return self._providers.get(key)

    @property
    def providers(self) -> list[DataProvider]:
        return list(self._providers.values())

    def sync(self, provider_key: str | None = None, refresh: bool = False) -> Dict[str, int]:
        """同步数据。provider_key 为 None 则同步全部。返回 {key: new_rows}。"""
        providers_to_sync = (
            [self._providers[provider_key]] if provider_key
            else list(self._providers.values())
        )
        results: Dict[str, int] = {}
        for provider in providers_to_sync:
            # 找到该 provider 对应的 store
            store_key = getattr(provider, '_store_key', 'openctp')
            with self.connect_store(store_key) as conn:
                try:
                    if hasattr(provider, 'sync'):
                        n = provider.sync(conn, refresh=refresh)  # type: ignore[union-attr]
                    else:
                        n = 0
                    results[provider.key] = n
                except Exception:
                    logger.exception("sync failed for %s", provider.key)
                    results[provider.key] = -1
        return results

    # ═══════════════════════════════════════════════════════════════
    # DataFrame 加载（委托给 IdleResourceManager）
    # ═══════════════════════════════════════════════════════════════

    def register_loader(self, namespace: str, loader: Callable[..., pd.DataFrame]) -> None:
        """
        注册一个 DataFrame 加载器。

        namespace:  资源类型（如 'datameta'、'roller_info'）
        loader:     加载函数 f(key, **kwargs) → DataFrame
                    当 IdleResourceManager 缓存未命中时调用
        """
        self._loaders[namespace] = loader
        logger.info("Loader registered: %s", namespace)

    def unregister_loader(self, namespace: str) -> None:
        self._loaders.pop(namespace, None)

    def load(self, namespace: str, key: str,
             ttl: float | None = None,
             force_reload: bool = False,
             reader: Callable[[str], pd.DataFrame] | None = None,
             **loader_kwargs) -> pd.DataFrame:
        """
        加载 DataFrame（通过 IdleResourceManager 缓存）。

        namespace:     资源类型（对应 register_loader 时注册的名称）
        key:           资源键（如 'CTP:AG2506:MIN1'、'/path/to/file.parquet'）
        ttl:           空闲超时秒数（None 则用 IdleResourceManager 默认值）
        force_reload:  强制跳过缓存，重新加载
        reader:        可选，直接指定加载函数。优先级：reader > 注册的 loader > IdleResourceManager 默认
        loader_kwargs: 传给注册 loader 的额外参数（reader 传入时忽略）
        """
        if reader is not None:
            fn = reader
        else:
            registered = self._loaders.get(namespace)
            if registered is None:
                # 没有注册 loader 也没有传 reader：透传给 IdleResourceManager，
                # 它会用默认 pd.read_parquet
                fn = None
            elif loader_kwargs:
                fn = lambda _key, _fn=registered, _kw=loader_kwargs: _fn(_key, **_kw)
            else:
                fn = registered

        if force_reload:
            self._idle_manager.invalidate(namespace, key)

        return self._idle_manager.load(
            namespace=namespace,
            path=key,
            ttl=ttl,
            reader=fn,
        )

    def touch(self, namespace: str, key: str) -> None:
        """仅更新访问时间，不加载数据。"""
        self._idle_manager.touch(namespace, key)

    def invalidate(self, namespace: str, key: str) -> None:
        """强制使缓存失效。"""
        self._idle_manager.invalidate(namespace, key)
