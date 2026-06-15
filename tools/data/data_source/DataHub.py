"""DataHub — 统一数据中心。

职责：
  1. 管理 SQLite 数据库及其注册的 DataProvider（schema 建表 + 数据同步）
  2. 管理 DataFrame 加载器（按 namespace 注册），统一通过 IdleResourceManager 缓存
  3. 全局单例：整个应用只应有一个 DataHub 实例

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
from pathlib import Path
from typing import Any, Callable, Dict, List

import pandas as pd

from tools.base.IdleResourceManager import IdleResourceManager

logger = logging.getLogger(__name__)


class DataHub:
    """
    统一数据中心（全局单例）。

    ── SQLite 管理 ──
      - 持有多个数据库路径
      - 注册/注销 DataProvider
      - 统一 ensure_schema() / sync()

    ── DataFrame 加载 ──
      - register_loader(namespace, fn)  注册加载器
      - load(namespace, key)           通过 IdleResourceManager 缓存加载
      - touch(namespace, key)          仅更新时间戳
      - invalidate(namespace, key)     强制失效
    """

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
        self._stores: Dict[str, Path] = {}          # store_key → db_path
        self._providers: Dict[str, 'DataProvider'] = {}

        # ── DataFrame 加载器 ──
        self._loaders: Dict[str, Callable[..., pd.DataFrame]] = {}
        self._idle_manager = IdleResourceManager.get_instance()

    # ═══════════════════════════════════════════════════════════════
    # SQLite 管理
    # ═══════════════════════════════════════════════════════════════

    def register_store(self, key: str, db_path: str | Path) -> None:
        """注册一个 SQLite 数据库路径。"""
        self._stores[key] = Path(db_path)
        logger.info("Store registered: %s → %s", key, db_path)

    def get_store_path(self, key: str) -> Path:
        """获取已注册的数据库路径。"""
        if key not in self._stores:
            raise KeyError(f"Unknown store: {key}")
        return self._stores[key]

    def connect_store(self, store_key: str) -> sqlite3.Connection:
        """打开指定 store 的数据库连接。"""
        path = self.get_store_path(store_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path))
        conn.row_factory = sqlite3.Row
        return conn

    def init_stores(self) -> None:
        """遍历所有注册的 DataProvider，确保各自的表/Schema 存在。"""
        for store_key in self._stores:
            with self.connect_store(store_key) as conn:
                for provider in self._providers.values():
                    try:
                        provider.ensure_schema(conn)
                    except Exception:
                        logger.exception("ensure_schema failed for %s on %s", provider.key, store_key)

    # ── DataProvider 管理 ──

    def register_provider(self, provider: 'DataProvider') -> 'DataProvider':
        if provider.key in self._providers:
            logger.warning("DataProvider %s already registered, skipping", provider.key)
            return self._providers[provider.key]
        self._providers[provider.key] = provider
        logger.info("DataProvider registered: %s (%s)", provider.key, provider.label)
        return provider

    def unregister_provider(self, key: str) -> None:
        self._providers.pop(key, None)

    def get_provider(self, key: str) -> 'DataProvider | None':
        return self._providers.get(key)

    @property
    def providers(self) -> List['DataProvider']:
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
                    n = provider.sync(conn, refresh=refresh)
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
