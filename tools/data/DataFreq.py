import pandas as pd
from abc import ABCMeta
from re import findall
from typing import Any
from weakref import WeakValueDictionary

import sys; from pathlib import Path; sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from tools.base.UniqueObject import UniqueObject

units = {'days': 'DAY', 'hours': 'HOUR', 'minutes': 'MIN', 'seconds': 'SECOND', 
         'milliseconds': 'MILLISECOND', 'microseconds': 'MICROSECOND', 'nanoseconds': 'NANOSECOND'}
reverse_map = {v: k for k, v in units.items()}

class DataFreqMeta(ABCMeta):
    _instances = WeakValueDictionary()

    def __iter__(cls):
        return iter(cls._instances.values())

    def __contains__(cls, item):
        return item in cls._instances.values()
    
    def __getattr__(cls, name):
        return DataFreq(name)
    
    @property
    def __members__(cls):
        return cls._instances
    
class DataFreq(UniqueObject, metaclass=DataFreqMeta):
    _instances = WeakValueDictionary()
    value: pd.Timedelta
    name: str
    alias: str

    def __new__(cls, freq: Any):
        if isinstance(freq, DataFreq):
            return freq
        if isinstance(freq, str) or isinstance(freq, pd.Timedelta):
            try:
                value = pd.Timedelta(freq)
                name = ''.join(f"{units[k]}{v}" for k, v in value.components._asdict().items() if v > 0) or '0'
            except:
                assert isinstance(freq, str)
                name = freq.removeprefix('DataFreq.').split('@')[-1].upper()
                value = ''.join(f"{num}{reverse_map.get(unit, unit)}" for unit, num in findall(r'([A-Z]+)(\d+)', name))
                value = pd.Timedelta(value)
            finally:
                instance = super().__new__(cls, name=name)
            if not hasattr(instance, '_initialized'):
                instance.value = value
                instance.name = name
                instance.alias = 'DataFreq.' + name
                instance._initialized = True
            return instance
        else:
            raise ValueError("Invalid frequency format")
            
    def is_day_multiple(self) -> bool:
        return self.value >= pd.Timedelta('1day') and self.value.total_seconds() % pd.Timedelta('1day').total_seconds() == 0
    
    def __class_getitem__(cls, key):
        return DataFreq(key)
    
    @classmethod
    def all(cls):
        return list(cls._instances.values())
    
if __name__ == '__main__':
    DataFreq.MIN1