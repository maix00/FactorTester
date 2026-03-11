from typing import Callable, List, Dict, Optional, Sequence, Set, Tuple, Any, Literal
import pandas as pd

from Tools import SerialObject, _process_data_freq
from Products import DataColumn
from typing import TYPE_CHECKING

class Parameter(SerialObject):
    _instance_count: int = -1
    _serial_map = {}

    def __new__ (cls, alias: Optional[str] = None, *args, **kwargs):
        return super().__new__(cls, type_alias='P', alias=alias)

    def __init__(self, alias: Optional[str], default_value: Any,
                 whether_in_space: Callable[[Any], bool],
                 get_value_alias: Callable[[Any], str]):
        if not hasattr(self, '_initialized'):
            super().__init__(type_alias='P', alias=alias)
            self._register = {}
            self.whether_in_space = whether_in_space
            self.default_value = default_value
            self.check_in_space(self.default_value)
            self.rectify_value = self._rectify_value
            self.default_value = self.rectify_value(self.default_value)
            self.get_value_alias = lambda x: get_value_alias(x) if self.check_in_space(x) else ''

    def _rectify_value(self, value: Any) -> Any:
        return value

    def check_in_space(self, value: Any, error: bool = True) -> bool:
        check = self.whether_in_space(value)
        if not check and error:
            raise ValueError(f"{value} is not in the value space")
        return check

    def change_default_value(self, value: Any) -> Parameter:
        self.check_in_space(value)
        self.default_value = self.rectify_value(value)
        return self
    
    def __iadd__(self, other):
        if isinstance(other, Parameter):
            old_whether = self.whether_in_space
            old_get_alias = self.get_value_alias
            other_whether = other.whether_in_space
            other_get_alias = other.get_value_alias
            old_rectify = self.rectify_value
            other_rectify = other.rectify_value
            self.whether_in_space = lambda x: old_whether(x) or other_whether(x)
            self.get_value_alias = lambda x: old_get_alias(x) if old_whether(x) else other_get_alias(x)
            self.rectify_value = lambda x: old_rectify(x) if old_whether(x) else other_rectify(x)
            return self
        return NotImplemented
    
    def __add__(self, other):
        if isinstance(other, Parameter):
            old_whether = self.whether_in_space
            old_get_alias = self.get_value_alias
            other_whether = other.whether_in_space
            other_get_alias = other.get_value_alias
            old_rectify = self.rectify_value
            other_rectify = other.rectify_value
            new_param = Parameter(
                alias = self.alias,
                default_value = self.default_value,
                whether_in_space = lambda x: old_whether(x) or other_whether(x),
                get_value_alias = lambda x: old_get_alias(x) if old_whether(x) else other_get_alias(x)
            )
            new_param.rectify_value = lambda x: old_rectify(x) if old_whether(x) else other_rectify(x)
            return new_param
        return NotImplemented
    
    def __isub__(self, other):
        if isinstance(other, Parameter):
            old_whether = self.whether_in_space
            old_get_alias = self.get_value_alias
            other_whether = other.whether_in_space
            other_get_alias = other.get_value_alias
            self.whether_in_space = lambda x: old_whether(x) and not other_whether(x)
            self.get_value_alias = lambda x: old_get_alias(x) if old_whether(x) and not other_whether(x) else (other_get_alias(x) if other_whether(x) and not old_whether(x) else '')
            return self
        return NotImplemented
    
    def __sub__(self, other):
        if isinstance(other, Parameter):
            old_whether = self.whether_in_space
            old_get_alias = self.get_value_alias
            other_whether = other.whether_in_space
            other_get_alias = other.get_value_alias
            new_param = Parameter(
                alias = self.alias,
                default_value = self.default_value,
                whether_in_space = lambda x: old_whether(x) and not other_whether(x),
                get_value_alias = lambda x: old_get_alias(x) if old_whether(x) and not other_whether(x) else (other_get_alias(x) if other_whether(x) and not old_whether(x) else '')
            )
            new_param.rectify_value = self.rectify_value
            return new_param
        return NotImplemented
    
    if TYPE_CHECKING:
        from Factor import Factor
    
    def register(self, factor: Factor, value: Any) -> None:
        self.check_in_space(value)
        self._register[factor] = self.rectify_value(value)

    def change_value(self, factor: Factor, value: Any) -> None:
        self.check_in_space(value)
        self._register[factor] = self.rectify_value(value)

    def get_value(self, factor: Factor) -> Any:
        return self._register.get(factor, self.default_value)
    
if __name__ == '__main__':
    param1 = Parameter(alias='P1', default_value=1, whether_in_space=lambda x: isinstance(x, int) and 0 <= x <= 10, get_value_alias=lambda x: f"{x}")
    param2 = Parameter(alias='P2', default_value=5, whether_in_space=lambda x: isinstance(x, int) and 5 <= x <= 15, get_value_alias=lambda x: f"{x}")
    combined_param = param1 + param2
    minus_param = param1 - param2
    print(combined_param.whether_in_space(3))  # True
    print(combined_param.whether_in_space(8))  # True
    print(combined_param.whether_in_space(12)) # True
    print(minus_param.whether_in_space(3))     # True
    print(minus_param.whether_in_space(8))     # False
    print(minus_param.whether_in_space(12))    # False
    
class FinRangeParam(Parameter):
    def __init__(self, alias: Optional[str], 
                 value_space: List[Any]|Any, 
                 default_value: Optional[Any] = None,
                 get_value_alias: Optional[Callable[[Any], str]] = None):
        if not hasattr(self, '_initialized'):
            if not isinstance(value_space, list):
                value_space = [value_space]
            super().__init__(
                alias = alias,
                default_value = default_value if default_value is not None else value_space[0],
                whether_in_space = lambda x: x in value_space,
                get_value_alias = get_value_alias if get_value_alias else lambda x: str(x)
            )
            self.value_space = value_space

class DataColumnParam(FinRangeParam):
    def __init__(self, alias: Optional[str], default_value: Optional[Any] = None):
        from Tools import _process_data_col
        if default_value is not None:
            default_value = _process_data_col(default_value)
        else:
            try:
                from itertools import takewhile
                result = ''.join(takewhile(str.isalpha, alias)) if alias else ''
                default_value = _process_data_col(result.upper()) if alias else None
            except:
                pass
        if not hasattr(self, '_initialized'):
            super().__init__(
                alias = alias,
                value_space = [col for col in DataColumn],
                default_value=default_value,
                get_value_alias = lambda x: {col: col.value for col in DataColumn}.get(x, str(x))
            )
        else:
            self.default_value = default_value
    
    def col(self, col: Any):
        from Tools import _process_data_col
        col = _process_data_col(col)
        return self.get_value_alias(col)

if __name__ == '__main__':
    C1 = DataColumnParam('C1')
    print(C1.col(DataColumn.CLOSE))

class TimeDeltaParam(Parameter):
    def __init__(self, alias: Optional[str] = None, default_value: Optional[Any] = None,
                 flag: Optional[Literal['pos', 'neg', 'nonneg', 'nonpos']] = None):
        if not hasattr(self, '_initialized'):
            if default_value is None:
                default_value = pd.Timedelta('1d')
            self.flag = flag
            super().__init__(
                alias = alias,
                default_value = default_value,
                whether_in_space = self._whether_in_space,
                get_value_alias = self._get_value_alias
            )

    def _rectify_value(self, value: Any) -> Any:
        if self.check_in_space(value):
            return pd.Timedelta(value)

    def _whether_in_space(self, value: Any) -> bool:
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
    param = FinRangeParam(alias, None, get_value_alias=lambda _: 'N')
    param += TimeDeltaParam(flag='pos')
    return param
    
if __name__ == '__main__':
    ReturnFreq = get_return_freq_param()
    print(ReturnFreq.get_value_alias('2h45m10s11ms'))

class ColumnTimeParam(Parameter):

    def __init__(self, alias: Optional[str] = None, default_value: Optional[Any] = None):

        from Tools import DataFreq

        if not hasattr(self, '_initialized'):
            if default_value is None:
                default_value = (DataFreq.MIN1.name, '2024-01-02 09:00:00')
            super().__init__(
                alias = alias,
                default_value = default_value,
                whether_in_space = self._whether_in_space,
                get_value_alias = self._get_value_alias
            )
            self.default_value = self.rectify_value(self.default_value)

    def _rectify_value(self, value: Any) -> Any:
        if self.check_in_space(value):
            from Tools import _process_data_freq
            return (_process_data_freq(value[0]).name, pd.to_datetime(value[1]))

    def _whether_in_space(self, value: Any) -> bool:
        if not isinstance(value, (list, tuple)):
            return False
        try:
            from Tools import DataFreq, _process_data_freq
            freq = _process_data_freq(value[0])
            time = pd.Timestamp(value[1])  # Check if the second element can be converted to a timestamp
            check = True
            if freq == DataFreq.DAY1 and time.time() != pd.Timestamp('00:00:00').time():
                    check = False
            return check
        except Exception:
            return False
        
    def _get_value_alias(self, value: Any) -> str:
        try:
            from Tools import _process_data_freq
            freq = _process_data_freq(value[0])
            time = pd.Timestamp(value[1])  # Check if the second element can be converted to a timestamp
            return f"{freq.name}: {time}"
        except Exception:
            return str(value)

def get_start_calc_param(alias: Optional[str] = '$SC') -> Parameter:
    return ColumnTimeParam(alias)

if __name__ == '__main__':
    StartCalc = get_start_calc_param()
    print(StartCalc.get_value_alias(('1d', '2024-01-02')))
    print(StartCalc.get_value_alias(StartCalc.default_value))