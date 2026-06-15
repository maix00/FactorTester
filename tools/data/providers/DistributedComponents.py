# =============================================================================
# tools/base/DistributedComponents.py
# 分布式数据组件抽象接口 + 默认本地实现
#
# 为 DataProviderProductTS 预留分布式扩展点：
#   - PathResolver: 将 (DataProviderProductTS, Product) 映射到存储路径
#
# 默认本地实现（LocalPathResolver）完全兼容现有行为；
# 分布式部署时替换为 Redis / RPC / S3 实现即可，上层代码零改动。
# =============================================================================
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Callable


# ---------------------------------------------------------------------------
# PathResolver — 路径解析抽象
# ---------------------------------------------------------------------------


class PathResolver(ABC):
    """将 (DataSource, Product) 映射到存储路径的解析器。"""

    @abstractmethod
    def get_path(self, data_source: Any, obj: Any) -> str:
        """返回给定 data_source 和 product 的数据文件路径。"""
        ...


class LocalPathResolver(PathResolver):
    """默认本地实现：委托给创建时传入的 get_object_path 回调。"""

    def __init__(self, get_object_path_callable: Callable[[Any], str]) -> None:
        self._get_path = get_object_path_callable

    def get_path(self, data_source: Any, obj: Any) -> str:
        return self._get_path(obj)
