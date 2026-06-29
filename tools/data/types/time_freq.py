from __future__ import annotations

# =============================================================================
# tools/data/time_freq.py
# 数据频率类模块
#
# 提供全局唯一的数据频率表示。支持多种输入格式：
#   字符串 '1d'、'30min'、pd.Timedelta 对象、DataFreq 实例本身（原样返回）。
# 内部将时间转化为形如 "DAY1"、"MIN30" 的标准名称，作为唯一标识也用于数据索引列名。
# =============================================================================
import pandas as pd
from abc import ABCMeta
from re import findall
from typing import Any, cast
from weakref import WeakValueDictionary

from .base import UniqueNameObject

# 标准时间单位→简短名称映射（pd.Timedelta.components 属性名 → DataFreq 名称组成单元）
units = {'days': 'DAY', 'hours': 'HOUR', 'minutes': 'MIN', 'seconds': 'SECOND', 
         'milliseconds': 'MILLISECOND', 'microseconds': 'MICROSECOND', 'nanoseconds': 'NANOSECOND'}
# 反向映射：DAY→days 等、用于从 DataFreq 名称字符串解析回 pd.Timedelta
reverse_map = {v: k for k, v in units.items()}

class DataFreqMeta(ABCMeta):
    """
    DataFreq 的元类。

    继承 ABCMeta，影响 DataFreq 的实例管理：
      - 支持 for f in DataFreq 遍历所有已创建的频率实例。
      - 支持 DataFreq.MIN1 属性访问语法（通过 __getattr__ 动态创建）。
    """
    _instances = WeakValueDictionary()  # 全局实例缓存

    def __iter__(cls):
        """for f in DataFreq 语法支持，遍历已知频率实例。"""
        return iter(cls._instances.values())

    def __contains__(cls, item):
        """f in DataFreq 语法支持。"""
        return item in cls._instances.values()
    
    def __getattr__(cls, name) -> DataFreq:
        """
        DataFreq.MIN1 / DataFreq.DAY1 等属性访问：
        如果属性名未在元类中直接定义，用它作为频率字符串创建 DataFreq。
        """
        return DataFreq(name)
    
    @property
    def __members__(cls):
        """Compatible with Enum-like access patterns."""
        return cls._instances
    
class DataFreq(UniqueNameObject, metaclass=DataFreqMeta):
    """
    数据频率类。

    设计为全局唯一实例：相同频率的实例全局共享。支持多种输入格式：
      DataFreq('1d') == DataFreq('DAY1') == DataFreq(pd.Timedelta('1d'))

    内部会将时间转化为形如 "DAY1"、"MIN1"、"MIN30" 的字符串 name，同时将 value
    存为 pd.Timedelta（用于数值比较）。

    属性：
        value (pd.Timedelta) : 频率对应的时间轴步长
        name  (str)          : 内部标准名称，如 "DAY1"、"MIN30"
        alias (str)          : 带前缀的完整名，如 "DataFreq.DAY1"
    """
    _instances = WeakValueDictionary()
    value: pd.Timedelta
    name: str
    alias: str

    def __init__(self, *args, **kwargs):
        """__init__ 被 __new__ 旁路，但声明接受任意参数以避免 TypeError。"""
        pass

    def __new__(cls, freq: Any):
        """
        创建或返回已有 DataFreq 实例。

        支持输入：
          - DataFreq 实例：直接原样返回
          - pd.Timedelta 或可袋封为 Timedelta 的字符串（'1d'、'30min'等）
          - DataFreq 名称字符串（'DAY1'、'MIN30'等）
        """
        if isinstance(freq, DataFreq):
            return freq  # 已是 DataFreq，直接返回
        if isinstance(freq, str) or isinstance(freq, pd.Timedelta):
            try:
                import warnings
                from pandas.errors import Pandas4Warning
                with warnings.catch_warnings():
                    warnings.filterwarnings("ignore", category=Pandas4Warning)
                    # 尝试直接解析为 pd.Timedelta，并转为标准名称
                    value = pd.Timedelta(freq)
                    if not isinstance(value, pd.Timedelta):
                        value = pd.Timedelta(0)
                    if value == pd.Timedelta(0):
                        name = '0'
                    elif value > pd.Timedelta(0):
                        name = ''.join(f"{units[k]}{v}" for k, v in getattr(cast(pd.Timedelta, value), 'components')._asdict().items() if v > 0)
                    else:
                        name = '-' + ''.join(f"{units[k]}{v}" for k, v in getattr(cast(pd.Timedelta, -value), 'components')._asdict().items() if v > 0)
            except:
                # 如果无法直接解析，尝试按 DataFreq 名称格式解析，如 'MIN30' → '30min'
                assert isinstance(freq, str)
                name = freq.removeprefix('DataFreq.').removeprefix('DataFreq:').split('@')[-1].upper()
                # 正则提取单位+数字对，拼接为 Timedelta 可识别字符串
                values = [pd.Timedelta(f"{num}{reverse_map.get(unit, unit)}") for unit, num in findall(r'\-?([A-Z]+)(\d+)', name)]
                value = sum(values, pd.Timedelta(0))
                if name.startswith('-'):
                    value = -value
            finally:
                instance = super().__new__(cls, name=name)
            if not hasattr(instance, '_initialized'):
                # 首次创建时写入属性
                object.__setattr__(instance, 'value', value)
                object.__setattr__(instance, 'name', name)
                object.__setattr__(instance, 'alias', 'DataFreq:' + name)
                object.__setattr__(instance, '_initialized', True)
            return instance
        else:
            raise ValueError("Invalid frequency format")

    @property    
    def days(self) -> int:
        """以天为单位的频率表示(向下取整), 如 90min → 0d, 36h → 1d, -36h → -2d"""
        return self.value.days if self.value >= pd.Timedelta(0) else self.value.days + 1
    
    @property
    def subday(self) -> pd.Timedelta:
        """小于一天的频率部分, 如 90min → 1min, 36h → 12h, -36h → 12h"""
        return cast(pd.Timedelta, self.value - pd.Timedelta(days=self.days))
    
    @property
    def is_multiples_of_day(self) -> bool:
        """判断该频率是否为 整日数倍数（即是 1天的整数倍）。"""
        return self.is_day_multiple()
    
    def is_day_multiple(self) -> bool:
        """
        判断该频率是否为 整日数倍数（即 >= 1天且是 1天的整数倍）。
        正实务应用中用于区分日频信号与分钟频信号的处理逻辑。
        """
        return abs(self.value) >= pd.Timedelta('1day') and self.value.total_seconds() % pd.Timedelta('1day').total_seconds() == 0
    
    def __class_getitem__(cls, key):
        """DataFreq['MIN1'] 下标语法支持。"""
        return DataFreq(key)
    
    @classmethod
    def all(cls):
        """返回所有已创建的 DataFreq 实例列表。"""
        return list(cls._instances.values())
    
if __name__ == '__main__':
    DataFreq.MIN1
    print(DataFreq('-1d3m').days, DataFreq('-1d3m').subday)
