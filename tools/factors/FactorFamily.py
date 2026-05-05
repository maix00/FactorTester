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
from tools.factors.FactorData import FactorData
from tools.factors.FactorExpr import (
    FactorExpr, DataColumn, DataFreq,
    ColumnRef, ConstExpr, ParamRef,
    RollingOp, ShiftOp, CrossSectionalOp, CompositeExpr,
    OperandExpr,
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
            self.math_expr = _math or (_expr.to_latex_with_intermediates() if _expr is not None else '')

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
            # 中间因子：{str → FactorData}，evaluate 后由 _collect_intermediates() 填充
            self._intermediates: Dict[str, 'FactorData'] = {}

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
        normalized = self._normalize_param_kwargs(**params)
        ordered_keys = [p.alias for p in self._expr.ordered_param_deps] if self._expr is not None else sorted(
            (k for k in normalized.keys() if k in self.params_dict),
            key=lambda k: (type(self.params_dict[k]).__name__, self.params_dict[k].alias),
        )

        parts = []
        for key in ordered_keys:
            value = normalized[key]
            val_alias = self.params_dict[key]._value_space.alias(value)
            if val_alias:
                if key == '$Rev':
                    if val_alias == '1':
                        parts.append(key)
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
            _pl = [{p.alias: p.default_value for p in self.params}]
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
            signal_freq = current_params.get('$F', current_params.get('F', '1d'))
            is_reversed: bool = current_params.get('$Rev', current_params.get('Rev', False))

            # 构建 param_values（排除已提取的元参数）
            param_values = {
                p.alias: current_params[p.alias]
                for p in self.params
                if p.alias in current_params and p.alias not in ('$F', 'F', '$Rev', 'Rev')
            }

            # 解析表达式树：将 ParamRef 替换为实际值 → func_expr（纯因子逻辑，不含对齐）
            if self._expr is not None:
                func_expr = self.resolve(self._expr, param_values=param_values).as_intermediate()
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
                if is_reversed:
                    resolved_expr = CompositeExpr('neg', resolved_expr)
                    func_expr = CompositeExpr('neg', func_expr)
            else:
                func_expr = None
                resolved_expr = None

            factor = Factor(
                alias=factor_alias,
                func_expr=func_expr,
                _resolved_expr=resolved_expr,
                signal_freq=signal_freq,
                is_reversed=False,
                family=self,
            )

            if return_freq is not None:
                t = Factor._get_active_tester()
                if t is not None:
                    t.factor_return_freqs[factor] = ReturnFreqParam._value_space.rectify(return_freq)
            factors.append(factor)

        self.factors = factors
        return factors

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

    @staticmethod
    def resolve(expr: FactorExpr, param_values: dict | None = None) -> FactorExpr:
        """
        递归解析表达式树中的参数引用
        将 ParamRef → 对应的 ConstExpr 或 ColumnRef（取决于参数值类型）
        """
        return expr.resolve(param_values=param_values)

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
        resolved = self.resolve(self._expr, param_values=param_values)

        # ── 预加载：收集所有需要的列，每个品种只读一次 ──
        from tools.factors.FactorExpr import ColumnRef
        from tools.data.DataMeta import DataMeta

        preloaded: dict = {}
        column_refs = resolved.column_refs
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

        # 保存未对齐的原始数据，供 Factor.source_table 使用
        self._last_raw_result = result

        # ── 收集中间因子 ──
        self._collect_intermediates(resolved)

        # ── 信号对齐 ──
        signal_df = self._align_to_signal(result, signal_freq)

        return signal_df if not is_reversed else -signal_df

    def _collect_intermediates(self, resolved: 'FactorExpr') -> None:
        """
        遍历解析后的整棵表达式树，收集所有 _is_intermediate 标记的节点。
        子类可覆盖以实现自定义收集逻辑（如 CrossSectionIC 按名称收集）。
        """
        from tools.factors.FactorData import FactorData

        self._intermediates.clear()
        name_to_sk: Dict[str, tuple] = {}

        seen: Set[tuple] = set()
        stack: List[FactorExpr] = [resolved]

        while stack:
            node = stack.pop()
            sk = node._structural_key()
            if sk in seen:
                continue
            seen.add(sk)

            if getattr(node, '_is_intermediate', False):
                structural_hash = str(sk)
                fd = FactorData.get_by_hash(structural_hash)
                if fd is not None:
                    name = getattr(node, '_intermediate_name', None)
                    if name:
                        prev_sk = name_to_sk.get(name)
                        if prev_sk is not None and prev_sk != sk:
                            raise ValueError(
                                f"Intermediate 名称冲突: {name} 被用于不同表达式。"
                                "请为不同子表达式使用不同 as_intermediate(name)。"
                            )
                        name_to_sk[name] = sk
                        self._intermediates[name] = fd

            for opnd in reversed(list(getattr(node, '_operands', ()))):
                stack.append(opnd)

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
    截面 IC 因子族：接受一个因子表达式 FE，内部构建收益率表达式 RE，
    通过 factor_expr() 声明式地计算截面 Spearman 秩相关系数。

    参数：
        FE  : 被分析因子表达式 (FactorExpr)，不含 SignalAlign（由调用方剥离）
        SC  : 收益率价格列 (DataColumn)，默认 CLOSE_ADJUSTED
              OPEN/OPEN_ADJUSTED → basepoint='first'，Lag=1（下一期开盘收益）
              CLOSE/CLOSE_ADJUSTED → basepoint='last'，Lag=0（同期收益）
        RF  : 收益率计算窗口 (WindowParam)，默认 '1d'
        S   : 收益率 shift 偏移 (TypeParam)，默认自动根据 SC 决定
        F   : 信号频率（复用 FactorFreqParam）

    FE 和 RE 子表达式自动标记为 _is_intermediate，evaluate 后
    由 _collect_intermediates() 遍历 operands 收集到 _intermediates。
    """

    def get_intermediate(self, key: object) -> 'FactorData | None':
        """
        获取中间因子数据（FactorData，含 source_table 原始数据）。

        key 支持两种形式：
          - str: 按 .as_intermediate() 注册的名称查找，如 'FE', 'RE'
          - FactorExpr: 按表达式结构 hash 查找 → FactorData.get_by_hash()

        中间因子在 evaluate() 时自动创建 FactorData 并存入全局去重表，
        _collect_intermediates() 按名称收集到 self._intermediates。
        """
        from tools.factors.FactorData import FactorData

        if isinstance(key, str):
            return self._intermediates.get(key)
        if hasattr(key, '_structural_key'):
            # key 是 FactorExpr，按结构 hash 查找
            return FactorData.get_by_hash(str(key._structural_key()))  # type: ignore[union-attr]
        return None

    @staticmethod
    def factor_expr():
        """
        FE.cs_spearman(RE.shift(-Lag))

        FE — 被分析因子（纯因子逻辑，不含 SignalAlign）
        RE — 收益率表达式，内建：(SC.delta(RF) / SC.shift(RF)).shift((S - 1) * RF)
        """
        from tools.parameters import FactorParam, DataColumnParam, WindowParam, TypeParam
        from tools.data.DataColumn import DataColumn

        FE = FactorParam('FE')
        SC = DataColumnParam('SC', default_value=DataColumn.CLOSE_ADJUSTED)
        RF = WindowParam('RF')
        # S: 收益率 shift 偏移
        #   OPEN   → S = 0 → .shift(-RF) → 下一期开盘
        #   CLOSE  → S = 1 → .shift(0)    → 同期
        S = TypeParam('S', default_value=1, typ=int)
        # RE = (SC.delta(RF) / SC.shift(RF)).shift((S - 1) * RF)
        RE = (SC.delta(RF) / SC.shift(RF)).shift((S - 1) * RF)

        # 标记 FE 和 RE 为中间因子，evaluate 后由 _collect_intermediates() 收集
        FE = FE.as_intermediate('FE')
        RE = RE.as_intermediate('RE')

        return FE.cs_spearman(RE)

    def func(self, products, *args, **kwargs):
        """
        根据 SC 参数动态设置 basepoint，然后委托父类求值。

        - OPEN/OPEN_ADJUSTED → basepoint='first'
        - CLOSE/CLOSE_ADJUSTED → basepoint='last', daily_basepoint='15:00:00'
        """
        from tools.data.DataColumn import DataColumn
        kwargs = self._normalize_param_kwargs(**kwargs)

        SC = kwargs.get('SC', DataColumn.CLOSE_ADJUSTED)
        if SC in (DataColumn.OPEN, DataColumn.OPEN_ADJUSTED):
            self.basepoint = 'first'
            self.daily_basepoint = None
        else:
            self.basepoint = 'last'
            self.daily_basepoint = '15:00:00'

        # 收益率信号频率 = RF（而非独立的 F 参数）
        kwargs.pop('$F', None)
        kwargs.pop('F', None)
        if 'RF' in kwargs:
            kwargs['F'] = kwargs['RF']

        return super().func(products, *args, **kwargs)
