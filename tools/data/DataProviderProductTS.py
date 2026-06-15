# =============================================================================
# tools/data/DataProviderProductTS.py
# 品种时序数据提供器
#
# 描述一个具体的数据来源（如本地 CSV/Parquet 目录）：
#   - 包含数据频率、文件路径函数、列名映射表、时区等元数据。
#   - 支持判断一个 Product 是否在此数据源中存在实际文件。
#   - 所有实例由 DataSourceMeta 元类维护的全局字典注册。
#   - 路径解析通过 PathResolver 可插拔（默认 LocalPathResolver）。
# =============================================================================
from __future__ import annotations

from abc import ABCMeta
from typing import Any, Callable, Dict, Optional

import sys; from pathlib import Path; sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from tools.base.UniqueObject import UniqueObject
from tools.base.DistributedComponents import PathResolver, LocalPathResolver
from tools.data.DataColumn import DataColumn
from tools.data.DataFreq import DataFreq

class _DataMultipleProviderMeta(ABCMeta):
    """
    数据多提供器元类 — 可为任意子类提供全局注册表。

    任一使用本元类的子类自动获得：
      - for ds in SubClass          遍历所有已注册的实例
      - ds in SubClass              判断某个实例是否已注册
      - SubClass['alias']           按别名查找
      - 默认实例管理：第一个被创建的实例自动成为默认

    不硬编码任何子类名；所有引用通过 cls 动态解析。
    """
    # 按子类隔离注册表，避免不同子类同名 alias 冲突。
    _sources_registry: Dict[type, Dict[str, Any]] = {}
    _default_sources: Dict[type, Any] = {}

    def _ensure_registry(cls):
        """为当前子类懒初始化独立注册表。"""
        if cls not in cls._sources_registry:
            cls._sources_registry[cls] = {}
        return cls._sources_registry[cls]

    def __iter__(cls):
        """for item in cls 语法支持。"""
        return iter(cls._ensure_registry().values())

    def __contains__(cls, item):
        """in 运算符支持。"""
        return item in cls._ensure_registry().values()

    def __getitem__(cls, name: str):
        """cls['alias'] 下标语法。"""
        return cls._ensure_registry()[name]

    def _register_source(cls, source):
        """将源注册到当前子类的独立字典中（若未重复注册）。"""
        reg = cls._ensure_registry()
        if source.alias not in reg:
            reg[source.alias] = source
        return source

    def get_default_source(cls):
        """获取当前子类的默认数据源。"""
        return cls._default_sources.get(cls)

    def set_default_source(cls, source):
        """设置当前子类的默认数据源。"""
        cls._default_sources[cls] = source
        return source

class DataProviderProductTS(UniqueObject, metaclass=_DataMultipleProviderMeta):
    """
    品种时序数据提供器。

    描述一个具体的数据来源，主要把 Product 映射到实际文件路径。

    属性：
        alias     (str)         : 数据源唯一识别名
        freq      (DataFreq)    : 本源提供的数据频率，如 MIN1、DAY1
        timezone  (str|None)    : 时区，概与 Product 不匹配则该源对其不可用

    初始化参数：
        alias                 : 数据源别名（唯一标识）
        data_freq             : 数据频率
        get_object_path       : (Product) -> 文件路径 的回调函数
        if_object_is_in_source: (Product) -> bool 的回调，默认检查文件是否存在
        time_cols_mapping     : {csv列名: DataFreq} 映射，将文件中的时间列映射到 DataFreq.name
        data_cols_mapping     : {csv列名: DataColumn} 映射，将文件中的数据列映射到 DataColumn.name
    """

    def __new__(cls, alias: str, *args, **kwargs):
        return super().__new__(cls, alias=alias, **kwargs)

    def __init__(self, alias: str, data_freq: Any,
                 get_object_path: Optional[Callable[[UniqueObject], Any]] = None,
                 path_resolver: Optional[PathResolver] = None,
                 if_object_is_in_source: Optional[Callable[[UniqueObject], bool]] = None, *args, **kwargs):
        if not hasattr(self, '_initialized'):
            super().__init__(alias=alias)
            self.alias = alias
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
                self._if_object_is_in_source_func = lambda object: os.path.isfile(self.get_path(object))
            else:
                self._if_object_is_in_source_func = if_object_is_in_source
            self.timezone = kwargs.get('timezone', None)
            self.set_time_cols_mapping(kwargs.get('time_cols_mapping', {}))
            self.set_data_cols_mapping(kwargs.get('data_cols_mapping', {}))


    # ── 路径委托 ──
    def get_path(self, obj: UniqueObject) -> str:
        """通过内部 PathResolver 获取对象路径。"""
        return self._path_resolver.get_path(self, obj)

    def __contains__(self, object: UniqueObject) -> bool:
        """
        支持 object in data_source 语法，判断某个 Product 是否在此数据源中存在实际数据。
        必须时区匹配（如 Product.timezone == DataProviderProductTS.timezone）。
        """
        if hasattr(object, 'timezone') and getattr(object, 'timezone') != self.timezone:
            return False
        return self._if_object_is_in_source_func(object)
    
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
        _DataMultipleProviderMeta._ensure_registry(type(self)).pop(self.alias, None)
        super().delete()

if __name__ == '__main__':
    ds1 = DataProviderProductTS('source1', data_freq='1D', get_object_path=lambda _: None)
    print(ds1)
    ds = DataProviderProductTS.get_default_source()
    print(ds)