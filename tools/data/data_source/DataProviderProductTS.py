# =============================================================================
# tools/data/data_source/DataProviderProductTS.py
# 品种时序数据提供器
#
# 描述一个具体的数据来源（如本地 CSV/Parquet 目录）：
#   - 包含数据频率、文件路径函数、列名映射表、时区等元数据。
#   - 支持判断一个 Product 是否在此数据源中存在实际文件。
#   - 所有实例由 _DataMultipleProviderMeta 元类维护的按子类注册表。
#   - 路径解析通过 PathResolver 可插拔（默认 LocalPathResolver）。
#
# 继承链：DataProvider（key/label/ensure_schema）+ _DataMultipleProviderMeta（注册表）
# =============================================================================
from __future__ import annotations

from typing import Any, Callable, Dict, Optional

import sys; from pathlib import Path; sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
from tools.base.DistributedComponents import PathResolver, LocalPathResolver
from tools.data.DataColumn import DataColumn
from tools.data.DataFreq import DataFreq
from tools.data.data_source.DataProvider import DataProvider, _DataMultipleProviderMeta


class DataProviderProductTS(DataProvider, metaclass=_DataMultipleProviderMeta):
    """
    品种时序数据提供器。

    描述一个具体的数据来源，主要把 Product 映射到实际文件路径。

    属性：
        key       (str)         : 数据源唯一识别名（继承自 DataProvider，等价于旧 alias）
        freq      (DataFreq)    : 本源提供的数据频率，如 MIN1、DAY1
        timezone  (str|None)    : 时区，概与 Product 不匹配则该源对其不可用

    初始化参数：
        key                   : 数据源唯一标识
        data_freq             : 数据频率
        get_object_path       : (Product) -> 文件路径 的回调函数
        if_object_is_in_source: (Product) -> bool 的回调，默认检查文件是否存在
        time_cols_mapping     : {csv列名: DataFreq} 映射，将文件中的时间列映射到 DataFreq.name
        data_cols_mapping     : {csv列名: DataColumn} 映射，将文件中的数据列映射到 DataColumn.name
    """

    def __init__(self, key: str, data_freq: Any,
                 get_object_path: Optional[Callable[[Any], Any]] = None,
                 path_resolver: Optional[PathResolver] = None,
                 if_object_is_in_source: Optional[Callable[[Any], bool]] = None,
                 label: Optional[str] = None, *args, **kwargs):
        if not hasattr(self, '_initialized'):
            super().__init__(key=key, label=label or key)
            self.freq = DataFreq(data_freq)    # 数据频率对象
            # 第一个被创建的源自动成为默认源
            if not DataProviderProductTS.all():
                DataProviderProductTS.set_default_source(self)
            DataProviderProductTS._register_source(self)  # 注册到元类管理的字典

            # ── 路径解析（可插拔） ──
            if path_resolver is not None:
                self._path_resolver: PathResolver = path_resolver
            elif get_object_path is not None:
                self._path_resolver = LocalPathResolver(get_object_path)
            else:
                raise ValueError("Either get_object_path or path_resolver must be provided")

            # 如果未提供可用性检测函数，默认检查文件是否存在且非空
            if if_object_is_in_source is None:
                import os
                self._if_object_is_in_source_func = lambda obj: os.path.isfile(self.get_path(obj))
            else:
                self._if_object_is_in_source_func = if_object_is_in_source
            self.timezone = kwargs.get('timezone', None)
            self.set_time_cols_mapping(kwargs.get('time_cols_mapping', {}))
            self.set_data_cols_mapping(kwargs.get('data_cols_mapping', {}))


    # ── 路径委托 ──
    def get_path(self, obj: Any) -> str:
        """通过内部 PathResolver 获取对象路径。"""
        return self._path_resolver.get_path(self, obj)

    def __contains__(self, obj: Any) -> bool:
        """
        支持 obj in data_source 语法，判断某个 Product 是否在此数据源中存在实际数据。
        必须时区匹配（如 Product.timezone == DataProviderProductTS.timezone）。
        """
        if hasattr(obj, 'timezone') and getattr(obj, 'timezone') != self.timezone:
            return False
        return self._if_object_is_in_source_func(obj)
    
    def set_time_cols_mapping(self, mapping: Dict[Any, Any]) -> None:
        """设置时间列映射：将数据文件内的时间列名映射到 DataFreq.name，将被用于构建多级索引。"""
        self.time_cols_mapping = {k: DataFreq(v).name for k, v in mapping.items()}

    def set_data_cols_mapping(self, mapping: Dict[Any, Any]) -> None:
        """设置数据列映射：将数据文件内的列名映射到 DataColumn.name。"""
        self.data_cols_mapping = {k: DataColumn(v).name for k, v in mapping.items()}

    @classmethod
    def all(cls):
        """返回已注册的所有实例列表。"""
        return list(cls._ensure_registry().values())

    def delete(self):
        """删除本数据源并从注册表中移除。"""
        type(self)._ensure_registry().pop(self.key, None)

if __name__ == '__main__':
    ds1 = DataProviderProductTS('source1', data_freq='1D', get_object_path=lambda _: None)
    print(ds1)
    ds = DataProviderProductTS.get_default_source()
    print(ds)