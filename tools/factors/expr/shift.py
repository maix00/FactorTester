# =============================================================================
# tools/factors/expr/shift.py
# 因子表达式系统 — 从 FactorExpr.py 拆分
# =============================================================================
from __future__ import annotations

import numpy as np
import pandas as pd
import threading
from typing import (
    TYPE_CHECKING, Any, Callable, Dict, Iterator, List, NamedTuple,
    Optional, Sequence, Set, Tuple, Union, cast
)

from tools.data.types import DataColumn
from tools.data.types import DataFreq

if TYPE_CHECKING:
    from tools.products.Product import Product
    from tools.data.providers import DataProviderProductTS as DataSource
    from tools.data.views.ProductDataView import ProductDataView
    from tools.parameters.Parameter import Parameter


from .core import FactorExpr, EvaluateContext
from .operands import OperandExpr
from .leaf import ConstExpr, ColumnRef, ParamRef, _to_expr
from .rolling import _resolve_windows

class ShiftOp(OperandExpr):
    """
    位移算子：SHIFT(periods, x) 即前 N 期的 x 值。

    operands = (periods, operand)
    periods 是第一 operand（ConstExpr 或 ParamRef），operand 是第二 operand。
    """

    def __init__(self, op: str, periods: Union[int, str, pd.Timedelta, 'Parameter', 'FactorExpr'],
                 operand: 'FactorExpr'):
        super().__init__(op, _to_expr(periods), operand)

    @property
    def periods(self) -> 'FactorExpr':
        return self.operands[0]

    @property
    def operand(self) -> 'FactorExpr':
        return self.operands[1]

    # ── evaluate：覆盖 OperandExpr 默认实现 ──

    def _evaluate(self, ctx: EvaluateContext) -> pd.DataFrame:

        # 先求 operand（DataFrame）
        operand_val = self.operands[1].evaluate(ctx=ctx)

        periods_expr = self.operands[0]
        if not isinstance(periods_expr, ConstExpr):
            periods_val = periods_expr.evaluate(ctx=ctx)
        else:
            periods_val = periods_expr.value
        common, common_periods, product_periods = _resolve_windows(
            window=periods_val, freq=ctx.freq,
            products=[p for p in ctx.products if p in operand_val.columns],
            allow_zero=True,
            allow_negative=True,
        )

        # 同交易位置的面板沿用 master 的固定行数语义。
        timeline = ctx.panel_timeline
        if timeline is None or timeline.same_session:
            if common:
                result = operand_val.shift(int(common_periods))
            else:
                unique_periods = set(product_periods.values())
                periods_products_map = {
                    p: [product for product, period in product_periods.items() if period == p]
                    for p in unique_periods
                }
                result_parts = []
                for p, products_group in periods_products_map.items():
                    result_parts.append(operand_val[products_group].shift(int(p)))
                result = pd.concat(result_parts, axis=1)
            return result

        # 异步面板使用初始 observed mask 压紧；union 对齐插入的行不计作本品种 bar。
        from .timeline import compact_observed, scatter_observed

        packed, ordinals, observed = compact_observed(operand_val, timeline)
        if common:
            shifted = packed.shift(int(common_periods))
        else:
            shifted = pd.DataFrame(np.nan, index=packed.index, columns=packed.columns)
            for periods in set(product_periods.values()):
                columns = [
                    product for product, value in product_periods.items()
                    if value == periods and product in packed.columns
                ]
                if columns:
                    shifted[columns] = packed[columns].shift(int(periods))
        return scatter_observed(shifted, operand_val, ordinals, observed)

    # ── 展示方法 ──

    @property
    def op_name(self) -> str:
        p = self.periods
        label = str(p.value) if isinstance(p, ConstExpr) else str(p)
        return f"SHIFT_{label}"

    def _to_latex(self, subst: dict | None = None) -> str:
        sk = self._structural_key()
        if subst is not None and sk in subst:
            return f"{subst[sk]}_t"
        operand_latex = self.operand._to_latex(subst)
        if _is_zero_shift_period(self.periods):
            return operand_latex
        p_label = self.periods._to_latex(subst)
        # Only a leaf (or a named intermediate) has a replaceable time index.
        # Stripping a suffix from a sum would shift only its final operand;
        # appending a subscript to a nested shift would create double indices.
        named = subst is not None and self.operand._structural_key() in subst
        indexed_leaf = isinstance(self.operand, (ColumnRef, ParamRef)) or named
        operand_base = _strip_latex_time_subscript(operand_latex)
        if not indexed_leaf or operand_base == operand_latex:
            return f"\\operatorname{{Shift}}_{{{p_label}}}\\left({operand_latex}\\right)"
        from .composite import CompositeExpr
        # Reuse subtraction's RHS precedence rules for the synthetic t - p.
        subtraction = CompositeExpr('sub', self.operand, self.periods)
        p_label = subtraction._binary_operand_latex(
            self.periods, p_label, side='right', subst=subst,
        )
        if p_label.startswith('-'):
            p_label = f"\\left({p_label}\\right)"
        return f"{operand_base}_{{t - {p_label}}}"

    def _get_alias(self) -> str:
        p_expr = self.periods
        p = str(p_expr.value) if isinstance(p_expr, ConstExpr) else str(p_expr).replace(' ', '')
        return f"shift_{self.operand._get_alias()}_{p}"


def _is_zero_shift_period(periods: 'FactorExpr') -> bool:
    if not isinstance(periods, ConstExpr):
        return False
    value = periods.value
    if value == 0:
        return True
    try:
        return pd.Timedelta(value) == pd.Timedelta(0)
    except Exception:
        return False


def _strip_latex_time_subscript(latex: str) -> str:
    """
    Remove a trailing time subscript from a LaTeX fragment.

    Historically some leaf nodes emitted `_t` while others emitted `_{t}`.
    For operators like SHIFT that need to *replace* the time index, we must
    normalize both forms to avoid MathJax "Double subscripts" errors
    (e.g. `\\tilde{O}_t_{t-N}`).
    """
    if latex.endswith('_{t}'):
        return latex[:-len('_{t}')]
    if latex.endswith('_t'):
        return latex[:-len('_t')]
    return latex
