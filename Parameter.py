from typing import Callable, List, Dict, Optional, Sequence, Set, Tuple, Any, Literal
import pandas as pd

from Tools import UniqueObject, _process_data_freq, SerialObject
from Products import DataColumn
from typing import TYPE_CHECKING

class Parameter(SerialObject):
    def __new__ (cls, alias: Optional[str] = None, *args, **kwargs):
        type_alias = kwargs.pop('type_alias', 'P')
        return super().__new__(cls, type_alias=type_alias, alias=alias, **kwargs)

    def __init__(self, alias: Optional[str], default_value: Any,
                 whether_in_space: Callable[[Any], bool],
                 get_value_alias: Callable[[Any], str], *args, **kwargs):
        if not hasattr(self, '_initialized'):
            type_alias = kwargs.pop('type_alias', 'P')
            super().__init__(type_alias=type_alias, alias=alias, *args, **kwargs)
            self._register = {}
            self.whether_in_space = whether_in_space
            self.default_value = default_value
            self.check_in_space(self.default_value)
            self.rectify_value = self._rectify_value
            self.default_value = self.rectify_value(self.default_value)
            self.get_value_alias = lambda x: get_value_alias(x) if self.check_in_space(x) else ''

    def _rectify_value(self, value: Any, **kwargs) -> Any:
        return value

    def check_in_space(self, value: Any, error: bool = True) -> bool:
        check = self.whether_in_space(value)
        if not check and error:
            raise ValueError(f"{value} is not in the value space")
        return check

    def change_default_value(self, value: Any, **kwargs) -> Parameter:
        self.check_in_space(value)
        self.default_value = self.rectify_value(value, **kwargs)
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
            self.rectify_value = lambda x, **kwargs: old_rectify(x, **kwargs) if old_whether(x) else other_rectify(x, **kwargs)
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
            new_param.rectify_value = lambda x, **kwargs: old_rectify(x, **kwargs) if old_whether(x) else other_rectify(x, **kwargs)
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
            new_param.rectify_value = lambda x, **kwargs: self.rectify_value(x, **kwargs)
            return new_param
        return NotImplemented
    
    if TYPE_CHECKING:
        from Tools import UniqueObject
    
    def register(self, object: UniqueObject, value: Any, **kwargs) -> None:
        self.check_in_space(value)
        self._register[(object, type(object).__name__)] = self.rectify_value(value, **kwargs)

    def unregister(self, object: UniqueObject) -> None:
        if (object, type(object).__name__) in self._register:
            del self._register[(object, type(object).__name__)]

    def get_value(self, object: UniqueObject) -> Any:
        return self._register.get((object, type(object).__name__), self.default_value)
    
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

class TypeParam(Parameter):
    def __init__(self, alias: Optional[str] = None, default_value: Any = None, type_: Optional[type] = None, *args, **kwargs):
        type_ = type_ if type_ is not None else type(default_value)
        if not hasattr(self, '_initialized'):
            super().__init__(
                alias = alias,
                default_value = default_value,
                whether_in_space = kwargs.pop('whether_in_space', lambda x: isinstance(x, type_)),
                get_value_alias = kwargs.pop('get_value_alias', lambda x: str(x)),
                *args, **kwargs
            )
    
class FinRangeParam(Parameter):
    def __init__(self, alias: Optional[str] = None, 
                 value_space: List[Any]|Any = None, 
                 default_value: Optional[Any] = None,
                 get_value_alias: Optional[Callable[[Any], str]] = None, *args, **kwargs):
        if not hasattr(self, '_initialized'):
            if not isinstance(value_space, list):
                value_space = [value_space]
            super().__init__(
                alias = alias,
                default_value = default_value if default_value is not None else value_space[0],
                whether_in_space = lambda x: x in value_space,
                get_value_alias = get_value_alias if get_value_alias else lambda x: str(x),
                *args, **kwargs
            )
            self.value_space = value_space

class DataColumnParam(TypeParam):
    def __init__(self, alias: Optional[str] = None, default_value: Optional[Any] = None, *args, **kwargs):
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
                default_value=default_value,
                whether_in_space=self._whether_in_space,
                get_value_alias = lambda x: {col: col.value for col in DataColumn}.get(x, str(x)),
                *args, **kwargs
            )
        else:
            self.default_value = default_value

    def _whether_in_space(self, value: Any) -> bool:
        from Tools import _process_data_col
        try:
            _process_data_col(value)
            return True
        except Exception:
            return False
        
    def _rectify_value(self, value: Any, **kwargs) -> Any:
        from Tools import _process_data_col
        return _process_data_col(value)
    
    def col(self, col: Any):
        from Tools import _process_data_col
        col = _process_data_col(col)
        return self.get_value_alias(col)

if __name__ == '__main__':
    C1 = DataColumnParam('C1')
    print(C1.col(DataColumn.CLOSE))

class TimeDeltaParam(Parameter):
    def __init__(self, alias: Optional[str] = None, default_value: Optional[Any] = None,
                 flag: Optional[Literal['pos', 'neg', 'nonneg', 'nonpos']] = None, *args, **kwargs):
        if not hasattr(self, '_initialized'):
            if default_value is None:
                default_value = pd.Timedelta('1d')
            self.flag = flag
            super().__init__(
                alias = alias,
                default_value = default_value,
                whether_in_space = self._whether_in_space,
                get_value_alias = self._get_value_alias,
                *args, **kwargs
            )

    def _rectify_value(self, value: Any, **kwargs) -> Any:
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
    param += TimeDeltaParam(flag='pos', single_use=True)
    return param

def get_factor_freq_param(alias: Optional[str] = 'F') -> Parameter:
    param = TimeDeltaParam(alias=alias, default_value='1d', flag='pos')
    param += FinRangeParam(alias=None, value_space='S', single_use=True)
    return param
    
if __name__ == '__main__':
    ReturnFreq = get_return_freq_param()
    print(ReturnFreq.get_value_alias('2h45m10s11ms'))

class DateOrTimeParam(Parameter):
    def __init__(self, alias: Optional[str] = None,
                 default_value: Optional[Any] = None, *args, **kwargs):
        if not hasattr(self, '_initialized'):
            if default_value is None:
                default_value = pd.Timestamp('2000-01-01').date()
            super().__init__(
                alias = alias,
                default_value = default_value,
                whether_in_space = self._whether_in_space,
                get_value_alias = self._get_value_alias,
                *args, **kwargs
            )
            self.default_value = self.rectify_value(self.default_value, **kwargs)

    def _rectify_value(self, value: Any, **kwargs) -> Any:
        if self.check_in_space(value):
            import datetime
            isDate = kwargs.get('isDate', None) or type(value) is datetime.date
            isDatetime = kwargs.get('isDatetime', None)
            timezone = kwargs.get('timezone', None)
            value = pd.Timestamp(value, tz=timezone)
            if isDate is not None and isDatetime is not None and isDate and isDatetime:
                raise ValueError(f"DateOrTimeParam {self.name}: Cannot specify both isDate and isDatetime for {value}")
            if isDate is not None and isDate:
                return value.date()
            return value
    
    def _whether_in_space(self, value: Any) -> bool:
        try:
            pd.Timestamp(value)
            return True
        except Exception:
            return False
        
    def _get_value_alias(self, value: Any, **kwargs) -> str:
        return str(self.rectify_value(value, **kwargs))
    
    if TYPE_CHECKING:
        from Tools import UniqueObject
    
    def is_date(self, object: Optional[UniqueObject] = None, value: Optional[Any] = None, **kwargs) -> bool:
        value = self.get_value(object) if object is not None else self.rectify_value(value, **kwargs)
        assert value is not None, "Either object or value must be provided"
        import datetime
        return type(value) is datetime.date
    
    def is_time(self, object: Optional[UniqueObject] = None, value: Optional[Any] = None, **kwargs) -> bool:
        value = self.get_value(object) if object is not None else self.rectify_value(value, **kwargs)
        assert value is not None, "Either object or value must be provided"
        import datetime
        return not type(value) is datetime.date

def get_StartCalcPointParam(alias: Optional[str] = '$SCP', default_value: Optional[Any] = None, **kwargs) -> DateOrTimeParam:
    return DateOrTimeParam(alias, default_value=default_value, **kwargs)

if __name__ == '__main__':
    StartCalcPoint = get_StartCalcPointParam()
    print(StartCalcPoint)
    print(StartCalcPoint.get_value_alias('2024-01-02'))
    print(StartCalcPoint.get_value_alias('2024-01-02 09:30:00'))
    print(StartCalcPoint.check_in_space('2024-01-02 09:90:00', error=False))
    print(StartCalcPoint.is_date(value='2024-01-02'))
    print(StartCalcPoint.is_date(value='2024-01-02', isDate=True))
    print(StartCalcPoint.is_time(value='2024-01-02 09:30:00'))
    print(StartCalcPoint.is_time(value='2024-01-02 09:30:00', isDatetime=True))
    print(StartCalcPoint.is_time(value='2024-01-02', isDate=True))
    print(StartCalcPoint.is_time(value='2024-01-02'))