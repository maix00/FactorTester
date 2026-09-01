# =============================================================================
# tools/parameters/Parameter.py
# 参数系统模块
#
# 提供一套可组合的参数类型体系，用于管理因子族（FactorFamily）的超参数：
#   ValueSpace    - 不可变值空间：定义合法值域、验证、标准化、展示，支持并集/差集
#   Parameter     - 基类，持有 ValueSpace，通过注册表把「对象→参数值」解耦
#   TypeParam     - 类型约束参数
#   FinRangeParam - 有限枚举集参数
#   TimeDeltaParam- 时间增量参数，支持正/负/非负等约束
#
# 参数使用基于注册表（_registry）而非实例属性存值，
# 避免了多因子同时使用同一参数对象时的数据污染。
# =============================================================================
import pandas as pd
from typing import Any, Callable, List, Optional, cast
from weakref import WeakKeyDictionary

from tools.decorators import factor_workspace
from tools.data.types import UniqueNameObject


# ═════════════════════════════════════════════════════════════════════════════
# ValueSpace —— 不可变值空间
# ═════════════════════════════════════════════════════════════════════════════

@factor_workspace
class ValueSpace:
    """
    值空间：定义合法值域、验证、标准化、展示。
    不可变对象，支持组合（并集、差集）。
    """
    @factor_workspace
    def __init__(
        self,
        contains: Callable[[Any], bool],
        rectify: Callable[[Any], Any] = lambda x: x,
        alias: Callable[[Any], str] = str,
    ):
        self._contains = contains
        self._rectify = rectify
        self._alias = alias

    def __contains__(self, value: Any) -> bool:
        return self._contains(value)

    @factor_workspace
    def rectify(self, value: Any) -> Any:
        return self._rectify(value)

    @factor_workspace
    def alias(self, value: Any) -> str:
        return self._alias(value)

    @factor_workspace
    def union(self, other: 'ValueSpace') -> 'ValueSpace':
        """返回当前空间与 other 的并集"""
        return ValueSpace(
            contains=lambda v: v in self or v in other,
            rectify=lambda v: self.rectify(v) if v in self else other.rectify(v),
            alias=lambda v: self.alias(v) if v in self else other.alias(v),
        )

    @factor_workspace
    def difference(self, other: 'ValueSpace') -> 'ValueSpace':
        """返回当前空间减去 other 的值域"""
        return ValueSpace(
            contains=lambda v: v in self and v not in other,
            rectify=self.rectify,
            alias=self.alias,
        )

    # ── 工厂方法 ──

    @classmethod
    @factor_workspace
    def any_type(cls, typ: type | tuple[type, ...]) -> 'ValueSpace':
        return cls(contains=lambda v: isinstance(v, typ))

    @classmethod
    @factor_workspace
    def finite(cls, values: List[Any]) -> 'ValueSpace':
        return cls(contains=lambda v: v in values)

    @classmethod
    @factor_workspace
    def timedelta(cls, flag: Optional[str] = None) -> 'ValueSpace':
        """flag: 'pos'/'neg'/'nonneg'/'nonpos'/None"""
        def contains(v: Any) -> bool:
            try:
                td = pd.Timedelta(v)
                if flag == 'pos':
                    return td > pd.Timedelta(0)
                if flag == 'neg':
                    return td < pd.Timedelta(0)
                if flag == 'nonneg':
                    return td >= pd.Timedelta(0)
                if flag == 'nonpos':
                    return td <= pd.Timedelta(0)
                return True
            except Exception:
                return False
        return cls(
            contains=contains,
            rectify=pd.Timedelta,
            alias=lambda v: _format_timedelta(cast(pd.Timedelta, pd.Timedelta(v)))
        )


def _format_timedelta(td: pd.Timedelta) -> str:
    c = getattr(td, 'components')
    units = {'days': 'd', 'hours': 'h', 'minutes': 'm', 'seconds': 's',
             'milliseconds': 'ms', 'microseconds': 'us', 'nanoseconds': 'ns'}
    return ''.join(f"{v}{units[k]}" for k, v in c._asdict().items() if v > 0) or '0'


# ═════════════════════════════════════════════════════════════════════════════
# Parameter —— 持有 ValueSpace 的参数基类
# ═════════════════════════════════════════════════════════════════════════════

@factor_workspace
class Parameter(UniqueNameObject):
    """
    参数对象：持有值空间和默认值，提供注册表存储不同对象的参数值。

    只做三件事：
      1. 持有 ValueSpace 和默认值
      2. 提供 WeakKeyDictionary 注册表（键为 Any 实例）
      3. 继承 UniqueNameObject 实现全局重用

    属性（兼容旧 API）：
        rectify_value   → 代理到 self._value_space.rectify
        get_value_alias → 代理到 self._value_space.alias
    """
    @factor_workspace
    def __new__(cls, alias: Optional[str] = None, *args, **kwargs):
        return super().__new__(cls, alias=alias)

    @factor_workspace
    def __init__(
        self,
        alias: Optional[str] = None,
        value_space = None,
        default_value: Any = None,
        *args, **kwargs
    ):
        if hasattr(self, '_initialized'):
            return
        assert value_space is not None
        super().__init__(alias=alias, *args, **kwargs)
        self._value_space: ValueSpace = value_space
        self.default_value = value_space.rectify(default_value)
        if default_value not in value_space:
            raise ValueError(f"Default value {default_value} not in space")
        # 注册表：WeakKeyDictionary，key 为实例
        self._registry = WeakKeyDictionary()

        # 兼容旧 API：属性代理到 _value_space
        self.rectify_value = value_space._rectify
        self.get_value_alias = value_space._alias

    # ── 值空间代理 ──
    @factor_workspace
    def __contains__(self, value: Any) -> bool:
        return value in self._value_space

    @factor_workspace
    def check_in_space(self, value: Any, error: bool = True) -> bool:
        ok = value in self._value_space
        if not ok and error:
            raise ValueError(f"{value} is not in the value space")
        return ok

    @factor_workspace
    def change_default_value(self, value: Any) -> 'Parameter':
        self.check_in_space(value)
        self.default_value = self._value_space.rectify(value)
        return self

    # ── 注册表操作 ──
    @factor_workspace
    def register(self, obj: Any, value: Any, **kwargs) -> None:
        self.check_in_space(value)
        self._registry[obj] = self._value_space.rectify(value)

    @factor_workspace
    def unregister(self, obj: Any) -> None:
        self._registry.pop(obj, None)

    @factor_workspace
    def get_value(self, obj: Any) -> Any:
        return self._registry.get(obj, self.default_value)

    # ── 表达式树代理 ──
    # Parameter 实例可通过 .shift(N) / .rolling_mean(N) 等方法直接参与表达式构建，
    # 内部创建 ParamRef(self) 代理所有 FactorExpr 上的方法。

    @factor_workspace
    def __getattr__(self, name: str):
        # 避免在 __init__ 期间提前触发 ParamRef 导入
        if name.startswith('_'):
            raise AttributeError(name)
        from tools.factors.FactorExpr import ParamRef
        return getattr(ParamRef(self), name)

    # ── 运算符代理 ──
    # Python 运算符不经过 __getattr__，需要显式代理到 ParamRef。

    @factor_workspace
    def _ref(self):
        from tools.factors.FactorExpr import ParamRef
        return ParamRef(self)

    @staticmethod
    @factor_workspace
    def _to_expr_arg(x):
        """若 x 是 Parameter，转成 ParamRef，否则原样返回。"""
        if isinstance(x, Parameter):
            from tools.factors.FactorExpr import ParamRef
            return ParamRef(x)
        return x

    @factor_workspace
    def __add__(self, other): return self._ref().__add__(self._to_expr_arg(other))
    @factor_workspace
    def __radd__(self, other): return self._ref().__radd__(self._to_expr_arg(other))
    @factor_workspace
    def __sub__(self, other): return self._ref().__sub__(self._to_expr_arg(other))
    @factor_workspace
    def __rsub__(self, other): return self._ref().__rsub__(self._to_expr_arg(other))
    @factor_workspace
    def __mul__(self, other): return self._ref().__mul__(self._to_expr_arg(other))
    @factor_workspace
    def __rmul__(self, other): return self._ref().__rmul__(self._to_expr_arg(other))
    @factor_workspace
    def __truediv__(self, other): return self._ref().__truediv__(self._to_expr_arg(other))
    @factor_workspace
    def __rtruediv__(self, other): return self._ref().__rtruediv__(self._to_expr_arg(other))
    @factor_workspace
    def __neg__(self): return self._ref().__neg__()
    @factor_workspace
    def __pos__(self): return self._ref().__pos__()
    @factor_workspace
    def __abs__(self): return self._ref().__abs__()
    @factor_workspace
    def __invert__(self): return self._ref().__invert__()


# ═════════════════════════════════════════════════════════════════════════════
# 子类 —— 利用 ValueSpace 工厂方法的语法糖
# ═════════════════════════════════════════════════════════════════════════════

@factor_workspace
class TypeParam(Parameter):
    """
    类型约束参数：只接受指定 Python 类型的值。
    示例：TypeParam('S', default_value=1) 只接受 int。
    
    typ 可以是单个 type 或 type 的 tuple（表示多类型联合）。
    """
    @factor_workspace
    def __init__(self, alias: Optional[str] = None, default_value: Any = None, 
                 typ: Optional[type | tuple[type, ...]] = None, *args, **kwargs):
        if hasattr(self, '_initialized'):
            return
        if typ is None:
            typ = type(default_value)
        space = ValueSpace.any_type(typ)
        self._typ = typ
        super().__init__(alias=alias, value_space=space, default_value=default_value, *args, **kwargs)


@factor_workspace
class FactorParam(TypeParam):
    """
    因子表达式参数：接受 FactorExpr、因子引用或数值常量（允许 None 作为默认值）。

    数值常量会规范化为 ConstExpr，使其能作为 FactorExpr 直接嵌入表达式树。

    等价于 TypeParam(..., typ=(FactorExpr, type(None)))，但自动导入 FactorExpr。
    示例：FactorParam('FE') — 接受任意 FactorExpr 或 None。
    """
    @factor_workspace
    def __init__(self, alias: Optional[str] = None, default_value: Any = None,
                 *args, **kwargs):
        if hasattr(self, '_initialized'):
            return
        from tools.factors.FactorExpr import FactorExpr, ConstExpr, ParamRef
        from tools.factors.factor_param_resolution import coerce_factor_param_expr
        from tools.parameters.DataColumnParam import DataColumnParam

        def contains(value: Any) -> bool:
            try:
                normalized = coerce_factor_param_expr(value)
            except Exception:
                return False
            return normalized is None or isinstance(normalized, (FactorExpr, str, dict))

        def rectify(value: Any) -> Any:
            return coerce_factor_param_expr(value)

        def alias_value(value: Any) -> str:
            if value is None:
                return ''
            if isinstance(value, ConstExpr):
                return str(value.value)
            if isinstance(value, dict):
                raw = value.get('factor_alias') or value.get('alias') or str(value)
                return raw
            if isinstance(value, FactorExpr):
                try:
                    return value._get_alias()
                except Exception:
                    pass
            if isinstance(value, ParamRef):
                return getattr(value.param, 'alias', str(value))
            raw = getattr(value, 'alias', str(value))
            return raw

        space = ValueSpace(
            contains=contains,
            rectify=rectify,
            alias=alias_value,
        )
        # FactorParam inherits from TypeParam but constructs its own ValueSpace;
        # set _typ so TypeParam-aware helpers (e.g. _coerce_transport_value) can
        # inspect the accepted types.
        self._typ = (FactorExpr, DataColumnParam, str, dict, type(None))
        Parameter.__init__(self, alias=alias, value_space=space, default_value=default_value, *args, **kwargs)


@factor_workspace
class FinRangeParam(Parameter):
    @factor_workspace
    def __init__(self, alias: Optional[str] = None, value_space: Optional[List[Any]] = None, 
                 default_value: Any = None, *args, **kwargs):
        if hasattr(self, '_initialized'):
            return
        if value_space is None:
            value_space = []
        if not isinstance(value_space, list):
            value_space = [value_space]
        custom_alias = kwargs.pop('get_value_alias', None)
        space = ValueSpace.finite(value_space)
        if custom_alias is not None:
            space = ValueSpace(contains=space._contains, rectify=space._rectify, alias=custom_alias)
        if default_value is None and value_space:
            default_value = value_space[0]
        self._fin_values = value_space
        self._fin_custom_alias = custom_alias
        super().__init__(alias=alias, value_space=space, default_value=default_value, *args, **kwargs)
        self.value_space = value_space  # 保留原始列表，供 Category 等子类使用


@factor_workspace
class TimeDeltaParam(Parameter):
    """
    时间增量参数：接受可转换为 pd.Timedelta 的值，支持正/负/非负/非正约束。
    示例：TimeDeltaParam('RF', flag='pos', default_value='1d') 只接受正时长。
    """
    @factor_workspace
    def __init__(self, alias: Optional[str] = None, flag: Optional[str] = None, 
                 default_value: Any = '1d', *args, **kwargs):
        if hasattr(self, '_initialized'):
            return
        space = ValueSpace.timedelta(flag)
        self.flag = flag
        super().__init__(alias=alias, value_space=space, default_value=default_value, *args, **kwargs)
