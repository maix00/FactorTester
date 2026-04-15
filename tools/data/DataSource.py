from abc import ABCMeta
from weakref import WeakValueDictionary
from typing import Any, Callable, Dict, List, Optional

import sys; from pathlib import Path; sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from tools.base.UniqueObject import UniqueObject
from tools.base.SerialObject import SerialObject
from tools.data.DataColumn import DataColumn
from tools.data.DataFreq import DataFreq

class DataSourceMeta(ABCMeta):
    """元类，同时作为 DataSource 的注册表"""
    _data_sources = WeakValueDictionary()  # 存储所有 DataSource 实例，键为 alias

    def __iter__(cls):
        return iter(cls._data_sources.values())

    def __contains__(cls, item):
        return item in cls._data_sources.values()

    def __getitem__(cls, name: str):
        return cls._data_sources[name]

    def _register_source(cls, source: 'DataSource') -> 'DataSource':
        if source.alias not in cls._data_sources:
            cls._data_sources[source.alias] = source
        return source

    def get_default_source(cls) -> 'DataSource':
        return cls.default_source

    def set_default_source(cls, source: 'DataSource') -> 'DataSource':
        cls.default_source = source
        return source

class DataSource(SerialObject, metaclass=DataSourceMeta):
    _instances = WeakValueDictionary()
    default_source: 'DataSource'

    def __new__(cls, alias: str, *args, **kwargs):
        return super().__new__(cls, type_alias='DS', alias=alias)

    def __init__(self, alias: str, data_freq: Any,
                 get_object_path: Callable[[UniqueObject], Any],
                 if_object_is_in_source: Optional[Callable[[UniqueObject], bool]] = None, *args, **kwargs):
        if not hasattr(self, '_initialized'):
            self.freq = DataFreq(data_freq)
            alias =  self.freq.name + '@' + alias
            super().__init__(type_alias='DS', alias=alias)
            if not DataSource.all():
                DataSource.set_default_source(self)
            DataSource._register_source(self)
            self._get_object_path_func = get_object_path
            if if_object_is_in_source is None:
                import os
                self._is_object_in_source_func = lambda object: os.path.isfile(get_object_path(object))
            else:
                self._is_object_in_source_func = if_object_is_in_source
            self.timezone = kwargs.get('timezone', None)
            self.set_time_cols_mapping(kwargs.get('time_cols_mapping', {}))
            self.set_data_cols_mapping(kwargs.get('data_cols_mapping', {}))

    def if_object_is_in_source(self, object: UniqueObject) -> bool:
        if hasattr(object, 'timezone') and getattr(object, 'timezone') != self.timezone:
            return False
        return self._is_object_in_source_func(object)

    def get_object_path(self, object: UniqueObject) -> Any:
        return self._get_object_path_func(object)
    
    def set_time_cols_mapping(self, mapping: Dict[Any, Any]) -> None:
        self.time_cols_mapping = {k: DataFreq(v).name for k, v in mapping.items()}

    def set_data_cols_mapping(self, mapping: Dict[Any, Any]) -> None:
        self.data_cols_mapping = {k: DataColumn(v).name for k, v in mapping.items()}

    @classmethod
    def all(cls):
        return list(cls._data_sources.values())
    
    def delete(self):
        DataSourceMeta._data_sources.pop(self.alias, None)
        super().delete()

if __name__ == '__main__':
    ds1 = DataSource('source1', data_freq='1D', get_object_path=lambda _: None)
    print(ds1)
    ds = DataSource.get_default_source()
    print(ds)