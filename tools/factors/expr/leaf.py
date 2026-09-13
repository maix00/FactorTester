# =============================================================================
# tools/factors/expr/leaf.py
# 因子表达式系统 — 从 FactorExpr.py 拆分
# =============================================================================
from __future__ import annotations

import numpy as np
import pandas as pd
from typing import (
    TYPE_CHECKING, Any, Optional, Set
)

from tools.data.types import DataColumn
from tools.data.types import DataFreq

if TYPE_CHECKING:
    from tools.products.Product import Product
    from tools.data.providers import DataProviderProductTS as DataSource
    from tools.data.views.ProductDataView import ProductDataView
    from tools.parameters.Parameter import Parameter


from .core import FactorExpr, EvaluateContext


_LATEX_TIME_UNITS = {
    'days': r'\mathrm{d}',
    'hours': r'\mathrm{h}',
    'minutes': r'\mathrm{min}',
    'seconds': r'\mathrm{s}',
    'milliseconds': r'\mathrm{ms}',
    'microseconds': r'\mu\mathrm{s}',
    'nanoseconds': r'\mathrm{ns}',
}


def _format_latex_value(value: Any) -> str:
    """Format scalar expression values without leaking Python repr syntax.

    ``str(pd.Timedelta)`` is a human-readable Python value such as
    ``25 days 00:00:00``.  In a math environment that becomes a sequence of
    implicit variables and punctuation.  Keep the canonical duration while
    making every unit an upright LaTeX operator (``25\\,\\mathrm{d}``).
    """
    if isinstance(value, pd.Timedelta):
        sign = '-' if value < pd.Timedelta(0) else ''
        components = abs(value).components
        parts = [
            rf"{int(getattr(components, name))}\,{unit}"
            for name, unit in _LATEX_TIME_UNITS.items()
            if int(getattr(components, name))
        ]
        return sign + r'\,'.join(parts) if parts else '0'
    return str(value)

class ColumnRef(FactorExpr):
    """
    数据列引用 — 表达式树的叶子节点。

    示例：
        close = ColumnRef(DataColumn.CLOSE_ADJUSTED)
        high  = ColumnRef(DataColumn.HIGH_ADJUSTED)
        vol   = ColumnRef(DataColumn.VOLUME)

    运行时通过 product.{freq} 获取数据，source 参数选择数据源。
    """

    def __init__(self, column: DataColumn):
        self.column = column

    @property
    def is_leaf_ref(self) -> bool:
        return True

    @property
    def required_columns(self) -> Set[str]:
        """此列引用所需的数据列名（用于校验数据源是否兼容）。"""
        return {self.column.name, self.column.value}

    def _select_source(self, product: 'Product', freq: DataFreq,
                       source: Optional['DataSource'] = None) -> Optional['DataSource']:
        """
        为给定品种选择数据源。返回 None 表示无需指定（ProductDataView 使用自己的加载逻辑）。

        - 若 source 已指定：校验该品种在此 source+freq 下是否有数据
        - 若未指定：遍历 DataSource 找到第一个可用且包含所需列的源
        - 若无注册的数据源：返回 None，由 ProductDataView 自行加载
        """
        from tools.data.providers import DataProviderProductTS as DataSource

        return DataSource.select_for_product(product, freq, source)

    def _evaluate(self, ctx: EvaluateContext) -> pd.DataFrame:

        from tools.data.views.ProductDataView import ProductDataView

        products = ctx.products
        freq = ctx.freq
        source = ctx.source
        preloaded = ctx.preloaded

        series_dict = {}
        for p in products:
            # 优先使用预加载数据
            if preloaded is not None:
                preload_key = (p, freq.name)
                preloaded_df = preloaded.get(preload_key)
                if preloaded_df is not None and self.column.name in preloaded_df.columns:
                    series_dict[p] = preloaded_df[self.column.name]
                    continue
                if preloaded_df is not None:
                    from tools.data.views.ProductDataView import ProductDataView
                    raw_col = ProductDataView._get_nonadjusted_col_name(self.column.name)
                    if ProductDataView._check_is_adjusted(self.column.name) and raw_col in preloaded_df.columns:
                        series_dict[p] = preloaded_df[raw_col]
                        continue

            dm: ProductDataView = getattr(p, freq.name)
            if source is not None:
                try:
                    dm.set_current_source(source)
                except ValueError as e:
                    raise Warning(f"ColumnRef: source {source.key} is not compatible with product {p.name} at freq {freq.name}") from e
            if dm.next_available_source() is None:
                continue  # 无可用数据源，跳过此品种
            col_name = self.column.name   # 如 'CLOSE_ADJUSTED' for CA

            # 使用 get_and_adjust_cols 确保复权列（如 CLOSE_ADJUSTED）被自动计算
            data = dm.get_and_adjust_cols(
                [col_name],
                copy=False,
                start_dt=ctx.start_dt,
                end_dt=ctx.end_dt,
                warmup_window=ctx.warmup_window,
            )
            if data.empty:
                continue
            series_dict[p] = data[col_name]

        result = pd.concat(series_dict, axis=1).sort_index(level=-1, sort_remaining=False)
        result.columns = list(series_dict.keys())
        run_result = ctx.run_result
        if (
            run_result is not None
            and isinstance(run_result.data_present_mask, pd.DataFrame)
            and run_result.data_present_mask.empty
        ):
            data_present_mask = pd.DataFrame(
                {
                    product: np.asarray(result.index.isin(series.index), dtype=bool)
                    for product, series in series_dict.items()
                },
                index=result.index,
                dtype=bool,
            )
            run_result.data_present_mask = data_present_mask
            run_result.data_present_all = bool(data_present_mask.to_numpy(dtype=bool).all())
        return result

    @property
    def op_name(self) -> str:
        return self.column.value

    def _to_latex(self, subst: dict | None = None) -> str:
        sk = self._structural_key()
        if subst is not None and sk in subst:
            return f"{subst[sk]}_t"
        col_to_latex = {
            'O': 'O_t', 'H': 'H_t', 'L': 'L_t', 'C': 'C_t',
            'OA': '\\tilde{O}_t', 'HA': '\\tilde{H}_t',
            'LA': '\\tilde{L}_t', 'CA': '\\tilde{C}_t',
            'V': 'V_t', 'OI': 'OI_t',
        }
        return col_to_latex.get(self.column.value) or self.column.value

    def _get_alias(self) -> str:
        return self.column.value

    def _structural_key(self) -> tuple:
        return ('ColumnRef', self.column)


class CategoryBoolRef(FactorExpr):
    """A category membership selection evaluated as a boolean product panel."""

    def __init__(self, category: Any, category_name: str):
        from tools.products.categories.Category import Category

        if not isinstance(category, Category):
            raise TypeError("CategoryBoolRef requires a Category")
        if category_name not in category.categories:
            raise ValueError(
                f"Category name {category_name!r} is not in {category.alias!r}"
            )
        self.category = category
        self.category_name = category_name

    @property
    def is_leaf_ref(self) -> bool:
        return True

    def _evaluate(self, ctx: EvaluateContext) -> pd.DataFrame:
        timeline = ctx.panel_timeline
        if timeline is None:
            raise ValueError(
                "CategoryBoolRef requires EvaluateContext.panel_timeline so its "
                "boolean panel has a concrete evaluation index"
            )
        index = timeline.index
        result = pd.DataFrame(index=index, columns=list(ctx.products), dtype=bool)
        for product in ctx.products:
            result[product] = self.category.is_in_category(self.category_name, product)
        return result.astype(bool)

    @property
    def op_name(self) -> str:
        return f"CAT[{self.category.alias}:{self.category_name}]"

    def _to_latex(self, subst: dict | None = None) -> str:
        sk = self._structural_key()
        if subst is not None and sk in subst:
            return f"{subst[sk]}_t"
        return rf"\operatorname{{Cat}}_{{{self.category.alias}:{self.category_name}}}"

    def _get_alias(self) -> str:
        raw = f"CAT_{self.category.alias}_{self.category_name}"
        return ''.join(char if char.isalnum() or char == '_' else '_' for char in raw)

    def _structural_key(self) -> tuple:
        return (
            'CategoryBoolRef',
            self.category.alias,
            getattr(self.category, '_definition_key', None),
            self.category_name,
        )

class ParamRef(FactorExpr):
    """
    参数引用 — 表达式树的叶子节点，运行时从 FactorFamily 注册表取参数值。

    示例：
        window_param = WindowParam('W', 5)            # 2. WindowParam 来自 tools/parameters
        close_ma = ColumnRef(DataColumn.CLOSE_ADJUSTED).rolling_mean(window_param)

        # 等价于：close_ma = CLOSE.rolling_mean(5)，但窗口长度由外部参数化

    支持的类型：
      - DataColumnParam: 值会被 rectify 为 DataColumn 后用于列查找
      - WindowParam: 值作为窗口参数传入 RollingOp
      - 任意 Parameter: 值直接作为标量参与表达式计算
    """

    def __init__(self, param: 'Parameter'):
        self.param = param

    @property
    def is_leaf_ref(self) -> bool:
        return True

    def _evaluate(self, ctx: EvaluateContext) -> pd.DataFrame:
        raise RuntimeError("ParamRef._evaluate() 不得调用; 请先调用 resolve(param_values) 将 ParamRef 转为 ConstExpr/ColumnRef 后再求值")

    def resolve(self, param_values: dict | None = None, *args, **kwargs) -> FactorExpr:
        """从宿主对象的注册表中取出当前参数值。若提供 param_values 则优先从中查找。"""
        from tools.parameters import DataColumnParam, FactorParam
        factor = None

        if param_values is not None and self.param.alias in param_values:
            value = param_values[self.param.alias]
        else:
            value = self.param.default_value
        if isinstance(self.param, DataColumnParam):
            resolved: FactorExpr = ColumnRef(DataColumn(value))
        elif isinstance(self.param, FactorParam):
            from tools.factors.factor_param_resolution import resolve_factor_param_expr
            value, factor = resolve_factor_param_expr(value)
            if value is None:
                resolved = ConstExpr(None)
            else:
                resolved = value
                if not isinstance(resolved, FactorExpr):
                    raise TypeError(f"参数 {self.param.alias} 需要 FactorExpr，收到 {type(value).__name__}")
                resolved = resolved.resolve(param_values=param_values, *args, **kwargs)
        else:
            resolved = ConstExpr(value)

        if self._is_intermediate:
            resolved = resolved.as_intermediate(self._intermediate_name, factor=factor)
        return resolved

    @property
    def op_name(self) -> str:
        return f"${{{self.param.alias}}}"

    def _to_latex(self, subst: dict | None = None) -> str:
        """LaTeX 变量名。ParamRef 的参数名作为基础变量，如 'P' → P_t。"""
        sk = self._structural_key()
        if subst is not None and sk in subst:
            return f"{subst[sk]}_t"
        param_latex = self._parameter_latex()
        from tools.parameters import DataColumnParam, FactorParam
        if isinstance(self.param, (DataColumnParam, FactorParam)):
            return f"{param_latex}_{{t}}"
        return param_latex

    def _parameter_latex(self) -> str:
        # Parameter aliases are identifiers, not LaTeX math delimiters.
        alias = str(self.param.alias).replace('$', r'\$')
        return f"\\textcolor{{red}}{{{alias}}}"

    def _get_alias(self) -> str:
        return f"P{self.param.alias}"

    def _structural_key(self) -> tuple:
        return ('ParamRef', self.param.alias)

class ConstExpr(FactorExpr):
    """
    常量表达式 — 标量、固定值或窗口/位移参数的叶子节点。

    当 value 是 int/float/ndarray 时 → 参与表达式运算，evaluate() 返回 self
    （由 CompositeExpr._apply_op 提取 .value 后内联处理）。

    当 value 是 pd.Timedelta/DataFreq 时 → 窗口/位移参数，
    evaluate() 直接返回 bar 数（int）。
    """

    def __init__(self, value: Any):
        self.value = value

    @property
    def is_leaf_ref(self) -> bool:
        return True

    def _evaluate(self, ctx: EvaluateContext) -> Any:
        return self.value

    @property
    def op_name(self) -> str:
        return f"const({self.value})"

    def _to_latex(self, subst: dict | None = None) -> str:
        sk = self._structural_key()
        if subst is not None and sk in subst:
            return f"{subst[sk]}_t"
        return _format_latex_value(self.value)

    def _get_alias(self) -> str:
        v = self.value
        if isinstance(v, (int, float)):
            return str(v).replace('.', 'd').replace('-', 'N')
        return 'const'

    def _structural_key(self) -> tuple:
        v = self.value
        if isinstance(v, np.ndarray):
            return ('ConstExpr', 'ndarray', str(v.dtype), tuple(v.shape), v.tobytes())
        return ('ConstExpr', v)


# ═════════════════════════════════════════════════════════════════════════════
# 辅助：将标量/ndarray 转为 ConstExpr
# ═════════════════════════════════════════════════════════════════════════════

def _to_expr(value: Any) -> FactorExpr:
    """将非 FactorExpr 值包装为 ConstExpr，将 Parameter 转为 ParamRef。"""
    if isinstance(value, FactorExpr):
        return value
    from tools.parameters.Parameter import Parameter
    if isinstance(value, Parameter):
        return ParamRef(value)
    return ConstExpr(value)  # type: ignore[arg-type]


# ═════════════════════════════════════════════════════════════════════════════
# Layer 4: 滚动窗口算子
# ═════════════════════════════════════════════════════════════════════════════

# ═════════════════════════════════════════════════════════════════════════════
# RollingExpr (方案 B) — 惰性滚动窗口表达式节点
# ═════════════════════════════════════════════════════════════════════════════
