# =============================================================================
# tools/data/DataSource.py
# 数据源模块
#
# 描述一个具体的数据来源（如本地 CSV/Parquet 目录）：
#   - 包含数据频率、文件路径函数、列名映射表、时区等元数据。
#   - 支持判断一个 Product 是否在此数据源中存在实际文件。
#   - 所有实例由 DataSourceMeta 元类维护的全局字典注册。
# =============================================================================
from abc import ABCMeta
from typing import Any, Callable, Dict, Optional

import sys; from pathlib import Path; sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from tools.base.UniqueObject import UniqueObject
from tools.data.DataColumn import DataColumn
from tools.data.DataFreq import DataFreq

class DataSourceMeta(ABCMeta):
    """
    DataSource 的元类。

    实现了全局 DataSource 注册表，支持：
      - for ds in DataSource  遍历所有已注册的数据源
      - ds in DataSource       判断某个源是否已注册
      - DataSource['alias']    按别名查找
      - 默认数据源管理：第一个被创建的源自动成为默认源
    """
    # 使用强引用注册表，避免 source 在仅有弱引用时被 GC 回收。
    _data_sources: Dict[str, 'DataSource'] = {}  # 全局数据源实例缓存，键为 alias

    def __iter__(cls):
        """for ds in DataSource 语法支持。"""
        return iter(cls._data_sources.values())

    def __contains__(cls, item):
        """in 运算符支持。"""
        return item in cls._data_sources.values()

    def __getitem__(cls, name: str):
        """DataSource['alias'] 下标语法。"""
        return cls._data_sources[name]

    def _register_source(cls, source: 'DataSource') -> 'DataSource':
        """将源注册到全局字典中（若未重复注册）。"""
        if source.alias not in cls._data_sources:
            cls._data_sources[source.alias] = source
        return source

    def get_default_source(cls) -> 'DataSource':
        """获取当前默认数据源。"""
        return cls.default_source

    def set_default_source(cls, source: 'DataSource') -> 'DataSource':
        """设置默认数据源。"""
        cls.default_source = source
        return source

class DataSource(UniqueObject, metaclass=DataSourceMeta):
    """
    数据源。

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
    default_source: 'DataSource'

    def __new__(cls, alias: str, *args, **kwargs):
        return super().__new__(cls, alias=alias, **kwargs)

    def __init__(self, alias: str, data_freq: Any,
                 get_object_path: Callable[[UniqueObject], Any],
                 if_object_is_in_source: Optional[Callable[[UniqueObject], bool]] = None, *args, **kwargs):
        if not hasattr(self, '_initialized'):
            super().__init__(alias=alias)
            self.alias = alias
            self.freq = DataFreq(data_freq)    # 数据频率对象
            # 第一个被创建的源自动成为默认源
            if not DataSource.all():
                DataSource.set_default_source(self)
            DataSource._register_source(self)  # 注册到元类管理的字典
            self.get_object_path = get_object_path
            # 如果未提供可用性检测函数，默认检查文件是否存在且非空
            if if_object_is_in_source is None:
                import os
                self._if_object_is_in_source_func = lambda object: os.path.isfile(self.get_object_path(object))
            else:
                self._if_object_is_in_source_func = if_object_is_in_source
            self.timezone = kwargs.get('timezone', None)
            self.set_time_cols_mapping(kwargs.get('time_cols_mapping', {}))
            self.set_data_cols_mapping(kwargs.get('data_cols_mapping', {}))

    def __contains__(self, object: UniqueObject) -> bool:
        """
        支持 object in data_source 语法，判断某个 Product 是否在此数据源中存在实际数据。
        必须时区匹配（如 Product.timezone == DataSource.timezone）。
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
        """返回已注册的所有 DataSource 实例列表。"""
        return list(cls._data_sources.values())
    
    def delete(self):
        """部除本数据源并从元类字典中移除。"""
        DataSourceMeta._data_sources.pop(self.alias, None)
        super().delete()

if __name__ == '__main__':
    ds1 = DataSource('source1', data_freq='1D', get_object_path=lambda _: None)
    print(ds1)
    ds = DataSource.get_default_source()
    print(ds)