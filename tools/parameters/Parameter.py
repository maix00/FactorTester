import pandas as pd
from typing import TYPE_CHECKING, Callable, List, Optional, Any, Literal

from tools import UniqueObject, SerialObject

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
            self._registry = {}
            self.whether_in_space = whether_in_space
            self.default_value = default_value
            self.check_in_space(self.default_value)
            self.rectify_value = self._rectify_value
            self.default_value = self.rectify_value(self.default_value)
            self.get_value_alias = lambda x: get_value_alias(x) if self.check_in_space(x) else ''

    def _rectify_value(self, value: Any, **kwargs) -> Any:
        return value
    
    def __contains__(self, value: Any) -> bool:
        return self.check_in_space(value, error=False)

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
        from tools import UniqueObject
    
    def register(self, object: UniqueObject, value: Any, **kwargs) -> None:
        self.check_in_space(value)
        self._registry[(object, type(object).__name__)] = self.rectify_value(value, **kwargs)

    def unregister(self, object: UniqueObject) -> None:
        if (object, type(object).__name__) in self._registry:
            del self._registry[(object, type(object).__name__)]

    def get_value(self, object: UniqueObject) -> Any:
        return self._registry.get((object, type(object).__name__), self.default_value)

class TypeParam(Parameter):
    def __init__(self, alias: Optional[str] = None, default_value: Any = None, type_: Optional[type] = None, *args, **kwargs):
        type_ = type_ if type_ is not None else type(default_value)
        if not hasattr(self, '_initialized'):
            __whether_in_space = kwargs.pop('whether_in_space', None)
            _whether_in_space = lambda x: isinstance(x, type_) and (__whether_in_space(x) if __whether_in_space else True)
            super().__init__(
                alias = alias,
                default_value = default_value,
                whether_in_space = _whether_in_space,
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
