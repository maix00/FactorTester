from typing import Callable, List, Dict, Optional, Sequence, Set, Tuple, Any, Literal
import pandas as pd

from UniqueObject import SerialObject
from Products import DataColumn

class Parameter(SerialObject):
    _instance_count: int = -1
    _serial_map = {}

    def __new__ (cls, alias: Optional[str] = None, *args, **kwargs):
        instance = super().__new__(cls, type_alias='P', alias=alias)
        return instance

    def __init__(self, alias: Optional[str], default_value: Any,
                 check_in_space: Callable[[Any], bool],
                 get_value_alias: Callable[[Any], str]):
        if not hasattr(self, '_initialized'):
            super().__init__(type_alias='P', alias=alias)
            self.check_in_space = check_in_space
            self.default_value = default_value
            self.check_in_space(self.default_value)
            self.get_value_alias = lambda x: get_value_alias(x) if self.check_in_space(x) else ValueError

    def set_default_value(self, value: Any) -> Parameter:
        if not self.check_in_space(value):
            raise ValueError(f"Invalid value for parameter {self.alias}: {value}")
        self.default_value = value
        return self
    
    def __iadd__(self, other):
        if isinstance(other, Parameter):
            old_check = self.check_in_space
            old_get_alias = self.get_value_alias
            other_check = other.check_in_space
            other_get_alias = other.get_value_alias
            self.check_in_space = lambda x: old_check(x) or other_check(x)
            self.get_value_alias = lambda x: old_get_alias(x) if old_check(x) else other_get_alias(x)
            return self
        return NotImplemented
    
    def __add__(self, other):
        if isinstance(other, Parameter):
            old_check = self.check_in_space
            old_get_alias = self.get_value_alias
            other_check = other.check_in_space
            other_get_alias = other.get_value_alias
            new_param = Parameter(
                alias = self.alias,
                default_value = self.default_value,
                check_in_space = lambda x: old_check(x) or other_check(x),
                get_value_alias = lambda x: old_get_alias(x) if old_check(x) else other_get_alias(x)
            )
            return new_param
        return NotImplemented
    
class FinRangeParam(Parameter):
    def __init__(self, alias: Optional[str], value_space: List[Any], 
                 get_value_alias: Optional[Callable[[Any], str]] = None):
        if not hasattr(self, '_initialized'):
            super().__init__(
                alias = alias,
                default_value = value_space[0],
                check_in_space = lambda x: x in value_space,
                get_value_alias = get_value_alias if get_value_alias else lambda x: str(x)
            )
            self.value_space = value_space

class DataColumnParam(FinRangeParam):
    def __init__(self, alias: Optional[str]):
        if not hasattr(self, '_initialized'):
            super().__init__(
                alias = alias,
                value_space = [col for col in DataColumn],
                get_value_alias = lambda x: {col: col.value for col in DataColumn}.get(x, str(x))
            )
    
    def col(self, col: DataColumn):
        return self.get_value_alias(col)

if __name__ == '__main__':
    C1 = DataColumnParam('C1')
    print(C1.col(DataColumn.CLOSE))

class TimeParam(Parameter):
    def __init__(self, alias: Optional[str] = None, default_value: Optional[Any] = None,
                 flag: Optional[Literal['pos', 'neg', 'nonneg', 'nonpos']] = None):
        if not hasattr(self, '_initialized'):
            if default_value is None:
                default_value = pd.Timedelta('1d')
            self.flag = flag
            super().__init__(
                alias = alias,
                default_value = default_value,
                check_in_space = self._check_in_space,
                get_value_alias = self._get_value_alias
            )

    def _check_in_space(self, value: Any) -> bool:
        try:
            td = pd.Timedelta(value)
            if self.flag == 'pos':
                return td > pd.Timedelta(0)
            elif self.flag == 'neg':
                return td < pd.Timedelta(0)
            elif self.flag == 'nonneg':
                return td >= pd.Timedelta(0)
            elif self.flag == 'nonpos':
                return td <= pd.Timedelta(0)
            else:
                return True
        except Exception:
            return False

    def _get_value_alias(self, value: Any) -> str:
        try:
            c = pd.Timedelta(value).components
            units = {'days': 'd', 'hours': 'h', 'minutes': 'm', 'seconds': 's', 
                     'milliseconds': 'ms', 'microseconds': 'us', 'nanoseconds': 'ns'}
            return ''.join(f"{v}{units[k]}" for k, v in c._asdict().items() if v > 0) or '0'
        except Exception:
            return str(value)
        
def get_return_freq_param(alias: Optional[str] = '$RF') -> Parameter:
    return FinRangeParam(alias, [None], lambda _: 'N') + TimeParam(flag='pos')
    
if __name__ == '__main__':
    ReturnFreq = get_return_freq_param()
    print(ReturnFreq.get_value_alias('2h45m10s11ms'))
