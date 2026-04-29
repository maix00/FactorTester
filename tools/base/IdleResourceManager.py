"""
全局空闲资源管理器

组合 ResourceRegistry（记录访问时间）+ IdleResourceReaper（守护线程回收），
提供按 (namespace, path) 缓存的 DataFrame 加载/释放能力。
多个品种共享同一个 path 时只加载一次，idle 超时后自动释放。

切换分布式：只需把 LocalResourceRegistry 换成 RedisResourceRegistry，其余代码不动。

用法：
    manager = IdleResourceManager.get_instance()
    manager.start(idle_timeout=10)

    ri = manager.load('roller_info', path)   # 自动缓存 + 更新访问时间
    manager.touch('roller_info', path)       # 仅更新访问时间
"""
import threading
import time
from typing import Any

import pandas as pd

from tools.base.ResourceRegistry import LocalResourceRegistry, ResourceRegistry
from tools.base.IdleResourceReaper import IdleResourceReaper


class IdleResourceManager:
    """
    全局空闲资源管理器（单例）。

    内部：
      - ResourceRegistry: 记录每个 key 的最后访问时间
      - IdleResourceReaper: 守护线程扫描超时 key，删除缓存
      - _cache: {(namespace, path): {'data': DataFrame, 'ttl': float}}
    """
    _instance: 'IdleResourceManager | None' = None
    _lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> 'IdleResourceManager':
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def __init__(self):
        if IdleResourceManager._instance is not None:
            raise RuntimeError("Use IdleResourceManager.get_instance()")
        # 默认用内存版 registry；分布式时可替换
        self._registry: ResourceRegistry = LocalResourceRegistry()
        self._reaper: IdleResourceReaper | None = None
        # cache: {(namespace, path): {'data': DataFrame, 'ttl': float}}
        self._cache: dict[tuple[str, str], dict[str, Any]] = {}
        self._cache_lock = threading.Lock()
        self._default_reader = lambda p: pd.read_parquet(p)

    @property
    def registry(self) -> ResourceRegistry:
        """公开 registry 供外部记录/查询资源活动时间。"""
        return self._registry

    # ── 启动 / 停止 ──

    def start(self, idle_timeout: float = 10, scan_interval: float = 5):
        """启动回收守护线程。idle_timeout 同时作为默认 TTL。"""
        if self._reaper is not None:
            return
        self._default_idle_timeout = idle_timeout
        self._reaper = IdleResourceReaper(
            registry=self._registry,
            idle_timeout=idle_timeout,
            interval=scan_interval,
            on_recycle=self._on_recycle,
        )
        self._reaper.start()

    def stop(self):
        if self._reaper:
            self._reaper.stop()
            self._reaper = None

    # ── 切换 registry（分布式用） ──

    def set_registry(self, registry: ResourceRegistry):
        """替换底层注册表实现（如从 Local 切换到 Redis）。"""
        self._registry = registry
        if self._reaper:
            self._reaper.stop()
            self._reaper = IdleResourceReaper(
                registry=registry,
                idle_timeout=self._default_idle_timeout,
                interval=5,
                on_recycle=self._on_recycle,
            )
            self._reaper.start()

    # ── 对外 API ──

    def load(self, namespace: str, path: str, ttl: float | None = None,
             reader=None) -> pd.DataFrame:
        """
        加载 DataFrame（按 (namespace, path) 缓存）。已缓存则直接返回。
        同时记录访问时间到 registry。

        namespace: 资源类型（如 'roller_info'、'sectors'）
        path:      文件路径
        ttl:       空闲超时秒数（默认用 start() 时设置的值）
        reader:    自定义加载函数 f(path) -> DataFrame，默认 pd.read_parquet
        """
        key = (namespace, path)
        resource_id = self._to_resource_id(namespace, path)

        with self._cache_lock:
            entry = self._cache.get(key)
            if entry is not None:
                self._registry.record_use(resource_id)
                return entry['data']

            # 加载
            loader = reader or self._default_reader
            data = loader(path)
            self._cache[key] = {
                'data': data,
                'ttl': ttl if ttl is not None else getattr(self, '_default_idle_timeout', 10),
            }
            self._registry.record_use(resource_id)
            return data

    def touch(self, namespace: str, path: str):
        """仅更新访问时间，不加载数据。"""
        resource_id = self._to_resource_id(namespace, path)
        self._registry.record_use(resource_id)

    # ── 内部 ──

    @staticmethod
    def _to_resource_id(namespace: str, path: str) -> str:
        return f"{namespace}:{path}"

    def _on_recycle(self, resource_id: str):
        """Reaper 回调：从缓存中删除超时资源。"""
        # resource_id 格式：namespace:path
        for key in list(self._cache.keys()):
            if self._to_resource_id(*key) == resource_id:
                with self._cache_lock:
                    self._cache.pop(key, None)
                break

