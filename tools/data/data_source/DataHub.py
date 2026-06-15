"""DataHub — 管理一个 SQLite 数据库及其注册的 DataProvider。"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Dict, List

from .DataProvider import DataProvider

logger = logging.getLogger(__name__)


class DataHub:
    """
    管理一个 SQLite 数据库及其注册的 DataProvider。

    职责：
      - 持有数据库连接路径
      - 注册/注销 DataProvider
      - 统一 ensure_schema() / sync()
      - 将来可实例化多个 Hub 对应不同存储中心
    """

    def __init__(self, db_path: str | Path):
        self._db_path = Path(db_path)
        self._providers: Dict[str, DataProvider] = {}

    @property
    def path(self) -> Path:
        return self._db_path

    def connect(self) -> sqlite3.Connection:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        return conn

    # ── provider 管理 ──

    def register(self, provider: DataProvider) -> DataProvider:
        if provider.key in self._providers:
            logger.warning("DataProvider %s already registered, skipping", provider.key)
            return self._providers[provider.key]
        self._providers[provider.key] = provider
        logger.info("DataProvider registered: %s (%s)", provider.key, provider.label)
        return provider

    def unregister(self, key: str) -> None:
        self._providers.pop(key, None)

    def get_provider(self, key: str) -> DataProvider | None:
        return self._providers.get(key)

    @property
    def providers(self) -> List[DataProvider]:
        return list(self._providers.values())

    # ── 统一操作 ──

    def ensure_all_schemas(self) -> None:
        """遍历所有注册的 DataProvider，确保各自的表/Schema 存在。"""
        with self.connect() as conn:
            for provider in self._providers.values():
                try:
                    provider.ensure_schema(conn)
                except Exception:
                    logger.exception("ensure_schema failed for %s", provider.key)

    def sync(self, key: str | None = None, refresh: bool = False) -> Dict[str, int]:
        """同步数据。key 为 None 则同步全部。返回 {key: new_rows}。"""
        providers_to_sync = (
            [self._providers[key]] if key
            else list(self._providers.values())
        )
        results: Dict[str, int] = {}
        with self.connect() as conn:
            for provider in providers_to_sync:
                try:
                    n = provider.sync(conn, refresh=refresh)
                    results[provider.key] = n
                except Exception:
                    logger.exception("sync failed for %s", provider.key)
                    results[provider.key] = -1
        return results
