# =============================================================================
# tools/factors/FactorFamily.py
# 因子族模块 — 基于表达式树的统一因子族框架
#
# FactorFamily 支持两种使用方式：
#   1. 声明式（推荐）：定义 factor_expr() 静态方法，自动从表达式树收集参数
#   2. 命令式：直接传入 expr= 表达式树和 extra_params= 额外参数
#
# 功能：
#   - func()            — 表达式批量求值 + 信号对齐
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
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Sequence, Tuple, Set

from tools.factors.Factor import Factor
from tools.factors.FactorTester import FactorTester, get_factor_tester
from tools.factors.FactorExpr import (
    FactorExpr, DataColumn, DataFreq,
    ColumnRef, ConstExpr, ParamRef, UnaryOp,
    RollingOp, ShiftOp, CrossSectionalOp, CrossSectionalBinaryOp, CompositeExpr,
    OperandExpr,
    WindowOp, CorrOp,  # 向后兼容别名
)
from tools.factors.Parameters import FactorFreqParam, ReverseParam, ReturnFreqParam, FactorNextPeriodReturns
from tools import UniqueObject, DataMeta
from tools.parameters import Parameter

from Settings import sift_volume_ratio, default_plot_test_end_date, default_plot_test_start_date, default_test_end_date, default_test_start_date, factor_info_path

if TYPE_CHECKING:
    from tools.products.Product import Product

# ── 从 FactorTester 导入运行时上下文（避免循环导入） ──
# _active_tester / _active_user_prefix 在 FactorTester.py 模块级定义
from tools.factors.FactorTester import _active_tester, _active_user_prefix

class FactorFamily(FactorExpr, UniqueObject):
    """
    因子族基类 — 含参数的表达式模板 + 信号对齐。

    FactorFamily 继承 FactorExpr（它是带 ParamRef 的表达式树）
    和 UniqueObject（全局唯一命名对象）。

    支持两种使用方式：
        1. 声明式（推荐）— 子类定义 factor_expr() 静态方法，自动从表达式树收集参数
        2. 命令式 — 直接传入 expr= 表达式树和 extra_params=

    功能：
      - func() — 表达式批量求值 + 信号对齐
      - get_factor() / get_factors() — 创建 Factor 实例（已解析，无参数）
      - test()  — 一键 IC / 分组收益测试并持久化
      - 中间因子管理 — evaluate() 时自动缓存子表达式结果

    类属性：
        math_expr    (str)  : 因子公式的 LaTeX 字符串
        desc         (str)  : 因子简短描述
        description  (str)  : 因子详细说明（Markdown）
        params       (list) : 参数对象列表（子类覆盖或从 factor_expr 自动收集）
    """
    math_expr: str = ""
    desc: str = ""
    description: str = ""
    params: List[Parameter] = []

    # ── 信号对齐参数（类属性，可在子类或实例上覆盖） ──
    basepoint: 'str|Callable' = 'last'       # 通用信号基准点：'last'/'first'/callable
    daily_basepoint: 'str|None' = None       # 日倍频基准点（时间字符串，如 '15:00:00'），None 则用 basepoint
    end_session_skip: bool = True             # 是否跳过盘间间隔（仅子日频生效）
    end_session_gap: pd.Timedelta = pd.Timedelta('3hours')  # 盘间间隔阈值

    def __new__(cls, alias: Optional[str] = None, *args, **kwargs):
        # alias 保持纯净（类名），name = {user_prefix}:{alias}:{uuid}
        # 直接调用 UniqueObject.__new__（跳过 FactorExpr 的 object.__new__）
        core_alias = alias if alias else cls.__name__
        user_prefix = _active_user_prefix.get()
        if user_prefix:
            name = f"{user_prefix}:{core_alias}:{uuid.uuid4().hex}"
        else:
            name = f"{core_alias}:{uuid.uuid4().hex}"
        kwargs.pop('name', None)
        return UniqueObject.__new__(cls, name=name, alias=core_alias, **kwargs)

    def __init__(self, alias: Optional[str] = None,
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
                 **kwargs):
        """
        初始化 FactorFamily。

        参数均可省略（省略时从类属性取默认值），支持子类无 __init__ 声明：
            class MyFactor(FactorFamily):
                alias = 'MyFactor'
                expr = _expr
                params = [...]
                desc = '...'
                description = '...'
                math_expr = '...'

        参数：
            alias                : 因子族别名（默认从 cls.alias 读取）
            expr                 : 因子表达式树（默认从 cls.expr 读取）
            desc                 : 简短描述（默认从 cls.desc 读取）
            source_freq          : 数据频率（默认从 cls.source_freq 读取）
            description          : Markdown 详细说明（默认从 cls.description 读取）
            math_expr            : LaTeX 表达式（默认从 cls.math_expr 或 expr 自动生成）
            extra_params         : 额外参数（默认从 cls.extra_params 读取）
            signal_freq          : 默认信号频率（默认从 cls.signal_freq 或 '1d'）
        """
        if not hasattr(self, '_initialized'):
            
            cls = self.__class__

            # copy-on-write：确保子类有自己独立的 params 列表，不污染基类和其他子类
            if cls.params is FactorFamily.params:
                cls.params = list(cls.params)

            # 从参数或类属性中取值
            _alias = alias if alias is not None else getattr(cls, 'alias', cls.__name__)
            super().__init__(alias=_alias, **kwargs)  # 先调用父类 __init__ 设置 name 和 alias

            _expr = expr if expr is not None else getattr(cls, 'expression', None)
            # 声明式因子：expression 类属性未设置时，尝试调用 factor_expr() 静态方法
            if _expr is None and hasattr(cls, 'factor_expr'):
                _expr = getattr(cls, 'factor_expr')()
            _source_freq = source_freq if source_freq is not None else getattr(cls, 'source_freq', None)
            _math = math_expr if math_expr is not None else getattr(cls, 'math_expr', None)
            _extra = extra_params if extra_params is not None else getattr(cls, 'extra_params', None)
            _signal_freq = signal_freq if signal_freq is not None else getattr(cls, 'signal_freq', '1d')

            # desc：优先参数，其次类属性
            _desc = desc if desc is not None else getattr(cls, 'desc', '')

            # description：优先参数，其次类属性
            _desc_full = description if description is not None else getattr(cls, 'description', '')

            if _expr is None:
                if hasattr(cls, 'factor_expr'):
                    # 有 factor_expr 但返回了 None — 这不应该发生
                    raise ValueError(f"{cls.__name__}.factor_expr() 返回了 None")
                # 否则：旧式因子，手动实现 func()/params，不需要 expr，允许继续

            # 声明式因子：从表达式树自动收集参数（避免子类重复声明 params 列表）
            _from_factor_expr = (expr is None and getattr(cls, 'expression', None) is None
                                 and hasattr(cls, 'factor_expr'))
            if _from_factor_expr:
                assert _expr is not None  # _from_factor_expr 保证了 factor_expr 已被调用且成功
                for param in _expr.ordered_param_deps:
                    if param.alias not in {p.alias for p in cls.params}:
                        cls.params.append(param)

            # 需要在 super().__init__() 之前设置这些属性
            # 因为 __init__ 会调用 set_default_params() 读取 self.params
            self._expr = _expr
            self._source_freq_name = _source_freq

            # 按需设置 params — 内置 F/Rev 已在 __init__ 注册
            # 子类通过 class-level params 声明的额外参数已在 MRO 中
            if _extra:
                existing_aliases = {p.alias for p in cls.params}
                for p in _extra:
                    if p.alias not in existing_aliases:
                        cls.params.append(p)

            self.desc = _desc
            self.description = _desc_full
            self.math_expr = _math or (_expr.to_latex() if _expr is not None else '')

            # 信号对齐参数（None 则从类属性取默认值）
            self.basepoint = basepoint if basepoint is not None else getattr(cls, 'basepoint', 'last')
            self.daily_basepoint = daily_basepoint if daily_basepoint is not None else getattr(cls, 'daily_basepoint', None)
            self.end_session_skip = end_session_skip if end_session_skip is not None else getattr(cls, 'end_session_skip', True)
            self.end_session_gap = (end_session_gap if end_session_gap is not None
                                    else getattr(cls, 'end_session_gap', pd.Timedelta('3hours')))

            # 覆盖默认信号频率
            if _signal_freq != '1d':
                self.change_param_default_value(**{'$F': _signal_freq})
            
            self._runtime_ctx = threading.local()  # 运行时线程本地上下文（如当前 signal freq）
            self._source_freqs_lock = threading.Lock()
            self._source_freqs_seen: set[DataFreq] = set()
            # 注册内置参数 — 仅在首次实例化时追加到 cls.params
            existing_aliases = {p.alias for p in cls.params}
            if '$F' not in existing_aliases:
                cls.params.append(FactorFreqParam)
            if '$Rev' not in existing_aliases:
                cls.params.append(ReverseParam)
            self.params_dict = {param.alias: param for param in self.params}
            self.set_default_params()             # 以各参数默认值初始化 _params_list
            self.factors: List[Factor] = []       # 最近一批生成的 Factor 实例
            # 中间因子缓存：{str名称 或 FactorExpr → Factor(_local_only=True)}
            # 仅显式调用 _save_intermediate() 的节点（如 FE/RE）才存入
            self._intermediates: Dict[object, Factor] = {}

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
        """用各参数默认值初始化 _params_list（仅一组默认参数组合）。"""
        self._params_list = [{p.alias: p.default_value for p in self.params}]

    def _normalize_param_kwargs(self, **kwargs) -> dict:
        """
        归一化参数别名：当输入键不存在时，尝试在带/不带 '$' 形式间互转。

        例如：F -> $F，Rev -> $Rev。
        """
        normalized = {}
        for key, value in kwargs.items():
            target_key = key
            if key == 'Rev':
                target_key = '$Rev'
            if key not in self.params_dict:
                if key.startswith('$') and key[1:] in self.params_dict:
                    target_key = key[1:]
                elif not key.startswith('$') and f'${key}' in self.params_dict:
                    target_key = f'${key}'
            if target_key in normalized and normalized[target_key] != value:
                raise ValueError(f"Conflicting values for parameter {target_key}")
            normalized[target_key] = value
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
        parts = []
        for key, value in params.items():
            # $ 前缀标准化：与 _normalize_param_kwargs 保持一致
            if key not in self.params_dict:
                if not key.startswith('$') and f'${key}' in self.params_dict:
                    key = f'${key}'
            val_alias = self.params_dict[key]._value_space.alias(value)
            if val_alias:
                if key == '$Rev':
                    if val_alias == '1':
                        parts.append(key)
                else:
                    parts.append(f"{key}:{val_alias}")
        params_str = '|'.join(parts)
        return f"{self.alias}|{params_str}" if params_str else self.alias

    def get_factors(self, return_freq: Optional[Any] = None, params_list: Optional[list] = None, **kwargs) -> List[Factor]:
        """
        按 _params_list 中的所有参数组合批量创建 Factor 实例。

        Factor 创建时即完成参数解析：
          - $F → signal_freq（信号对齐频率）
          - $Rev → is_reversed（是否取反）
          - 其他参数 → 通过 _resolve_expr_params 固化到 _resolved_expr 中

        参数：
            return_freq      : 收益率计算频率（暂存于 tester 中）
            params_list      : 若提供，则使用此列表代替 self._params_list（用于 per-user 隔离）
            **kwargs         : 额外参数（如 timezone）

        返回：
            Factor 列表，同时写入 self.factors
        """
        _pl = params_list if params_list is not None else self._params_list
        factors = []
        for params in _pl:
            factor = self._create_factor(params)
            if return_freq is not None:
                t = Factor._get_active_tester()
                if t is not None:
                    t.factor_return_freqs[factor] = ReturnFreqParam._value_space.rectify(return_freq)
            factors.append(factor)
        self.factors = factors
        return factors

    def get_factor(self, return_freq: Optional[Any] = None, start_calc_point: Optional[Any] = None, **kwargs) -> Factor:
        """
        创建单个 Factor 实例（支持按 alias 复用已有实例）。

        参数：
            return_freq      : 收益率计算频率
            start_calc_point : 计算起始点
            **kwargs         : Parameter alias→value 键值对（未指定时取默认值）

        返回：
            Factor 实例
        """
        kwargs = self._normalize_param_kwargs(**kwargs)
        self._check_in_space(**kwargs)
        param_vals = {p: p._value_space.rectify(kwargs[p.alias]) if p.alias in kwargs else p.default_value for p in self.params}
        new_params = {p.alias: param_vals[p] for p in self.params}
        factor = self._create_factor(new_params)
        if return_freq is not None:
            t = Factor._get_active_tester()
            if t is not None:
                t.factor_return_freqs[factor] = ReturnFreqParam._value_space.rectify(return_freq)
        return factor

    def _create_factor(self, params: dict) -> Factor:
        """
        根据参数组合创建 Factor。

        流程：
          1. 提取 $F（信号频率）和 $Rev（是否取反）
          2. 用 _resolve_expr_params 将其他参数固化为纯表达式树（func_expr）
          3. 包裹 SignalAlign(func_expr, ...) → _resolved_expr
             SignalAlign 作为表达式节点参与结构去重，不同对齐参数 = 不同表达式
          4. Factor.calc() 直接 evaluate(_resolved_expr)，不需要额外对齐
        """
        factor_alias = self.get_alias(**params)

        # 提取元参数
        signal_freq = params.pop('$F', params.pop('F', '1d'))
        is_reversed: bool = params.pop('$Rev', params.pop('Rev', False))

        # 构建 param_values（排除已提取的元参数）
        param_values = {
            p.alias: params[p.alias]
            for p in self.params
            if p.alias in params and p.alias not in ('$F', 'F', '$Rev', 'Rev')
        }

        # 解析表达式树：将 ParamRef 替换为实际值 → func_expr（纯因子逻辑，不含对齐）
        from tools.factors.FactorExpr import SignalAlign
        if self._expr is not None:
            func_expr = self._resolve_expr_params(self._expr, param_values=param_values)
            # 包裹 SignalAlign：对齐参数来自 family 配置
            bp = getattr(self, 'basepoint', 'last')
            dbp = getattr(self, 'daily_basepoint', None)
            ess = getattr(self, 'end_session_skip', True)
            esg = getattr(self, 'end_session_gap', pd.Timedelta('3hours'))
            resolved_expr = SignalAlign(
                func_expr,
                signal_freq=signal_freq if signal_freq is not None else '1d',
                basepoint=bp, daily_basepoint=dbp,
                end_session_skip=ess, end_session_gap=esg,
            )
        else:
            func_expr = None
            resolved_expr = None

        return Factor(
            alias=factor_alias,
            func_expr=func_expr,        # 纯因子逻辑（不含对齐），给外部引用
            _resolved_expr=resolved_expr, # 含 SignalAlign 的完整表达式
            signal_freq=signal_freq,
            is_reversed=is_reversed,
            family=self,
        )

    def test(self, categories: Optional['str|List[str]'] = None,
             return_freq: Optional[Any] = None,
             start_calc_point: Optional[Any] = None,
             ic_test_time_range: Optional[Tuple] = None,
             sift_volume_ratio: float = sift_volume_ratio, **kwargs) -> FactorTester:
        """
        一键运行完整测试流程：因子计算 → IC 测试 → 分组收益测试 → 结果持久化。

        流程：
          1. 加载（或新建）因子信息缓存 CSV
          2. 创建 FactorTester，设置时间范围
          3. 调用 calc_factor、calc_ic
          4. 对每个 Factor 调用 test_by_group，并将结果追加写入 CSV

        参数：
            categories       : 品种分类过滤（字符串或列表），None 表示不过滤
            return_freq      : 收益率计算频率
            start_calc_point : 计算起始点
            ic_test_time_range: (start, end)，覆盖全局默认区间
            sift_volume_ratio: 按成交量筛选品种的比例（0~1）

        返回：
            FactorTester 对象（含完整测试结果）
        """
        factor_cache_path = os.path.join(factor_info_path, self.alias, self.alias + '.csv')
        if not os.path.exists(factor_info_path):
            os.makedirs(factor_info_path)
        if os.path.exists(factor_cache_path) and os.path.isfile(factor_cache_path):
            factor_table = pd.read_csv(factor_cache_path)
        else:
            factor_table = pd.DataFrame()

        start_date = ic_test_time_range[0] if ic_test_time_range is not None else default_test_start_date
        end_date = ic_test_time_range[1] if ic_test_time_range is not None else default_test_end_date
        tester = get_factor_tester(time_range=(start_date, end_date))
        # start_calc_point 通过 tester.start_calc_point（带时区 Timestamp）统一访问
        if start_calc_point is not None:
            tester.start_calc_point = pd.Timestamp(start_calc_point)

        returns_col = FactorNextPeriodReturns.NEXT_OPEN_TO_OPEN_ADJUSTED  # 默认使用次日开盘→开盘收益

        _token = _active_tester.set(tester)
        try:
            factors = self.get_factors(return_freq=return_freq, **kwargs)
            tester.calc_factor(factors)
            tester.calc_ic(returns_col=returns_col)

            for factor in factors:

                _, _, report_df, _, _ = tester.test_by_group(factor, returns_col=returns_col,
                    plot_flag=True, time_range=(default_plot_test_start_date, default_plot_test_end_date),
                    plot_show=False, plot_remark_str=','.join(categories) if categories else None, **kwargs
                    )

                # 将分组回测结果拼入发布报告行
                report_dict = {}
                for col in report_df.columns:
                    key_0 = f"{col} {report_df.index[0]}"
                    report_dict[key_0] = report_df.loc[report_df.index[0], col]
                for col in report_df.columns:
                    key_1 = f"{col} {report_df.index[1]}"
                    report_dict[key_1] = report_df.loc[report_df.index[1], col]

                new_row = pd.Series({
                    'factor_stem': self.alias,
                    'serial_num': pd.Timestamp.now(),
                    'factor_name': factor.alias,
                    'factor_freq': factor.freq,
                    'start_date': tester.start_date,
                    'end_date': tester.end_date,
                    'sift_volume_ratio': sift_volume_ratio,
                    'categories': categories,
                } | (factor.family.params_dict if factor.family else {}) | tester.factor_ic_stats.get(factor, pd.Series()).to_dict() | report_dict)
                factor_table = pd.concat([factor_table, new_row.to_frame().T], ignore_index=True)
                tester.factor_reports[factor] = factor_table
                factor_table.to_csv(factor_cache_path, index=False)
        finally:
            _active_tester.reset(_token)

        return tester
    
    @property
    def expr(self) -> FactorExpr:
        """返回因子表达式树。"""
        return self._expr  # type: ignore[return-value]

    def _resolve_expr_params(self, expr: FactorExpr, param_values: dict | None = None) -> FactorExpr:
        """
        递归解析表达式树中的参数引用。

        将 ParamRef → 对应的 ConstExpr 或 ColumnRef（取决于参数值类型），
        将 RollingOp/ShiftOp 中 window/periods Parameter → 实际值。

        参数：
            expr         : 表达式树
            param_values : 参数值字典（{alias: value}），优先于注册表查找。
                           由 func() 根据当前 Factor 的 kwargs 构建。

        返回一个全新的表达式树（不修改原始树）。
        """
        from tools.parameters import DataColumnParam

        # 叶子节点
        if isinstance(expr, ParamRef):
            value = expr.resolve(self, param_values=param_values)
            # 根据参数值类型决定替换为什么
            if isinstance(value, FactorExpr):
                return value       # 参数值本身是表达式（如 FE=某个因子表达式）
            if isinstance(expr.param, DataColumnParam):
                from tools.data.DataColumn import DataColumn
                return ColumnRef(DataColumn(value))
            else:
                return ConstExpr(value)

        if isinstance(expr, (ColumnRef, ConstExpr)):
            return expr  # 不变

        # ── OperandExpr 通用分发：委托给 _resolve_operand_expr ──
        if isinstance(expr, OperandExpr):
            resolved = self._resolve_operand_expr(expr, param_values)
            if resolved is not None:
                return resolved

        return expr  # fallback

    def _resolve_operand_expr(self, expr: 'OperandExpr', param_values: Optional[Dict[str, Any]]) -> Optional['OperandExpr']:
        """
        对 OperandExpr 子类进行参数解析和重建。

        子类分发：
          - RollingOp: 递归 operands + 解析 window
          - ShiftOp: 递归 operand + 解析 periods
          - CompositeExpr: 递归 operands + 常量折叠
          - 其他（UnaryOp, CrossSectionalOp, CrossSectionalBinaryOp）: 仅递归 operands
        """
        from tools.factors.FactorExpr import (
            UnaryRollingOp, BinaryRollingOp, CompositeExpr, RollingOp, ShiftOp,
            UnaryOp, CrossSectionalOp, CrossSectionalBinaryOp,
        )
        from tools.parameters.Parameter import Parameter

        # ── RollingOp: 递归所有 _operands，解析 window ──
        if isinstance(expr, RollingOp):
            operands = expr._operands
            new_operands = tuple(self._resolve_expr_params(opnd, param_values=param_values) for opnd in operands)
            window = expr.window
            if isinstance(window, Parameter):
                if param_values is not None and window.alias in param_values:
                    window = param_values[window.alias]
                else:
                    window = window.get_value(self)
            elif isinstance(window, str) and window.startswith('$'):
                # "$F" 之类参数别名 → 从 param_values 或参数表查找
                alias = window
                if param_values is not None and alias in param_values:
                    window = param_values[alias]
                elif alias in self.params_dict:
                    window = self.params_dict[alias].get_value(self)
            if (all(a is b for a, b in zip(new_operands, operands))
                    and window is expr.window):
                return expr
            if isinstance(expr, UnaryRollingOp):
                return UnaryRollingOp(expr.op, new_operands[0], window)
            elif isinstance(expr, BinaryRollingOp):
                return BinaryRollingOp(expr.op, new_operands[0], new_operands[1], window)
            else:
                expr.window = window
                return expr

        # ── ShiftOp: 递归 operand，解析 periods ──
        if isinstance(expr, ShiftOp):
            new_operand = self._resolve_expr_params(expr.operand, param_values=param_values)
            periods = expr.periods
            if isinstance(periods, Parameter):
                if param_values is not None and periods.alias in param_values:
                    periods = param_values[periods.alias]
                else:
                    periods = periods.get_value(self)
            elif isinstance(periods, str) and periods.startswith('$'):
                # "$F" 之类参数别名 → 从 param_values 或参数表查找
                alias = periods
                if param_values is not None and alias in param_values:
                    periods = param_values[alias]
                elif alias in self.params_dict:
                    periods = self.params_dict[alias].get_value(self)
            elif isinstance(periods, FactorExpr):
                resolved_periods = self._resolve_expr_params(periods, param_values=param_values)
                if isinstance(resolved_periods, ConstExpr):
                    periods = resolved_periods.value
                else:
                    periods = resolved_periods
            if new_operand is expr.operand and periods is expr.periods:
                return expr
            return ShiftOp(expr.op, new_operand, periods)  # type: ignore[arg-type]

        # ── CompositeExpr: 递归所有 operands，尝试常量折叠 ──
        if isinstance(expr, CompositeExpr):
            new_operands = tuple(self._resolve_expr_params(opnd, param_values=param_values) for opnd in expr.operands)
            if all(a is b for a, b in zip(new_operands, expr.operands)):
                return expr
            if all(isinstance(opnd, ConstExpr) for opnd in new_operands):
                try:
                    folded = CompositeExpr._fold_const(expr.op, new_operands)  # type: ignore[arg-type]
                    if folded is not None:
                        return folded  # type: ignore[return-type]
                except Exception:
                    pass
            return CompositeExpr(expr.op, *new_operands)

        # ── 通用 OperandExpr（UnaryOp, CrossSectionalOp, CrossSectionalBinaryOp）: 仅递归 operands ──
        operands = expr.operands
        new_operands = tuple(self._resolve_expr_params(opnd, param_values=param_values) for opnd in operands)
        if all(a is b for a, b in zip(new_operands, operands)):
            return expr
        # 用原始类型重建
        return type(expr)(expr.op, *new_operands)

    def func(self, products: Sequence['Product'], *args, **kwargs) -> pd.DataFrame:
        """
        重写 func()：直接通过表达式求值批量计算所有品种的信号。

        比默认 func() 更高效：一次性构建全品种 DataFrame，
        避免逐品种循环和 concat。

        流程：
          1. 表达式求值 → DataFrame（列=Product，行=时间MultiIndex）
          2. 根据 basepoint/end_session_skip 构建信号索引，一次性对齐
          3. 应用反转（如有）
        """
        kwargs = self._normalize_param_kwargs(**kwargs)
        if '$F' in kwargs and 'F' not in kwargs:
            kwargs['F'] = kwargs['$F']
        signal_freq = kwargs.get('F', pd.Timedelta('1d'))
        is_reversed: bool = kwargs.pop('$Rev', False)
        source = kwargs.pop('source', None)

        freq = DataFreq(self._source_freq_name or 'MIN1')
        if self._expr is None:
            raise TypeError(
                f"{self.__class__.__name__}: 未定义 expr（表达式树），无法使用 FactorFamily.func()。"
                f"请覆盖 func() 方法或定义 factor_expr() / expression 类属性。")
        # 构建 param_values：从 kwargs 中提取属于本 family 参数的值
        # （排除 F、$F、$Rev、source 等已处理的键）
        param_values = {
            p.alias: kwargs[p.alias]
            for p in self.params if p.alias in kwargs
        }
        resolved = self._resolve_expr_params(self._expr, param_values=param_values)

        # ── 预加载：收集所有需要的列，每个品种只读一次 ──
        from tools.factors.FactorExpr import ColumnRef
        from tools.data.DataMeta import DataMeta

        preloaded: dict = {}
        column_refs = resolved.collect_column_refs()
        # 按 (product, freq_name) 分组，收集需要的列名
        prod_freq_cols: dict[tuple, set] = {}
        for cr in column_refs:
            col_name = cr.column.name
            for p in products:
                key = (p, freq.name)
                if key not in prod_freq_cols:
                    prod_freq_cols[key] = set()
                prod_freq_cols[key].add(col_name)

        for (p, freq_name), cols in prod_freq_cols.items():
            dm: DataMeta = getattr(p, freq_name)
            if source is not None:
                try:
                    dm.set_current_source(source)
                except ValueError:
                    continue
            if dm.next_available_source() is None:
                continue
            # 一次性读取该品种的所有需要的列
            data = dm.get_and_adjust_cols(list(cols), copy=False)
            if not data.empty:
                preloaded[(p, freq_name)] = data

        # evaluate cache：{FactorExpr → DataFrame}，递归求值时避免重复计算
        df_cache: Dict[FactorExpr, pd.DataFrame] = {}
        result = resolved.evaluate(products, freq, source=source, preloaded=preloaded,
                                 cache=df_cache)

        # 自动创建用户标记的中间因子（.as_intermediate() 标记的节点）
        for expr, df in df_cache.items():
            if expr is not resolved and getattr(expr, '_is_intermediate', False):
                if expr not in self._intermediates:
                    f = Factor(alias=expr._get_alias(), _local_only=True)
                    f.table = self._align_to_signal(df, signal_freq)
                    f.source_table = df
                    f.family = self
                    self._intermediates[expr] = f

        # 保存未对齐的原始数据，供 Factor.source_table 使用
        self._last_raw_result = result

        # ── 信号对齐 ──
        signal_df = self._align_to_signal(result, signal_freq)

        return signal_df if not is_reversed else -signal_df

    def _align_to_signal(self, data: pd.DataFrame, freq: Any) -> pd.DataFrame:
        """委托给 signal_align 工具函数。"""
        from tools.factors.FactorExpr import signal_align
        return signal_align(
            data, freq,
            basepoint=self.basepoint,
            daily_basepoint=self.daily_basepoint,
            end_session_skip=self.end_session_skip,
            end_session_gap=self.end_session_gap,
        )

class Returns(FactorFamily):
    """
    内置收益率因子族。

    不再硬编码 source_freq —— 由 Factor.calc() 自动推断
    或在 calc() 调用时通过 source_freq 参数显式指定。
    """

    @staticmethod
    def factor_expr():
        from tools.parameters import DataColumnParam, WindowParam, TypeParam
        SC = DataColumnParam('SC', default_value=DataColumn.CLOSE)
        RF = WindowParam('RF')
        S = TypeParam('S', default_value=0)
        return (SC.delta(RF) / SC.shift(RF)).shift((S - 1) * RF)

    def func(self, products, *args, **kwargs):
        kwargs = self._normalize_param_kwargs(**kwargs)
        SC = kwargs.get('SC', DataColumn.CLOSE)
        # 根据价格列自动确定 basepoint
        if SC in (DataColumn.OPEN, DataColumn.OPEN_ADJUSTED):
            self.basepoint = 'first'
        else:
            self.basepoint = 'last'
            self.daily_basepoint = '15:00:00'
        # 收益率信号频率 = RF（而非独立的 F 参数）
        # 移除可能冲突的 F/$F，用 RF 的值替代（Returns 不需要独立的 F 参数）
        kwargs.pop('$F', None)
        kwargs.pop('F', None)
        if 'RF' in kwargs:
            kwargs['F'] = kwargs['RF']
        return super().func(products, *args, **kwargs)


# ═════════════════════════════════════════════════════════════════════════════
# CrossSectionIC —— 统一截面 IC 因子族
# ═════════════════════════════════════════════════════════════════════════════

class CrossSectionIC(FactorFamily):
    """
    截面 IC 因子族：接受主因子表达式 FE 和收益率表达式 RE 作为参数，
    通过 factor_expr() 声明式地计算截面 Spearman 秩相关系数。

    参数：
        FE  : 主因子表达式树 (FactorExpr)
        RE  : 收益率表达式树 (FactorExpr)，默认使用 Returns 族表达式
        Lag : IC 时滞，非负整数。0=同期IC，Lag>0=因子领先收益率Lag期
        F   : 信号频率（复用 FactorFreqParam）

    不再硬编码 source_freq —— 由 Factor.calc() 自动推断。
    func() 向后兼容：无显式 source_freq 时回退 'MIN1'。
    """

    # _intermediates 已由 FactorFamily.__init__ 初始化为 {FactorExpr: Factor}
    # 此处不再覆盖；func() 在 evaluate 后自动填充

    def _save_intermediate(self, key: object, factor: 'Factor') -> None:
        """保存中间因子，供外部取用。key 可以是 FactorExpr 或字符串名称。"""
        self._intermediates[key] = factor

    def get_intermediate(self, key: object) -> 'Factor | None':
        """获取已保存的中间因子。key 可以是 FactorExpr 或字符串名称。"""
        return self._intermediates.get(key, None)

    @staticmethod
    def factor_expr():
        from tools.parameters import FactorParam, TypeParam
        from tools.factors.FactorExpr import CrossSectionalBinaryOp
        FE = FactorParam('FE')
        RE = FactorParam('RE')
        Lag = TypeParam('Lag', default_value=0, typ=int)
        # 截面 IC = cs_spearman(FE, RE.shift(-Lag))
        # Lag>0 表示因子领先收益率 Lag 期：用 Lag 期前的 RE 与当期 FE 计算
        return FE.cs_spearman(RE.shift(-Lag))

    def func(self, products, *args, **kwargs):
        """
        求值 FE 和 RE 子表达式，保存中间结果，然后计算截面 IC。
        """
        kwargs = self._normalize_param_kwargs(**kwargs)
        signal_freq = kwargs.get('F', pd.Timedelta('1d'))
        is_reversed: bool = kwargs.pop('$Rev', False)
        source = kwargs.pop('source', None)

        freq = DataFreq(self._source_freq_name or 'MIN1')
        if self._expr is None:
            raise TypeError(f"{self.__class__.__name__}: 未定义 expr")

        # 构建 FE 和 RE 子表达式
        # factor_expr() 返回的树中，FE 和 RE 是 CrossSectionalBinaryOp 的左右子节点
        # 但我们需要单独求值它们来保存中间结果
        from tools.parameters import TypeParam
        fe_param = next((p for p in self.params if p.alias == 'FE'), None)
        re_param = next((p for p in self.params if p.alias == 'RE'), None)

        param_values = {
            p.alias: kwargs[p.alias]
            for p in self.params if p.alias in kwargs
        }

        # 构建 FE 子表达式
        from tools.factors.FactorExpr import ParamRef, ColumnRef
        fe_expr = ParamRef(fe_param) if fe_param else None
        re_expr = ParamRef(re_param) if re_param else None

        # 若 RE 未提供，用内置 Returns 表达式
        if re_expr is None or kwargs.get('RE', None) is None:
            from tools.parameters import DataColumnParam, WindowParam
            SC = DataColumnParam('SC', default_value=DataColumn.CLOSE)
            RF = WindowParam('RF', default_value='1d')
            S = TypeParam('S', default_value=0)
            re_expr = (SC.delta(RF) / SC.shift(RF)).shift((S - 1) * RF)
            re_param = None

        # 解析参数
        fe_resolved = self._resolve_expr_params(fe_expr, param_values=param_values)  # type: ignore[arg-type]
        if re_param is not None:
            re_resolved = self._resolve_expr_params(re_expr, param_values=param_values)
        else:
            re_resolved = re_expr  # Returns 表达式不含 ParamRef

        # 校验：抛出具体原因，而非 AttributeError: 'ConstExpr' has no 'index'
        from tools.factors.FactorExpr import ConstExpr
        if isinstance(fe_resolved, ConstExpr) and fe_resolved.value is None:
            fe_val = kwargs.get('FE', fe_param and fe_param.default_value)
            raise ValueError(f"FE 参数未设置 (当前值: {fe_val!r})，请为 {self.name} 指定 FE 表达式。")

        # ── 统一预加载 ──
        from tools.data.DataMeta import DataMeta
        fe_refs = fe_resolved.collect_column_refs()
        re_refs = re_resolved.collect_column_refs()
        all_refs = fe_refs | re_refs

        preloaded: dict = {}
        prod_freq_cols: dict[tuple, set] = {}
        for cr in all_refs:
            col_name = cr.column.name
            for p in products:
                key = (p, freq.name)
                if key not in prod_freq_cols:
                    prod_freq_cols[key] = set()
                prod_freq_cols[key].add(col_name)

        for (p, freq_name), cols in prod_freq_cols.items():
            dm: DataMeta = getattr(p, freq_name)
            if source is not None:
                try:
                    dm.set_current_source(source)
                except ValueError:
                    continue
            if dm.next_available_source() is None:
                continue
            data = dm.get_and_adjust_cols(list(cols), copy=False)
            if not data.empty:
                preloaded[(p, freq_name)] = data

        # ── 分别求值 FE / RE ──
        df_cache: Dict[FactorExpr, pd.DataFrame] = {}
        fe_raw = fe_resolved.evaluate(products, freq, preloaded=preloaded, cache=df_cache)
        re_raw = re_resolved.evaluate(products, freq, preloaded=preloaded, cache=df_cache)

        # 自动创建用户标记的中间因子（.as_intermediate() 标记的节点）
        for expr, df in df_cache.items():
            if getattr(expr, '_is_intermediate', False) and expr not in self._intermediates:
                f = Factor(alias=expr._get_alias(), _local_only=True)
                f.table = self._align_to_signal(df, signal_freq)
                f.source_table = df
                f.family = self
                self._intermediates[expr] = f

        # ── 信号对齐 ──
        fe_df = self._align_to_signal(fe_raw, signal_freq)
        re_df = self._align_to_signal(re_raw, signal_freq)

        if is_reversed:
            fe_df = -fe_df

        # 保存中间因子（匿名本地 Factor）—— FE/RE 总是作为中间因子暴露
        fe_factor = Factor(alias='FE', _local_only=True)
        fe_factor.table = fe_df
        fe_factor.source_table = fe_raw
        fe_factor.family = self
        self._save_intermediate('FE', fe_factor)

        re_factor = Factor(alias='RE', _local_only=True)
        re_factor.table = re_df
        re_factor.source_table = re_raw
        re_factor.family = self
        self._save_intermediate('RE', re_factor)

        # ── Lag 位移：RE.shift(-Lag)，Lag>0 时用历史 RE ──
        lag = kwargs.get('Lag', 0)
        if lag != 0:
            re_df = re_df.shift(-lag)

        # ── 截面 Spearman IC ──
        from tools.factors.FactorExpr import CrossSectionalBinaryOp
        import numpy as np
        result = CrossSectionalBinaryOp._apply_spearman(fe_df, re_df)

        # 还原为 MultiIndex
        from tools.factors.FactorTester import _extract_signal_index as _ext_sig
        if isinstance(fe_df.index, pd.MultiIndex):
            fe_sig = _ext_sig(fe_df.index)
            dt_index = result.index
            mask = fe_sig.isin(dt_index)
            mapping = {sig: full for sig, full in zip(fe_sig[mask], fe_df.index[mask])}
            valid_ts = [ts for ts in dt_index if ts in mapping]
            full_idx = pd.MultiIndex.from_tuples(
                [mapping[ts] for ts in valid_ts],
                names=fe_df.index.names)
            ic_vals = [result.loc[ts, result.columns[0]] if ts in result.index else np.nan
                       for ts in valid_ts]
            result = pd.Series(ic_vals, index=full_idx)

        return result.to_frame(name=self.name) if isinstance(result, pd.Series) else result
