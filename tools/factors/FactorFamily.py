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
from functools import partial
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any, Callable, List, Optional, Sequence, Tuple, Set

from tools.factors.Factor import Factor
from tools.factors.FactorTester import FactorTester, get_factor_tester
from tools.factors.FactorExpr import (
    FactorExpr, DataColumn, DataFreq,
    ColumnRef, ConstExpr, ParamRef, UnaryOp,
    WindowOp, ShiftOp, CrossSectionalOp, CompositeExpr,
)
from tools.factors.Parameters import FactorFreqParam, ReverseParam, FactorNextPeriodReturns
from tools import UniqueObject, DataMeta
from tools.parameters import Parameter

from Settings import sift_volume_ratio, default_plot_test_end_date, default_plot_test_start_date, default_test_end_date, default_test_start_date, factor_info_path

if TYPE_CHECKING:
    from tools.products.Product import Product

# 每个执行上下文（线程/协程）的活跃 FactorTester
_active_tester: ContextVar[Optional['FactorTester']] = ContextVar('_active_tester', default=None)
# 活跃用户前缀，如 '$COMMON' 或 '张三@1'
_active_user_prefix: ContextVar[str] = ContextVar('_active_user_prefix', default='$COMMON')

class FactorFamily(UniqueObject):
    """
    因子族基类 — 基于表达式树的统一因子框架。

    支持两种使用方式：
        1. 声明式（推荐）— 子类定义 factor_expr() 静态方法，自动收集参数
        2. 命令式 — 直接传入 expr= 表达式树和 extra_params=

    功能：
      - func() — 表达式批量求值 + 信号对齐
      - get_factor() / get_factors() — 创建 Factor 实例
      - test()  — 一键 IC / 分组收益测试并持久化

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
        core_alias = alias if alias else cls.__name__
        user_prefix = _active_user_prefix.get()
        if user_prefix:
            name = f"{user_prefix}:{core_alias}:{uuid.uuid4().hex}"
        else:
            name = f"{core_alias}:{uuid.uuid4().hex}"
        kwargs.pop('name', None)
        return super().__new__(cls, name=name, alias=core_alias, **kwargs)

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
                source_freq = 'MIN1'
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

            # 从参数或类属性中取值
            _alias = alias if alias is not None else getattr(cls, 'alias', cls.__name__)
            super().__init__(alias=_alias, **kwargs)  # 先调用父类 __init__ 设置 name 和 alias

            _expr = expr if expr is not None else getattr(cls, 'expression', None)
            _source_freq = source_freq if source_freq is not None else getattr(cls, 'source_freq', 'MIN1')
            _math = math_expr if math_expr is not None else getattr(cls, 'math_expr', None)
            _extra = extra_params if extra_params is not None else getattr(cls, 'extra_params', None)
            _signal_freq = signal_freq if signal_freq is not None else getattr(cls, 'signal_freq', '1d')

            # desc：优先参数，其次类属性
            _desc = desc if desc is not None else getattr(cls, 'desc', '')

            # description：优先参数，其次类属性
            _desc_full = description if description is not None else getattr(cls, 'description', '')

            if _expr is None:
                raise ValueError(f"{cls.__name__}: 必须提供 expr（表达式树）参数或类属性")

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
            self.math_expr = _math or _expr.to_latex()

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
            self._last_source_data_freq: Optional[DataFreq] = None
            self.params.append(FactorFreqParam)   # 所有子类默认包含信号频率参数 F
            self.params.append(ReverseParam)       # 所有子类默认包含反转参数 $Rev（1/True=-反向；0/False=正向）
            self.params_dict = {param.alias: param for param in self.params}
            self.set_default_params()             # 以各参数默认值初始化 _params_list
            self.factors: List[Factor] = []       # 最近一批生成的 Factor 实例

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

        参数：
            return_freq      : 收益率计算频率（覆盖 Factor 默认值）
            params_list      : 若提供，则使用此列表代替 self._params_list（用于 per-user 隔离）
            **kwargs         : 额外参数（如 timezone）

        返回：
            Factor 列表，同时写入 self.factors
        """
        _pl = params_list if params_list is not None else self._params_list
        factors = []
        for params in _pl:
            factor_alias = self.get_alias(**params)
            factor_func = partial(self.func, **params)
            factor = Factor(alias=factor_alias, func=factor_func, family=self)
            # 注册参数值：使用 factor 自己的 params_dict（非$参数已为独立的副本）
            for param_alias, value in params.items():
                # $ 前缀标准化
                actual_alias = param_alias
                if param_alias not in factor.params_dict:
                    if not param_alias.startswith('$') and f'${param_alias}' in factor.params_dict:
                        actual_alias = f'${param_alias}'
                factor.params_dict[actual_alias].register(factor, value)
            if return_freq is not None:
                factor.change_current_return_freq(return_freq)
            factors.append(factor)
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
        factor_alias = self.get_alias(**new_params)
        factor_func = partial(self.func, **new_params)
        factor = Factor(alias=factor_alias, func=factor_func, param_vals=param_vals, family=self)
        if return_freq is not None:
            factor.change_current_return_freq(return_freq)
        return factor

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
                } | factor.params_dict | factor.ic_stats.to_dict() | report_dict)
                factor_table = pd.concat([factor_table, new_row.to_frame().T], ignore_index=True)
                factor.report = factor_table
                factor_table.to_csv(factor_cache_path, index=False)
        finally:
            _active_tester.reset(_token)

        return tester
    
    @property
    def expr(self) -> FactorExpr:
        """返回因子表达式树。"""
        return self._expr

    def _resolve_expr_params(self, expr: FactorExpr) -> FactorExpr:
        """
        递归解析表达式树中的参数引用。

        将 ParamRef → 对应的 ConstExpr 或 ColumnRef（取决于参数值类型），
        将 WindowOp(window=Parameter) → WindowOp(window=int/str)。

        返回一个全新的表达式树（不修改原始树）。
        """
        from tools.parameters import DataColumnParam

        # 叶子节点
        if isinstance(expr, ParamRef):
            value = expr.resolve(self)
            # 根据参数值类型决定替换为什么
            if isinstance(expr.param, DataColumnParam):
                from tools.data.DataColumn import DataColumn
                return ColumnRef(DataColumn(value))
            else:
                return ConstExpr(value)

        if isinstance(expr, (ColumnRef, ConstExpr)):
            return expr  # 不变

        # 一元算子 / 横截面算子：递归 operand（无额外参数）
        if isinstance(expr, (UnaryOp, CrossSectionalOp)):
            new_operand = self._resolve_expr_params(expr.operand)
            if new_operand is expr.operand:
                return expr
            return type(expr)(expr.op, new_operand)

        # 位移算子：递归 operand，解析 periods 参数
        if isinstance(expr, ShiftOp):
            new_operand = self._resolve_expr_params(expr.operand)
            periods = expr.periods
            if isinstance(periods, Parameter):
                periods = periods.get_value(self)
            if new_operand is expr.operand and periods is expr.periods:
                return expr
            return ShiftOp(expr.op, new_operand, periods)

        # 窗口算子：递归 operand，解析 window 参数
        if isinstance(expr, WindowOp):
            new_operand = self._resolve_expr_params(expr.operand)
            window = expr.window
            if isinstance(window, Parameter):
                window = window.get_value(self)
            if new_operand is expr.operand and window is expr.window:
                return expr
            return WindowOp(expr.op, new_operand, window)

        # 复合表达式：递归所有 operands
        if isinstance(expr, CompositeExpr):
            new_operands = tuple(self._resolve_expr_params(opnd) for opnd in expr.operands)
            if all(a is b for a, b in zip(new_operands, expr.operands)):
                return expr
            return CompositeExpr(expr.op, *new_operands)

        return expr  # fallback

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

        freq = DataFreq(self._source_freq_name)
        resolved = self._resolve_expr_params(self._expr)
        result = resolved.evaluate(products, freq, source=source)

        # ── 信号对齐 ──
        signal_df = self._align_to_signal(result, signal_freq)

        return signal_df if not is_reversed else -signal_df

    def _align_to_signal(self, data: pd.DataFrame, freq: Any) -> pd.DataFrame:
        """
        将原始数据对齐到等间隔信号时间点。

        对整个 DataFrame 一次性操作，不做逐品种循环。
        """
        freq_dc = DataFreq(freq)
        bp = self.basepoint
        end_skip = self.end_session_skip
        end_gap = self.end_session_gap

        # 找到 freq 是其整数倍的索引层级（第一个匹配的）
        index_names = [str(n) for n in data.index.names]
        index_freqs = [DataFreq(n) for n in index_names]
        first_true_idx = next(
            (i for i, f in enumerate(index_freqs)
             if freq_dc.value.total_seconds() % f.value.total_seconds() == 0), None)
        assert first_true_idx is not None, \
            f"频率 {freq_dc} 不是任何数据索引频率的整数倍"
        multiple = int(freq_dc.value.total_seconds() / index_freqs[first_true_idx].value.total_seconds())

        idx_name = index_names[first_true_idx]
        idx_series = data.index.get_level_values(idx_name).to_series().reset_index(drop=True)

        # 确定各组的基准点位置
        # 日倍频且有 daily_basepoint 时，daily_basepoint 优先
        day_bp = None
        if freq_dc.is_day_multiple and self.daily_basepoint is not None:
            day_bp = self.daily_basepoint
            try:
                base_time = pd.Timestamp(day_bp).time()
            except Exception:
                raise ValueError(
                    f"Invalid time basepoint '{day_bp}'. Must be a time string like '09:01:00' or '15:00:00'")
            series = data.groupby(idx_name).transform(
                lambda x: pd.DatetimeIndex(x.index.get_level_values(-1)).time == base_time)
        elif isinstance(bp, str):
            bp_lower = bp.lower()
            if bp_lower == 'last':
                series = data.groupby(idx_name).cumcount(ascending=False) == 0
            elif bp_lower == 'first':
                series = data.groupby(idx_name).cumcount() == 0
            else:
                raise ValueError(
                    f"Invalid basepoint '{bp}'. Must be 'last', 'first', or a callable")
        else:
            series = bp(data.groupby(idx_name))

        if not any(series):
            series = data.groupby(idx_name).cumcount(ascending=False) == 0
        assert isinstance(series, pd.Series) and series.dtype == bool, \
            "basepoint function must return a boolean Series"

        basepoint_pos = series.reset_index(drop=True).index[series]

        # 从基准点按 multiple 间隔取信号点：仅子日频需要跳过盘间间隔
        if end_skip and freq_dc.value < pd.Timedelta('1day'):
            last_col_name = index_names[-1]
            last_col = data.index.get_level_values(last_col_name).to_series().reset_index(drop=True)
            end_session_pos = last_col[last_col.shift(-1) - last_col >= end_gap].index
            # 对每个 session 段，按 multiple 间隔取信号点
            signal_map_mask = basepoint_pos.isin({
                i
                for start, end in zip(
                    [0] + (end_session_pos[:-1].values + 1).tolist(),
                    end_session_pos
                )
                for i in range(start + multiple - 1, end + 1, multiple)
                if start + multiple - 1 <= end
            })
        else:
            idx = basepoint_pos.to_series().reset_index(drop=True).index
            signal_map_mask = (idx % multiple == multiple - 1)

        signal_pos = basepoint_pos[signal_map_mask]
        signal_map = idx_series.index.isin(signal_pos)

        # 构建新的索引：左侧层级用 signal_map 打 NA，目标层级替换为信号值，右侧层级保持不变
        left_names = [str(n).split('@')[-1] for n in index_names[:first_true_idx]]
        right_names = [str(n).split('@')[-1] for n in index_names[first_true_idx + 1:]]
        signal_name = f'_SIGNAL@{freq_dc.name}'

        left_arrays = [
            data.index.get_level_values(index_names[i]).to_series().where(signal_map)
            for i in range(first_true_idx)
        ]
        signal_vals = idx_series.where(signal_map)
        right_arrays = [
            data.index.get_level_values(index_names[i]).to_series()
            for i in range(first_true_idx + 1, len(index_names))
        ]
        new_index = pd.MultiIndex.from_arrays(
            left_arrays + [signal_vals] + right_arrays,
            names=left_names + [signal_name] + right_names
        ).dropna()

        # 用新索引筛选数据
        result = data[signal_map].copy()
        result.index = new_index

        return result

class Returns(FactorFamily):
    """
    内置收益率因子族。
    """

    source_freq = 'MIN1'

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
        return super().func(products, *args, **kwargs)
