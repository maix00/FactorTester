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

from tools.data.DataColumn import DataColumn
from tools.data.DataFreq import DataFreq

if TYPE_CHECKING:
    from tools.products.Product import Product
    from tools.data.DataSource import DataSource
    from tools.data.DataMeta import DataMeta
    from tools.parameters.Parameter import Parameter


from .core import FactorExpr, EvaluateContext
from .operands import OperandExpr
from .leaf import ConstExpr, _to_expr
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
            products=[p for p in ctx.products if p in operand_val.columns])

        # ── 同会话密集面板或没有 timeline → 标准 pandas shift ──
        timeline = ctx.panel_timeline
        use_fast_path = (
            timeline is None
            or timeline.dense_same_session
            or (timeline.schedule_complete and timeline.same_session)
        )
        if use_fast_path:
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

        # ── 异步会话面板 → session-aware shift ──
        # 只支持纯整数 bar 的 shift（日内）/ 或已解析为 common_periods 的 shift
        # 整日/混合窗口解析后 product_periods 不同时走 per-product 分支
        from .timeline import shift_positions

        if common:
            lookups = shift_positions(timeline, int(common_periods), operand_val)
        else:
            lookups = pd.DataFrame(-1, index=operand_val.index, columns=operand_val.columns, dtype=int)
            for periods, products_group in [
                (p, [pr for pr, pd_val in product_periods.items() if pd_val == p])
                for p in set(product_periods.values())
            ]:
                sub = operand_val[products_group]
                sub_lookups = shift_positions(timeline, int(periods), sub)
                for col in sub.columns:
                    lookups[col] = sub_lookups[col]

        result = pd.DataFrame(np.nan, index=operand_val.index, columns=operand_val.columns)
        arr = operand_val.to_numpy(dtype=float)
        lookup_arr = lookups.to_numpy(dtype=int)
        rows = np.arange(len(result.index))
        for j in range(len(result.columns)):
            valid = lookup_arr[:, j] >= 0
            result.iloc[valid, j] = arr[lookup_arr[valid, j], j]

        return result

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
        operand_base = _strip_latex_time_subscript(operand_latex)
        if _is_zero_shift_period(self.periods):
            return f"{operand_base}_{{t}}"
        p_label = self.periods._to_latex(subst) if isinstance(self.periods, FactorExpr) else str(self.periods)
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


