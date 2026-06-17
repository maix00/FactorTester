# =============================================================================
# tools/factors/FactorFamily.py
# 因子族模块 — 基于表达式树的统一因子族框架
#
# FactorFamily 支持两种使用方式：
#   1. 声明式（推荐）：定义 factor_expr() 静态方法，自动从表达式树收集参数
#   2. 命令式：直接传入 expr= 表达式树和 extra_params= 额外参数
#
# 功能：
#   - get_factor() / get_factors() — 创建 Factor 实例
#   - test()            — 一键运行 IC / 分组收益测试并持久化结果
#   - 内置 Returns — 收益率因子族
#
# =============================================================================
from __future__ import annotations

import os
import threading
import uuid
import pandas as pd
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Tuple, cast

from tools.decorator.factor_workspace import factor_workspace
from tools.factors.Factors import Factor
from tools.factors.FactorTester import FactorTester, get_factor_tester
from tools.factors.FactorExpr import (
    FactorExpr, DataColumn, DataFreq,
    ColumnRef, ConstExpr, ParamRef,
    RollingOp, ShiftOp, CrossSectionalOp, CompositeExpr,
    OperandExpr,
)
from tools.factors.Parameters import FactorFreqParam, ReverseParam, ReturnFreqParam, FactorNextPeriodReturns
from tools.data.types.base import UniqueNameObject
from tools import ProductDataView
from tools.parameters import Parameter
from tools.parameters.Parameter import FactorParam

from Settings import sift_volume_ratio, default_plot_test_end_date, default_plot_test_start_date, default_test_end_date, default_test_start_date, factor_info_path

if TYPE_CHECKING:
    from tools.products.Product import Product

# ── 从 FactorTester 导入运行时上下文（避免循环导入） ──
# _active_tester / _active_user_prefix 在 FactorTester.py 模块级定义
from tools.factors.FactorTester import _active_tester, _active_user_prefix

@factor_workspace
class FactorFamily(UniqueNameObject, FactorExpr):
    """
    因子族基类 — 含参数的表达式模板 + 信号对齐。

    继承链：UniqueNameObject（别名去重）+ FactorExpr（表达式树定义与求值）。

    使用方式：
      1. 声明式（推荐）— 子类重写 factor_expr()，返回表达式树，params 自动从 ParamRef 节点收集
      2. 命令式 — 直接传入 expr= 和 extra_params=

    核心流程：
      get_factor(**params) → Factor（已解析 = 无 ParamRef，可直接 evaluate）
      test(products, time_range) → IC + 分组回测 + 结果持久化

    关键属性：
        math_expr (LaTeX), desc (中文名), description (Markdown)
        basepoint / daily_basepoint / end_session_skip — 信号对齐配置
        depends_on  — 中间因子依赖声明
    """
    _runtime_ctx: threading.local
    _source_freqs_lock: threading.Lock

    math_expr: str = ""
    desc: str = ""
    description: str = ""
    factors: List[Factor] = []
    params: List[Parameter] = []
    params_dict: Dict[str, Parameter] = {}

    # ── 信号对齐参数（类属性，可在子类或实例上覆盖） ──
    basepoint: 'str|Callable' = 'last'       # 通用信号基准点：'last'/'first'/callable
    daily_basepoint: 'str|None' = None       # 日倍频基准点（时间字符串，如 '15:00:00'），None 则用 basepoint
    end_session_skip: bool = False             # 是否跳过盘间间隔（仅子日频生效）
    end_session_gap: pd.Timedelta = cast(pd.Timedelta, pd.Timedelta('3hours'))  # 盘间间隔阈值

    _expr: Optional[FactorExpr] = None
    _source_freq: Any = ''   # 从表达式树解析出的原始数据频率名称（如 '1d'、'1m'）
    _source_freqs_seen: set[DataFreq] = set()
    _has_natural_neg: bool = False
    _instance_signal_freq: str = '1d'

    def __new__(cls, alias: Optional[str] = None, 
                 expr: Optional[FactorExpr] = None,
                 desc: Optional[str] = None,
                 source_freq: Optional[str] = None,
                 description: Optional[str] = None,
                 math_expr: Optional[str] = None,
                 extra_params: Optional[List[Parameter]] = None,
                 signal_freq: Optional[str] = None,
                 basepoint: 'Optional[str|Callable]' = None,
                 daily_basepoint: 'Optional[str]' = None,
                 end_session_skip: Optional[bool] = None,
                 end_session_gap: 'Optional[pd.Timedelta]' = None,
                 *args, **kwargs):
        # alias 保持纯净（类名），name = {user_prefix}:{alias}:{uuid}
        # 直接调用 UniqueObject.__new__（跳过 FactorExpr 的 object.__new__）
        core_alias = alias if alias else cls.__name__
        user_prefix = _active_user_prefix.get()
        if user_prefix:
            name = f"{user_prefix}:{core_alias}:{uuid.uuid4().hex}"
        else:
            name = f"{core_alias}:{uuid.uuid4().hex}"
        name = kwargs.pop('name', name)
        alias = kwargs.pop('alias', core_alias)
        instance = UniqueNameObject.__new__(cls, name=name, alias=alias, **kwargs)
        
        if not hasattr(instance, '_initialized'):
            _expr = expr if expr is not None else getattr(cls, 'expression', None)
            # 声明式因子：expression 类属性未设置时，尝试调用 factor_expr() 静态方法
            _from_factor_expr = False
            if _expr is None and hasattr(cls, 'factor_expr'):
                _expr = getattr(cls, 'factor_expr')()
                _from_factor_expr = True

            # 声明式因子自动剥离 factor_expr() 最外层自然 neg，并将 $Rev 默认值设为 1
            # 处理两种情况：
            #   1. 真正的最外层 neg：return -expr          → 剥离 neg, $Rev 默认=1
            #   2. 分子带 neg 的分式：return -A / B        → 剥离分子 neg, $Rev 默认=1
            # 例：MmMADevRat 定义 return -P.rolling_mean(N)/(P+1e-10)
            #     → 剥离后 _expr = P.rolling_mean(N)/(P+1e-10)，$Rev 默认=1
            _has_natural_neg = False
            if _from_factor_expr and _expr is not None:
                if isinstance(_expr, CompositeExpr) and _expr.op == 'neg':
                    # 情况 1：最外层即 neg
                    _expr = _expr.operands[0]
                    _has_natural_neg = True
                elif isinstance(_expr, CompositeExpr) and len(_expr.operands) > 0:
                    # 情况 2：检查第一个操作数是否 neg
                    first_op = _expr.operands[0]
                    if isinstance(first_op, CompositeExpr) and first_op.op == 'neg':
                        # 剥离第一个操作数的 neg，用 -1 乘法实现等价变换（如果 op 支持）
                        if _expr.op in ('div', 'mul'):
                            _expr = CompositeExpr(
                                _expr.op,
                                first_op.operands[0],
                                *_expr.operands[1:],
                            )
                            _has_natural_neg = True

            cls.params = list(_expr.ordered_param_deps) if _expr is not None else []
            _source_freq = source_freq if source_freq is not None else getattr(cls, 'source_freq', None)
            _math = math_expr if math_expr is not None else getattr(cls, 'math_expr', None)
            _extra = extra_params if extra_params is not None else getattr(cls, 'extra_params', None)
            _signal_freq = signal_freq if signal_freq is not None else getattr(cls, 'signal_freq', '1d')

            if _expr is None:
                if hasattr(cls, 'factor_expr'):
                    # 有 factor_expr 但返回了 None — 这不应该发生
                    raise ValueError(f"{cls.__name__}.factor_expr() 返回了 None")
                # 否则：旧式因子，手动实现 func()/params，不需要 expr，允许继续

            # 声明式因子：从表达式树自动收集参数（避免子类重复声明 params 列表）
            if _from_factor_expr:
                assert _expr is not None  # _from_factor_expr 保证了 factor_expr 已被调用且成功
                for param in _expr.ordered_param_deps:
                    if param.alias not in {p.alias for p in cls.params}:
                        cls.params.append(param)

            instance._expr = _expr
            instance._source_freq = _source_freq

            # 按需设置 params — 内置 F/Rev 已在 __init__ 注册
            # 子类通过 class-level params 声明的额外参数已在 MRO 中
            if _extra:
                existing_aliases = {p.alias for p in cls.params}
                for p in _extra:
                    if p.alias not in existing_aliases:
                        cls.params.append(p)

            instance.desc = desc if desc is not None else getattr(cls, 'desc', '')
            instance.description = description if description is not None else getattr(cls, 'description', '')
            instance.math_expr = _math or (_expr.to_latex() if _expr is not None else '')

            # 信号对齐参数（None 则从类属性取默认值）
            instance.basepoint = basepoint if basepoint is not None else getattr(cls, 'basepoint', 'last')
            instance.daily_basepoint = daily_basepoint if daily_basepoint is not None else getattr(cls, 'daily_basepoint', None)
            instance.end_session_skip = end_session_skip if end_session_skip is not None else getattr(cls, 'end_session_skip', False)
            object.__setattr__(instance, 'end_session_gap',
                               end_session_gap if end_session_gap is not None
                               else getattr(cls, 'end_session_gap', cast(pd.Timedelta, pd.Timedelta('3hours'))))

            instance._runtime_ctx = threading.local()  # 运行时线程本地上下文（如当前 signal freq）
            instance._source_freqs_lock = threading.Lock()
            instance._source_freqs_seen = set()
            # 注册内置参数 — 仅在首次实例化时追加到 cls.params
            existing_aliases = {p.alias for p in cls.params}
            if '$F' not in existing_aliases:
                cls.params.append(FactorFreqParam)
            if '$Rev' not in existing_aliases:
                cls.params.append(ReverseParam)
            instance.params_dict = {param.alias: param for param in instance.params}

            # 保存自然 neg 和 signal_freq 覆盖信息，供 set_default_params 使用
            # 不通过 change_param_default_value 修改全局单例的 default_value
            instance._has_natural_neg = _has_natural_neg
            instance._instance_signal_freq = _signal_freq

            instance.set_default_params()             # 以各参数默认值初始化 _params_list
            instance.factors = []       # 最近一批生成的 Factor 实例
            instance._initialized = True
        return instance

    def _extract_user_prefix(self) -> Optional[str]:
        """
        从 self.name 中提取用户前缀。
        
        name 格式: '{user_prefix}:{alias}:{uuid}' 如 '$COMMON:MmMABreak:a1b2c3d4'
        返回: '$COMMON' 或 '张三@1' 或 None
        """
        name = self.name
        if ':' in name:
            prefix = name.split(':', 1)[0]
            if prefix == '$COMMON' or ('@' in prefix and prefix.rsplit('@', 1)[-1].isdigit()):
                return prefix
        return None

    def set_default_params(self):
        """用各参数默认值初始化 _params_list（仅一组默认参数组合）。
        
        自然 neg 和 signal_freq 覆盖通过 _params_list 中的值体现，
        不修改全局单例 Parameter 的 default_value。
        """
        self._params_list = [{p.alias: p.default_value for p in self.params}]
        params = self._params_list[0]
        if getattr(self, '_has_natural_neg', False):
            params['$Rev'] = True
        if getattr(self, '_instance_signal_freq', '1d') != '1d':
            params['$F'] = self._instance_signal_freq

    def _normalize_param_kwargs(self, **kwargs) -> dict:
        """
        参数名校验：F 和 $F 是完全独立的参数，不做任何自动转换。

        Issue #5: 取消 F→$F/Rev→$Rev 补全，调用方负责使用正确的参数名。
        """
        normalized = {}
        for key, value in kwargs.items():
            if key not in self.params_dict:
                raise ValueError(
                    f"Unknown parameter '{key}' for factor family '{self.alias}'. "
                    f"Available: {list(self.params_dict.keys())}"
                )
            if key in normalized and normalized[key] != value:
                raise ValueError(f"Conflicting values for parameter {key}")
            normalized[key] = value
        return normalized

    def change_param_default_value(self, **kwargs):
        """修改指定参数的默认值（同时校验值域）。"""
        kwargs = self._normalize_param_kwargs(**kwargs)
        self._check_in_space(**kwargs)
        for key, value in kwargs.items():
            self.params_dict[key].default_value = value

    def clear_params(self):
        """清空参数组合列表，使 get_factors 不生成任何 Factor。"""
        self._params_list = []

    def _check_in_space(self, **kwargs):
        """校验 kwargs 中每个参数值是否在对应参数的值域内，不在则抛出 ValueError。"""
        kwargs = self._normalize_param_kwargs(**kwargs)
        for key in kwargs:
            if kwargs[key] not in self.params_dict[key]:
                raise ValueError(f"{kwargs[key]} is not in the value space of {key}")

    def add_params(self, **kwargs):
        """
        向 _params_list 追加一组参数组合（已存在则忽略）。

        未指定的参数取其默认值，所有值均经 rectify_value 标准化。
        """
        kwargs = self._normalize_param_kwargs(**kwargs)
        self._check_in_space(**kwargs)
        new_params = {p.alias: p._value_space.rectify(kwargs[p.alias]) if p.alias in kwargs else p.default_value for p in self.params}
        if new_params not in self._params_list:
            self._params_list.append(new_params)

    def del_params(self, **kwargs):
        """从 _params_list 中删除与 kwargs 匹配的参数组合。"""
        kwargs = self._normalize_param_kwargs(**kwargs)
        self._check_in_space(**kwargs)
        del_params = {p.alias: p._value_space.rectify(kwargs[p.alias]) if p.alias in kwargs else p.default_value for p in self.params}
        self._params_list = [params for params in self._params_list if params != del_params]

    def set_all_params(self):
        """【子类可选重写】批量设置常用参数组合，不实现时返回 NotImplementedError。"""
        return NotImplementedError("请在子类中实现 `set_all_params` 方法")

    def get_alias(self, **params) -> str:
        """
        根据参数值生成 Factor 的完整别名。

        格式：{家族别名}|{alias1}:{值别名}|{alias2}:{值别名}...
        值别名为空字符串的参数会被跳过，不出现在名称中。
        若无参数则直接返回家族别名。
        """
        normalized = self._normalize_param_kwargs(**params)
        ordered_keys = sorted(
            (k for k in normalized.keys() if k in self.params_dict),
            key=lambda k: (k.startswith('$'), type(self.params_dict[k]).__name__, self.params_dict[k].alias),
        )

        parts = []
        for key in ordered_keys:
            value = normalized[key]
            param = self.params_dict[key]
            val_alias = param._value_space.alias(value)
            if val_alias:
                if key == '$Rev':
                    if val_alias == '1':
                        parts.append(key)
                elif isinstance(param, FactorParam):
                    parts.append(f"{key}:[{val_alias}]")
                else:
                    parts.append(f"{key}:{val_alias}")
        params_str = '|'.join(parts)
        return f"{self.alias}|{params_str}" if params_str else self.alias

    def get_factor(self, **kwargs) -> Factor:
        """根据 kwargs 中的参数值生成一个 Factor 实例（kwargs 形式同 add_params）。"""
        factors = self.get_factors(**kwargs)
        assert factors, "get_factors 返回了空列表，无法生成 Factor 实例"
        return factors[0]

    def get_factors(self, return_freq: Optional[Any] = None, params_list: Optional[list] = None, **kwargs) -> List[Factor]:
        """
        按 _params_list 中的所有参数组合批量创建 Factor 实例。

        流程：
          1. 提取 $F（信号频率）和 $Rev（是否取反）
          2. 用 resolve 将其他参数固化为纯表达式树（func_expr）
          3. 包裹 SignalAlign(func_expr, ...) → _resolved_expr
          4. Factor.calc() 直接 evaluate(_resolved_expr)，不需要额外对齐

        参数：
            return_freq      : 收益率计算频率（暂存于 tester 中）
            params_list      : 若提供，则使用此列表代替 self._params_list（用于 per-user 隔离）
            **kwargs         : 额外参数（如 timezone）

        返回：
            Factor 列表，同时写入 self.factors
        """
        from tools.factors.FactorExpr import SignalAlign, CompositeExpr

        normalized_kwargs = self._normalize_param_kwargs(**kwargs) if kwargs else {}
        if normalized_kwargs:
            self._check_in_space(**normalized_kwargs)

        if params_list is not None:
            _pl = params_list
        elif normalized_kwargs:
            _pl = [{
                p.alias: normalized_kwargs[p.alias] if p.alias in normalized_kwargs else p.default_value
                for p in self.params
            }]
        else:
            _pl = self._params_list

        factors = []
        for params in _pl:
            current_params = dict(params)
            if normalized_kwargs:
                for key, value in normalized_kwargs.items():
                    current_params[key] = self.params_dict[key]._value_space.rectify(value)

            factor_alias = self.get_alias(**current_params)

            # 提取元参数
            signal_freq = current_params.get('$F', '1d')
            is_reversed: bool = current_params.get('$Rev', False)

            # 构建 param_values（排除已提取的元参数）
            param_values = {
                p.alias: current_params[p.alias]
                for p in self.params
                if p.alias in current_params and p.alias not in ('$F', '$Rev')
            }

            # 解析表达式树：将 ParamRef 替换为实际值 → func_expr（纯因子逻辑，不含对齐）
            if self._expr is not None:
                func_expr = self.resolve(self._expr, param_values=param_values, caller=self).as_intermediate()
                bp = getattr(self, 'basepoint', 'last')
                dbp = getattr(self, 'daily_basepoint', None)
                ess = getattr(self, 'end_session_skip', True)
                esg = getattr(self, 'end_session_gap', pd.Timedelta('3hours'))
                resolved_expr = SignalAlign(
                    operand=func_expr,
                    signal_freq=signal_freq if signal_freq is not None else '1d',
                    basepoint=bp, daily_basepoint=dbp,
                    end_session_skip=ess, end_session_gap=esg,
                )
                if is_reversed:
                    resolved_expr = CompositeExpr('neg', resolved_expr)
                    func_expr = CompositeExpr('neg', func_expr)
            else:
                continue

            factor = Factor(expr=resolved_expr, alias=factor_alias, signal_freq=signal_freq, family=self)
            for key, value in current_params.items():
                self.params_dict[key].register(factor, value)

            if return_freq is not None:
                t = Factor._get_active_tester()
                if t is not None:
                    t._get_result(factor).return_freq = ReturnFreqParam._value_space.rectify(return_freq)
            factors.append(factor)

        self.factors = factors
        return factors
    
    @property
    def expr(self) -> FactorExpr:
        """返回因子表达式树。"""
        return self._expr  # type: ignore[return-value]

    @staticmethod
    def resolve(expr: FactorExpr, param_values: dict | None = None, **kwargs) -> FactorExpr:
        """
        递归解析表达式树中的参数引用
        将 ParamRef → 对应的 ConstExpr 或 ColumnRef（取决于参数值类型）
        """
        return expr.resolve(param_values=param_values, **kwargs)
