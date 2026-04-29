# =============================================================================
# tools/factors/ExprFactorFamily.py
# 基于表达式的因子族
#
# ExprFactorFamily 将 FactorExpr 表达式树包装为 FactorFamily，
# 可直接用现有 FactorTester 进行 IC 测试和分组回测。
#
# 使用方式：
#
#   from tools.factors.FactorExpr import OPEN, HIGH, LOW, CLOSE, VOLUME
#   from tools.factors.ExprFactorFamily import ExprFactorFamily
#
#   # 定义表达式：(close - open) / (high - low) — 日内位置因子
#   expr = (CLOSE - OPEN) / (HIGH - LOW + 1e-8)
#
#   # 创建 ExprFactorFamily
#   family = ExprFactorFamily(
#       alias='MyIntradayPosition',
#       expr=expr,
#       chinese_name='日内位置因子',
#       source_freq='MIN1',
#       description_sections=[...],
#       math_expr=expr.to_latex(),
#   )
#
#   # 运行测试（与现有 FactorFamily 完全相同）
#   tester = family.test()
#
#   # 查看结果
#   for factor in family.factors:
#       print(factor.ic_stats)
#
# 表达式支持：
#   - 列引用：OPEN, HIGH, LOW, CLOSE, VOLUME（不复权）
#   - 算术：+, -, *, /, neg, abs
#   - 时序：.ma(N), .std(N), .ref(N), .delta(N), .log(), .sign()
#   - 横截面：.cs_zscore(), .cs_rank()
#   - 比较/逻辑：>, <, ==, >=, <=, &, |
#   - 聚合：max(expr1, expr2, ...), min(expr1, expr2, ...)
#
# =============================================================================
from __future__ import annotations

import pandas as pd
from functools import partial
from typing import TYPE_CHECKING, Any, List, Optional, Sequence, Tuple, Set

from tools.factors.FactorFamily import FactorFamily
from tools.factors.Factor import Factor
from tools.factors.FactorExpr import (
    FactorExpr, DataColumn, DataFreq,
    ColumnRef, ConstExpr, ParamRef, UnaryOp,
    WindowOp, ShiftOp, CrossSectionalOp, CompositeExpr,
)
from tools.factors.Parameters import FactorFreqParam
from tools.parameters import Parameter, WindowParam, DataColumnParam

if TYPE_CHECKING:
    from tools.products.Product import Product

# 因子族默认支持 $Rev 和 $F 参数（已在 FactorFamily.__init__ 中注册），
# 无需在子类中重复声明。

class ExprFactorFamily(FactorFamily):
    """
    基于表达式的因子族 — 从 FactorExpr 表达式自动生成 FactorFamily。

    与普通 FactorFamily 的区别：
      - 不需要重写 func_timeseries()
      - 因子计算逻辑由 expr.evaluate(products, freq) 驱动
      - 支持表达式树的 LaTeX 自动生成
      - 额外参数通过 extra_params 声明

    参数：
        alias               : 因子族别名（如 'MyFactor'）
        expr                : FactorExpr 表达式树
        chinese_name        : 中文名称
        source_freq         : 使用的数据频率（'MIN1' 或 'DAY1'）
        description_sections: 因子结构化说明
        math_expr           : LaTeX 数学表达式（默认自动从 expr 生成）
        extra_params        : 额外的 Parameter 列表（需在 expr 构建时通过闭包引用）
        signal_freq         : 默认信号频率（默认 '1d'）
    """

    params: List[Parameter] = []  # 重置为空，子类可覆盖

    def __init_subclass__(cls, **kwargs):
        """子类定义完成后自动调用 factor_expr（如果定义了的话），并从表达式树自动收集 params。
        同时自动迁移旧字段 chinese_name → desc, description_sections → description。"""
        super().__init_subclass__(**kwargs)

        # --- 自动迁移旧字段到新字段 ---
        cls_cn = cls.__dict__.get('chinese_name', '')
        if cls_cn and not isinstance(cls_cn, property) and not cls.__dict__.get('desc'):
            cls.desc = cls_cn  # type: ignore[attr-defined]
        cls_ds = cls.__dict__.get('description_sections', None)
        if cls_ds is not None and not isinstance(cls_ds, property) and not cls.__dict__.get('description'):
            cls.description = FactorFamily._sections_to_markdown(cls_ds) if cls_ds else ''  # type: ignore[attr-defined]

        # --- 自动收集 factor_expr ---
        if hasattr(cls, 'factor_expr'):
            cls.expression = cls.factor_expr()  # type: ignore[attr-defined]
            # 从表达式树自动收集参数：按类型字典序分组，组内按 alias 字典序排序
            params = cls.expression.ordered_param_deps
            cls.params = sorted(params, key=lambda p: (type(p).__name__, p.alias))

    def __init__(self, alias: Optional[str] = None,
                 expr: Optional[FactorExpr] = None,
                 desc: Optional[str] = None,
                 source_freq: Optional[str] = None,
                 description: Optional[str] = None,
                 math_expr: Optional[str] = None,
                 extra_params: Optional[List[Parameter]] = None,
                 signal_freq: Optional[str] = None,
                 # ---- 向后兼容参数 ----
                 chinese_name: Optional[str] = None,
                 description_sections: Optional[List[dict]] = None,
                 **kwargs):
        """
        初始化 ExprFactorFamily。

        参数均可省略（省略时从类属性取默认值），支持子类无 __init__ 声明：
            class MyFactor(ExprFactorFamily):
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
            chinese_name         : [已废弃] 向后兼容，等同于 desc
            description_sections : [已废弃] 向后兼容，等同于 description
        """
        cls = self.__class__

        # 从参数或类属性中取值
        _alias = alias if alias is not None else getattr(cls, 'alias', cls.__name__)
        _expr = expr if expr is not None else getattr(cls, 'expression', None)
        _source_freq = source_freq if source_freq is not None else getattr(cls, 'source_freq', 'MIN1')
        _math = math_expr if math_expr is not None else getattr(cls, 'math_expr', None)
        _extra = extra_params if extra_params is not None else getattr(cls, 'extra_params', None)
        _signal_freq = signal_freq if signal_freq is not None else getattr(cls, 'signal_freq', '1d')

        # desc：优先参数，其次类属性 desc，再其次 chinese_name 向后兼容
        if desc is not None:
            _desc = desc
        elif chinese_name is not None:
            _desc = chinese_name
        else:
            _desc = getattr(cls, 'desc', '') or getattr(cls, 'chinese_name', '') or ''

        # description：优先参数，其次类属性 description
        # description_sections 已在 __init_subclass__ 自动迁移到 description
        if description is not None:
            _desc_full = description
        elif description_sections is not None:
            _desc_full = FactorFamily._sections_to_markdown(description_sections) if description_sections else ''
        else:
            _desc_full = getattr(cls, 'description', '') or ''

        if _expr is None:
            raise ValueError(f"{cls.__name__}: 必须提供 expr（表达式树）参数或类属性")

        # 需要在 super().__init__() 之前设置这些属性
        # 因为 __init__ 会调用 set_default_params() 读取 self.params
        self._expr = _expr
        self._source_freq_name = _source_freq

        # 按需设置 params（ExprFactorFamily 没有自己的 param 声明，只有内置的 F/Rev）
        # 若子类通过 class-level params 声明了额外参数，它们已在 MRO 中
        if _extra:
            existing_aliases = {p.alias for p in cls.params}
            for p in _extra:
                if p.alias not in existing_aliases:
                    cls.params.append(p)

        super().__init__(alias=_alias)

        self.desc = _desc
        self.description = _desc_full
        self.math_expr = _math or _expr.to_latex()

        # 覆盖默认信号频率
        if _signal_freq != '1d':
            self.change_param_default_value(**{'$F': _signal_freq})

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

    def func_timeseries(self, product: 'Product', *args, **kwargs) -> pd.Series:
        """
        单品种因子计算 — 从表达式求值结果中提取该品种的时序。

        ExprFactorFamily 在 func() 层面重写了整个计算流程，
        不走逐品种 func_timeseries 循环，但保留此方法供兼容。
        """
        freq = DataFreq(self._source_freq_name)
        source = kwargs.pop('source', None)
        resolved = self._resolve_expr_params(self._expr)
        df = resolved.evaluate([product], freq, source=source)
        # df 只有一列（一个品种），取出来作为 Series
        if isinstance(df, pd.DataFrame):
            if df.shape[1] == 1:
                result = df.iloc[:, 0]
            else:
                # 尝试按 product 列名匹配
                result = df[product] if product in df.columns else df.iloc[:, 0]
        else:
            result = df
        # 对齐到信号频率
        signal_freq = kwargs.get('F', kwargs.get('$F', pd.Timedelta('1d')))
        return self.sync_signal(result, freq=signal_freq)

    def func(self, products: Sequence['Product'], *args, **kwargs) -> pd.DataFrame:
        """
        重写 func()：直接通过表达式求值批量计算所有品种的信号。

        比默认 func() 更高效：一次性构建全品种 DataFrame，
        避免逐个品种循环和 concat。

        流程：
          1. 表达式求值 → DataFrame（列=Product，行=时间MultiIndex）
          2. 通过 sync_signal 对齐到信号频率
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

        # sync_signal 作用于整个 DataFrame
        # 由于 sync_signal 默认处理 Series，这里给每列单独处理再合并
        synced = {}
        for col in result.columns:
            synced[col] = self.sync_signal(result[col], freq=signal_freq)

        # 按列 concat
        all_index = synced[list(synced.keys())[0]].index
        for s in list(synced.values())[1:]:
            all_index = all_index.union(s.index)
        signal_df = pd.concat(
            {k: s.reindex(all_index) for k, s in synced.items()}, axis=1
        )

        if is_reversed:
            signal_df = -signal_df

        return signal_df

    def get_factors(self, return_freq=None, params_list=None, **kwargs) -> List[Factor]:
        """
        重写 get_factors：由于表达式因子族通常只有一组参数（默认），
        只需生成一个 Factor。
        """
        return super().get_factors(return_freq=return_freq, params_list=params_list, **kwargs)


# ═════════════════════════════════════════════════════════════════════════════
# 快捷创建函数
# ═════════════════════════════════════════════════════════════════════════════

def make_factor_family(
    alias: str,
    expr: FactorExpr,
    chinese_name: str = '',
    source_freq: str = 'MIN1',
    extra_params: Optional[List[Parameter]] = None,
    **kwargs
) -> ExprFactorFamily:
    """
    快捷创建 ExprFactorFamily。

    示例：
        from tools.factors.FactorExpr import CLOSE, OPEN, HIGH, LOW, MA
        expr = (CLOSE - OPEN) / (HIGH - LOW + 1e-8)
        family = make_factor_family('IntradayPos', expr, chinese_name='日内位置')

    参数同 ExprFactorFamily。
    """
    return ExprFactorFamily(
        alias=alias,
        expr=expr,
        chinese_name=chinese_name,
        source_freq=source_freq,
        extra_params=extra_params,
        **kwargs,
    )
