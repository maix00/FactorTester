# =============================================================================
# tools/parameters/Parameter.py
# 参数系统模块
#
# 提供一套可组合的参数类型体系，用于管理因子族（FactorFamily）的超参数：
#   Parameter     - 基类，通过注册表把「对象→参数值」解耦
#   TypeParam     - 类型约束参数
#   FinRangeParam - 有限枚举集参数
#   TimeDeltaParam- 时间增量参数，支持正/负/非负等约束
#   DataColumnParam- DataColumn 枚举参数
#   WindowParam   - 时间窗口参数（TimeDelta 或正整数）
#   DateOrTimeParam- 日期/时间点参数（用于设置计算起始点）
#
# 参数使用基于注册表（_registry）而非实例属性存值，
# 避免了多因子同时使用同一参数对象时的数据污染。
# =============================================================================
import pandas as pd
from typing import TYPE_CHECKING, Callable, List, Optional, Any, Literal

from tools import UniqueObject, SerialObject

class Parameter(SerialObject):
    """
    参数基类。

    核心设计模式：
      - 参数值不存在参数对象上，而是通过 _registry = {(object, typename): value} 存储
      - 每个 Product / Factor / FactorFamily 可以注册自己的参数值（register）
      - get_value(object) 返回对象的注册值，未注册时返回 default_value
      - 支持 param1 += param2 合并参数空间（联合值域）
      - whether_in_space / rectify_value / get_value_alias 是三个核心 hook

    属性：
        alias          (str)      : 参数别名，在因子名称中显示
        default_value  (Any)      : 未注册时的默认值
        whether_in_space (Callable): 值验证函数
        rectify_value   (Callable): 值标准化函数（如字符串→Timedelta）
        get_value_alias (Callable): 将值转换为可读展示字符串
    """
    def __new__ (cls, alias: Optional[str] = None, *args, **kwargs):
        type_alias = kwargs.pop('type_alias', 'P')
        return super().__new__(cls, type_alias=type_alias, alias=alias, **kwargs)

    def __init__(self, alias: Optional[str], default_value: Any,
                 whether_in_space: Callable[[Any], bool],
                 get_value_alias: Callable[[Any], str], *args, **kwargs):
        if not hasattr(self, '_initialized'):
            type_alias = kwargs.pop('type_alias', 'P')
            super().__init__(type_alias=type_alias, alias=alias, *args, **kwargs)
            self._registry = {}                          # {(object, typename): value} 注册表
            self.whether_in_space = whether_in_space     # 值合法性验证 hook
            self.default_value = default_value
            self.check_in_space(self.default_value)      # 构造时验证默认值合法
            self.rectify_value = self._rectify_value     # 值标准化 hook（子类可重写）
            self.default_value = self.rectify_value(self.default_value)  # 标准化默认值
            self.get_value_alias = lambda x: get_value_alias(x) if self.check_in_space(x) else ''

    def _rectify_value(self, value: Any, **kwargs) -> Any:
        """默认值标准化：原样返回。子类（如 TimeDeltaParam）会重写以执行类型转换。"""
        return value
    
    def __contains__(self, value: Any) -> bool:
        """支持 value in param 语法判断值是否在合法范围内。"""
        return self.check_in_space(value, error=False)

    def check_in_space(self, value: Any, error: bool = True) -> bool:
        """验证值是否合法。error=True 时不合法则抛出 ValueError。"""
        check = self.whether_in_space(value)
        if not check and error:
            raise ValueError(f"{value} is not in the value space")
        return check

    def change_default_value(self, value: Any, **kwargs) -> 'Parameter':
        """更改默认值（需通过合法性验证）。"""
        self.check_in_space(value)
        self.default_value = self.rectify_value(value, **kwargs)
        return self
    
    def __iadd__(self, other):
        """
        param1 += param2：原地扩展值域（联合两个参数的合法值集合）。
        合并后 get_value_alias 和 rectify_value 按原有顺序分支处理。
        """
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
        """
        param1 + param2：创建新参数，值域为两者并集，其余属性沿用 self。
        用于临时组合而不修改原参数。
        """
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
        """
        param1 -= param2：原地收缩值域（从合法集合中排除 param2 的值域）。
        """
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
        """
        为指定对象注册参数值。
        注册后 get_value(object) 将返回此值而非默认值。
        """
        self.check_in_space(value)
        self._registry[(object, type(object).__name__)] = self.rectify_value(value, **kwargs)

    def unregister(self, object: UniqueObject) -> None:
        """取消指定对象的参数注册，get_value 将回退到默认值。"""
        if (object, type(object).__name__) in self._registry:
            del self._registry[(object, type(object).__name__)]

    def get_value(self, object: UniqueObject) -> Any:
        """
        获取指定对象的参数值。
        若对象未注册，则返回 default_value。
        """
        return self._registry.get((object, type(object).__name__), self.default_value)

class TypeParam(Parameter):
    """
    类型约束参数：只接受指定 Python 类型的值。
    示例：TypeParam('S', default_value=1) 只接受 int。
    """
    def __init__(self, alias: Optional[str] = None, default_value: Any = None, type_: Optional[type] = None, *args, **kwargs):
        type_ = type_ if type_ is not None else type(default_value)
        if not hasattr(self, '_initialized'):
            l = kwargs.pop('whether_in_space', None)
            _whether_in_space = (lambda x: isinstance(x, type_)) if l is None else l
            super().__init__(
                alias = alias,
                default_value = default_value,
                whether_in_space = _whether_in_space,
                get_value_alias = kwargs.pop('get_value_alias', lambda x: str(x)),
                *args, **kwargs
            )

class FinRangeParam(Parameter):
    """
    有限枚举集参数：只接受给定列表中的值。
    示例：FinRangeParam('SC', ['open', 'close'])
    """
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
    """
    时间增量参数：接受可转换为 pd.Timedelta 的值，支持正/负/非负/非正约束。
    示例：TimeDeltaParam('RF', flag='pos', default_value='1d') 只接受正时长。
    值标准化为 pd.Timedelta；get_value_alias 生成紧凑字符串如 '1d'、'30m'。
    """
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
        """将输入值标准化为 pd.Timedelta 对象。"""       
        if self.check_in_space(value):
            return pd.Timedelta(value)

    def _whether_in_space(self, value: Any) -> bool:
        """
        验证 value 可转换为 Timedelta 且满足符号约束（flag）。
        flag: 'pos'(正) / 'neg'(负) / 'nonneg'(非负) / 'nonpos'(非正) / None(任意)
        """
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
        """
        生成紧凑的时间增量展示字符串。
        示例：pd.Timedelta('1day') → '1d'，pd.Timedelta('30min') → '30m'
        """
        try:
            c = pd.Timedelta(value).components
            units = {'days': 'd', 'hours': 'h', 'minutes': 'm', 'seconds': 's', 
                     'milliseconds': 'ms', 'microseconds': 'us', 'nanoseconds': 'ns'}
            return ''.join(f"{v}{units[k]}" for k, v in c._asdict().items() if v > 0) or '0'
        except Exception:
            return str(value)
