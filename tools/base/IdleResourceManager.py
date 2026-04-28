"""
全局空闲资源管理器

用一个独立守护线程统一管理通过路径加载的 DataFrame 资源。
多个品种共享同一个 path 时只加载一次，idle 超时后释放以节省内存。

用法：
    manager = IdleResourceManager.get_instance()
    manager.start()

    ri = manager.load('roller_info', path, ttl=10)      # 加载 DataFrame（自动缓存 + 更新访问时间）
    # ri 可能被多个调用者持有；超时释放后外部引用变 None，自行判空重新 load
"""
import threading
import time
from typing import Any

import pandas as pd


class IdleResourceManager:
    """
    全局空闲资源管理器（单例）。

    以 (namespace, path) 为键缓存 DataFrame。
    记录每个键的最后访问时间，后台线程定期扫描，超时则清空缓存。

    缓存键格式：(namespace, path) —— namespace 用于区分不同类型（如 'roller_info'）
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
        # cache: {(namespace, path): {'data': DataFrame, 'last_access': float, 'ttl': float}}
        self._cache: dict[tuple[str, str], dict[str, Any]] = {}
        self._cache_lock = threading.Lock()
        self._running = False
        self._thread: threading.Thread | None = None
        self._scan_interval = 5

    def start(self, scan_interval: float = 5):
        """启动守护线程。"""
        if self._running:
            return
        self._scan_interval = scan_interval
        self._running = True
        self._thread = threading.Thread(target=self._scan_loop, daemon=True, name="idle-resource-cleaner")
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=10)

    def load(self, namespace: str, path: str, ttl: float = 10,
             reader=None) -> pd.DataFrame | None:
        """
        获取 path 对应的 DataFrame。如果已缓存则更新 last_access 并返回。
        若未缓存则调用 reader(path) 加载（默认 pd.read_parquet）。

        namespace: 资源类型（如 'roller_info'）
        path:      文件路径
        ttl:       空闲超时秒数
        reader:    可选，自定义加载函数 f(path) -> DataFrame
        """
        key = (namespace, path)
        with self._cache_lock:
            entry = self._cache.get(key)
            if entry is not None:
                entry['last_access'] = time.time()
                return entry['data']
            # 未缓存，立刻加载
            loader = reader or (lambda p: pd.read_parquet(p))
            data = loader(path)
            self._cache[key] = {
                'data': data,
                'last_access': time.time(),
                'ttl': ttl,
            }
            return data

    def touch(self, namespace: str, path: str):
        """仅更新 last_access，不加载数据（用于已有缓存的情况）。"""
        key = (namespace, path)
        with self._cache_lock:
            entry = self._cache.get(key)
            if entry is not None:
                entry['last_access'] = time.time()

    def _scan_loop(self):
        while self._running:
            time.sleep(self._scan_interval)
            self._cleanup()

    def _cleanup(self):
        now = time.time()
        with self._cache_lock:
            expired = [
                key for key, entry in self._cache.items()
                if now - entry['last_access'] > entry['ttl']
            ]
            for key in expired:
                del self._cache[key]
