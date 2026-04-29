"""
资源注册表 —— 抽象接口 + 单机实现

职责：记录资源的最后使用时间、查询闲置资源、删除记录。
不负责实际回收逻辑，只维护元数据。
"""
import threading
import time
from abc import ABC, abstractmethod
from typing import Dict, List


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


# ──────────────────────────────────────────────
# 分布式参考实现（多进程 / 多服务器共享）
# 使用时取消注释并传入 IdleResourceManager.set_registry()
# ──────────────────────────────────────────────
#
# import redis
#
# class RedisResourceRegistry(ResourceRegistry):
#     """Redis 版资源注册表 —— 多进程共享。"""
#     def __init__(self, redis_client: redis.Redis, key_prefix: str = "idle_res:"):
#         self._r = redis_client
#         self._prefix = key_prefix
#
#     def _key(self, resource_id: str) -> str:
#         return f"{self._prefix}{resource_id}"
#
#     def record_use(self, resource_id: str) -> None:
#         self._r.set(self._key(resource_id), time.time())
#
#     def get_idle_resources(self, idle_threshold_seconds: float) -> list[str]:
#         now = time.time()
#         idle = []
#         for key_bytes in self._r.scan_iter(match=f"{self._prefix}*"):
#             rid = key_bytes.decode().removeprefix(self._prefix)
#             last_ts = float(self._r.get(key_bytes) or 0)
#             if now - last_ts > idle_threshold_seconds:
#                 idle.append(rid)
#         return idle
#
#     def remove(self, resource_id: str) -> None:
#         self._r.delete(self._key(resource_id))
#
# # 用法：
# # manager = IdleResourceManager.get_instance()
# # manager.set_registry(RedisResourceRegistry(redis_client))
# # manager.start(idle_timeout=10)
