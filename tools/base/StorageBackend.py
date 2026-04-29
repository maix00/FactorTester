"""
统一存储后端接口 + 本地实现 + Redis 实现（带断路器熔断回退）

设计思路：
  - StorageBackend: 抽象接口，上层只依赖此接口
  - LocalStorageBackend: 线程安全的单机实现，始终可用
  - RedisStorageBackend: 分布式实现，搭配 pybreaker 在 Redis 不可用时
    自动熔断并回退到 LocalStorageBackend

用法：
    from tools.base.StorageBackend import LocalStorageBackend, RedisStorageBackend

    backend = LocalStorageBackend()
    # 或
    import redis
    backend = RedisStorageBackend(redis.Redis(...), LocalStorageBackend())

    UniqueObject.set_backend(backend)
"""
import threading
from abc import ABC, abstractmethod
from typing import Any, Optional
from collections import defaultdict

# =============================================================================
# 抽象接口
# =============================================================================


class StorageBackend(ABC):
    """
    可动态切换的存储后端抽象接口。

    设计原则：后端只做"存在性协调"，value 统一存 "1"（仅作为存在标记）。
    对象始终由各进程的本地 WeakValueDictionary 管理生命周期。

    set_if_absent 对应 Redis SETNX —— 原子创建，消除 get-then-set 的 race condition。

    用法：
        backend = LocalStorageBackend()  # 单机
        # 或
        backend = RedisStorageBackend(redis_client, LocalStorageBackend())  # 分布式
        UniqueObject.set_backend(backend)
    """

    @abstractmethod
    def exists(self, key: str) -> bool:
        """检查 key 是否已存在（存在性协调）。"""
        ...

    @abstractmethod
    def set_if_absent(self, key: str) -> bool:
        """
        原子创建：仅在 key 不存在时设置。返回 True 表示创建成功。
        对应 Redis SET key 1 NX 语义。
        """
        ...

    @abstractmethod
    def delete(self, key: str) -> bool:
        """删除 key。成功返回 True。"""
        ...

    @abstractmethod
    def register_atomic_counter(self, counter_key: str) -> bool:
        """确保原子计数器的 key 已注册。"""
        ...

    @abstractmethod
    def get_next_sequence(self, counter_key: str) -> int:
        """获取并递增原子计数器。必须保证线程/进程安全。"""
        ...


# =============================================================================
# 本地实现
# =============================================================================


class LocalStorageBackend(StorageBackend):
    """线程安全的本地内存存储（单机兜底方案）。value 统一存 "1" 作为存在标记。"""

    def __init__(self):
        self._data: set[str] = set()
        self._counters: dict[str, int] = defaultdict(int)
        self._lock = threading.Lock()

    def exists(self, key: str) -> bool:
        with self._lock:
            return key in self._data

    def set_if_absent(self, key: str) -> bool:
        with self._lock:
            if key in self._data:
                return False
            self._data.add(key)
            return True

    def delete(self, key: str) -> bool:
        with self._lock:
            if key in self._data:
                self._data.discard(key)
                return True
            return False

    def register_atomic_counter(self, counter_key: str) -> bool:
        return True

    def get_next_sequence(self, counter_key: str) -> int:
        with self._lock:
            self._counters[counter_key] += 1
            return self._counters[counter_key]


# ─────────────────────────────────────────────────────────────────────────────
# 分布式参考实现：Redis + pybreaker 断路器（依赖：pip install redis pybreaker）
#
# 关键原则：Redis 只做"存在性协调"，value 统一存 "1"，不存 Python 对象。
# exists / set_if_absent 对应 Redis EXISTS / SETNX，消除 race condition。
# 对象生命周期由各进程本地的 UniqueObject._instances（WeakValueDictionary）管理。
# 实际使用时取消注释即可，无需修改上层业务代码。
# ─────────────────────────────────────────────────────────────────────────────
#
# import redis
# import pybreaker
#
# class RedisConnectionError(Exception):
#     """Redis 连接异常，用于触发熔断。"""
#     pass
#
# class RedisStorageBackend(StorageBackend):
#     """
#     Redis 分布式存储后端（协调层）。
#
#     内置 pybreaker 断路器：连续失败 fail_max 次后打开熔断器，
#     在 reset_timeout 秒内所有请求直接走 local_fallback 兜底。
#     """
#
#     def __init__(
#         self,
#         redis_client: 'redis.Redis',
#         local_fallback: StorageBackend,
#         fail_max: int = 3,
#         reset_timeout: int = 10,
#     ):
#         self.redis = redis_client
#         self.local_fallback = local_fallback
#         self._breaker = pybreaker.CircuitBreaker(
#             fail_max=fail_max, reset_timeout=reset_timeout,
#         )
#         self._seq_breaker = pybreaker.CircuitBreaker(
#             fail_max=fail_max, reset_timeout=reset_timeout,
#             fallback_function=self._fallback_get_next_sequence,
#         )
#
#     # ── 存在性协调（SETNX 原子语义，value = "1"） ──
#
#     def exists(self, key: str) -> bool:
#         try:
#             return self._breaker.call(self._do_exists, key)
#         except pybreaker.CircuitBreakerError:
#             return self.local_fallback.exists(key)
#
#     def _do_exists(self, key: str) -> bool:
#         try:
#             return bool(self.redis.exists(key))
#         except redis.exceptions.ConnectionError as e:
#             raise RedisConnectionError from e
#
#     def set_if_absent(self, key: str) -> bool:
#         try:
#             return self._breaker.call(self._do_set_if_absent, key)
#         except pybreaker.CircuitBreakerError:
#             return self.local_fallback.set_if_absent(key)
#
#     def _do_set_if_absent(self, key: str) -> bool:
#         try:
#             # SET key 1 NX → 原子创建，返回 True 表示创建成功
#             return bool(self.redis.set(key, "1", nx=True))
#         except redis.exceptions.ConnectionError as e:
#             raise RedisConnectionError from e
#
#     def delete(self, key: str) -> bool:
#         try:
#             return self._breaker.call(self._do_delete, key)
#         except pybreaker.CircuitBreakerError:
#             return self.local_fallback.delete(key)
#
#     def _do_delete(self, key: str) -> bool:
#         try:
#             return bool(self.redis.delete(key))
#         except redis.exceptions.ConnectionError as e:
#             raise RedisConnectionError from e
#
#     # ── 原子计数器 ──
#
#     def register_atomic_counter(self, counter_key: str) -> bool:
#         return True
#
#     def get_next_sequence(self, counter_key: str) -> int:
#         return self._seq_breaker.call(self._do_get_next_sequence, counter_key)
#
#     def _do_get_next_sequence(self, counter_key: str) -> int:
#         try:
#             return self.redis.incr(counter_key)
#         except redis.exceptions.ConnectionError as e:
#             raise RedisConnectionError from e
#
#     def _fallback_get_next_sequence(self, counter_key: str) -> int:
#         print(f"[Fallback] Redis breaker OPEN, using local counter for '{counter_key}'.")
#         return self.local_fallback.get_next_sequence(counter_key)
#
# # 用法：
# # from tools.base.StorageBackend import LocalStorageBackend, RedisStorageBackend
# # from tools.base.UniqueObject import UniqueObject
# # UniqueObject.set_backend(
# #     RedisStorageBackend(redis.Redis(...), LocalStorageBackend())
# # )
