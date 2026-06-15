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
import logging
import threading
import time
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List

import pandas as pd

logger = logging.getLogger(__name__)


# =============================================================================
# 资源注册表 —— 抽象接口 + 单机实现
# =============================================================================

class ResourceRegistry(ABC):
    """资源注册表抽象接口。"""

    @abstractmethod
    def record_use(self, resource_id: str) -> None:
        """记录资源被使用（更新时间戳）。"""
        ...

    @abstractmethod
    def get_idle_resources(self, idle_threshold_seconds: float) -> List[str]:
        """返回所有闲置超时的 resource_id 列表。"""
        ...

    @abstractmethod
    def remove(self, resource_id: str) -> None:
        """从注册表中删除该资源的记录。"""
        ...


class LocalResourceRegistry(ResourceRegistry):
    """线程安全的内存版资源注册表。"""

    def __init__(self):
        self._last_access: Dict[str, float] = {}
        self._lock = threading.Lock()

    def record_use(self, resource_id: str) -> None:
        with self._lock:
            self._last_access[resource_id] = time.time()

    def get_idle_resources(self, idle_threshold_seconds: float) -> List[str]:
        now = time.time()
        with self._lock:
            return [
                rid for rid, last_ts in self._last_access.items()
                if now - last_ts > idle_threshold_seconds
            ]

    def remove(self, resource_id: str) -> None:
        with self._lock:
            self._last_access.pop(resource_id, None)


# =============================================================================
# 空闲资源回收线程
# =============================================================================

class IdleResourceReaper:
    """
    空闲资源回收器。

    registry:     资源注册表（记录最后使用时间）
    idle_timeout: 闲置超时秒数
    interval:     扫描间隔秒数
    on_recycle:   回收回调 f(resource_id) → None，由业务注册
    """

    def __init__(
        self,
        registry: ResourceRegistry,
        idle_timeout: float = 60,
        interval: float = 5,
        on_recycle: Callable[[str], None] | None = None,
    ):
        self.registry = registry
        self.idle_timeout = idle_timeout
        self.interval = interval
        self._on_recycle = on_recycle
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def on_recycle(self) -> Callable[[str], None] | None:
        return self._on_recycle

    @on_recycle.setter
    def on_recycle(self, fn: Callable[[str], None] | None):
        self._on_recycle = fn

    def start(self):
        """启动守护线程。"""
        if self._thread is not None:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="idle-resource-reaper")
        self._thread.start()

    def stop(self):
        """停止守护线程。"""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=10)
            self._thread = None

    def _run(self):
        while not self._stop_event.wait(self.interval):
            try:
                idle_ids = self.registry.get_idle_resources(self.idle_timeout)
                for rid in idle_ids:
                    if self._on_recycle:
                        try:
                            self._on_recycle(rid)
                        except Exception:
                            logger.exception("Error recycling resource: %s", rid)
                    self.registry.remove(rid)
            except Exception:
                logger.exception("Error during idle resource scan")


# =============================================================================
# 全局空闲资源管理器（单例）
# =============================================================================

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

    def invalidate(self, namespace: str, path: str):
        """强制从缓存和 registry 中删除指定资源。"""
        resource_id = self._to_resource_id(namespace, path)
        key = (namespace, path)
        with self._cache_lock:
            self._cache.pop(key, None)
        self._registry.remove(resource_id)

    # ── 内部 ──

    @staticmethod
    def _to_resource_id(namespace: str, path: str) -> str:
        return f"{namespace}:{path}"

    def _on_recycle(self, resource_id: str):
        """Reaper 回调：从缓存中删除超时资源。"""
        for key in list(self._cache.keys()):
            if self._to_resource_id(*key) == resource_id:
                with self._cache_lock:
                    entry = self._cache.pop(key, None)
                if entry is not None:
                    logger.info("[IdleResourceManager] 回收闲置资源: %s", resource_id)
                    print(f"[IdleResourceManager] 回收闲置资源: {resource_id}")
                break

