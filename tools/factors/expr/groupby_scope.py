"""Scope-partitioned aggregation expressions (``groupby_scope``).

``rolling(K)`` slides a fixed-length window: at every bar it looks back K bars,
so ``rolling('1d')`` reaches across the trading-day boundary (1-minute bars,
255/day: a mid-afternoon bar would cover the previous day's tail).  This module
adds the missing aggregate over the **current partition** — the trading day, the
session, or every K bars — using only the current bar and earlier observations.

Typical use (研报口径)：

    Dur.groupby_scope(scope_trading_day()).truncate(0, 119).mean()   # 当日午前均值
    Dur.groupby_scope(scope_trading_day()).truncate(120, None).mean()  # 当日午后均值
    Dur.groupby_scope(scope_trading_day()).argmax()                 # 当日最稳定节点

LaTeX keeps the rolling symbol ``\\mathrm{R}`` and moves the scope to the
**superscript**: ``\\mathrm{R}^{\\text{trading\\_day}}``, or
``\\mathrm{R}^{\\text{trading\\_day},\\mathrm{trunc}(a,b)}`` with a truncation.
"""

from __future__ import annotations

from typing import Any, ClassVar, Optional, Sequence, Union

import pandas as pd

from .core import EvaluateContext, FactorExpr
from .groupby_scope_eval import GROUPED_AGGREGATIONS, apply_grouped
from .leaf import _to_expr
from .lookback_scope import BarCountScope, LookbackScope, SessionScope, TradingDayScope
from .operands import OperandExpr


def _bound_value(expr: Optional[FactorExpr], ctx: EvaluateContext) -> Optional[int]:
    """Resolve a truncation bound to an int (a constant or a scalar series)."""
    if expr is None:
        return None
    resolved = expr.evaluate(ctx=ctx)
    if isinstance(resolved, pd.DataFrame):
        if resolved.empty:
            return None
        value = resolved.iloc[-1, 0]
    else:
        value = resolved
    if pd.isna(value):
        return None
    return int(value)


def _scope_latex(scope: LookbackScope) -> str:
    if isinstance(scope, TradingDayScope):
        return r'\text{trading\_day}'
    if isinstance(scope, SessionScope):
        return r'\text{session}(' + str(scope.gap) + ')'
    if isinstance(scope, BarCountScope):
        return r'\text{bars}(K)'
    return r'\text{scope}'


class GroupByScopeExpr(FactorExpr):
    """Partition by a lookback scope; aggregate inside the current partition."""

    _AGG_OPS: ClassVar[frozenset[str]] = GROUPED_AGGREGATIONS

    def __init__(self, scope: LookbackScope, data: FactorExpr) -> None:
        self.scope = scope
        self._data = data

    @property
    def _operands(self) -> Sequence[FactorExpr]:
        return (self._data,)

    def _structural_extra(self) -> tuple:
        scope = self.scope
        return (
            type(self).__name__,
            type(scope).__name__,
            getattr(scope, 'gap', None),
        )

    def _make_grouped_op(self, agg: str, extra: Any = None) -> 'GroupByScopeOp':
        operands: list[FactorExpr] = [self._data]
        if extra is not None:
            operands.append(_to_expr(extra))
        if self.trunc_start is not None or self.trunc_end is not None:
            operands.append(self.trunc_start if self.trunc_start is not None else _to_expr(0))
            operands.append(self.trunc_end if self.trunc_end is not None else _to_expr(0))
        return GroupByScopeOp(agg, self.scope, *operands)

    # ── 聚合方法（与 rolling 同名，便于统一分发）──

    def mean(self) -> 'GroupByScopeOp':
        return self._make_grouped_op('mean')

    def std(self) -> 'GroupByScopeOp':
        return self._make_grouped_op('std')

    def var(self) -> 'GroupByScopeOp':
        return self._make_grouped_op('var')

    def min(self) -> 'GroupByScopeOp':
        return self._make_grouped_op('min')

    def max(self) -> 'GroupByScopeOp':
        return self._make_grouped_op('max')

    def sum(self) -> 'GroupByScopeOp':
        return self._make_grouped_op('sum')

    def median(self) -> 'GroupByScopeOp':
        return self._make_grouped_op('median')

    def quantile(self, q: Any) -> 'GroupByScopeOp':
        return self._make_grouped_op('quantile', q)

    def argmax(self) -> 'GroupByScopeOp':
        return self._make_grouped_op('argmax')

    def argmin(self) -> 'GroupByScopeOp':
        return self._make_grouped_op('argmin')

    def truncate(self, start: Any, end: Any) -> 'GroupByScopeExpr':
        """Restrict the aggregation to positions ``[start, end]`` **of the partition**."""
        result = GroupByScopeExpr(self.scope, self._data)
        result.trunc_start = _to_expr(start) if start is not None else None
        result.trunc_end = _to_expr(end) if end is not None else None
        return result

    trunc_start: Optional[FactorExpr] = None
    trunc_end: Optional[FactorExpr] = None

    def _get_alias(self) -> str:
        return 'groupby_scope'

    def _to_latex(self, subst: dict | None = None) -> str:
        sk = self._structural_key()
        if subst is not None and sk in subst:
            return f"{subst[sk]}_t"
        scope = _scope_latex(self.scope)
        start = self.trunc_start
        end = self.trunc_end
        if start is not None or end is not None:
            left = start._to_latex(subst) if isinstance(start, FactorExpr) else str(start)
            right = end._to_latex(subst) if isinstance(end, FactorExpr) else str(end)
            return (r'\mathrm{R}^{' + scope
                    + r',\mathrm{trunc}(' + left + ',' + right + ')}')
        return r'\mathrm{R}^{' + scope + '}'


class GroupByScopeOp(OperandExpr):
    """One aggregation over a scope partition.

    ``operands`` mirrors ``RollingOp``: ``(scope, *data, [trunc_start], [trunc_end])``
    so the structural key and the identity serialization stay consistent with the
    rest of the expression layer.
    """

    def __init__(self, op: str, scope: LookbackScope, *operands: FactorExpr) -> None:
        self.op = op
        self.scope = scope
        super().__init__(op, *operands)

    @property
    def _has_truncate(self) -> bool:
        return len(self.operands) >= 3

    @property
    def trunc_start(self) -> Optional[FactorExpr]:
        return self.operands[-2] if self._has_truncate else None

    @property
    def trunc_end(self) -> Optional[FactorExpr]:
        return self.operands[-1] if self._has_truncate else None

    @property
    def _data_start(self) -> int:
        return 0

    @property
    def _n_data(self) -> int:
        """数据操作数的个数（本算子恒为 1）。

        尾部可能挂截断的 start/end（两个），quantile 还会在数据之后挂一个 q；
        这两类都不是数据操作数。
        """
        trailing = (2 if self._has_truncate else 0) + (1 if self.op == "quantile" else 0)
        return len(self.operands) - trailing

    @property
    def quantile_value(self) -> Any:
        if self.op != 'quantile':
            return None
        index = self._data_start + self._n_data
        return self.operands[index] if index < len(self.operands) else None

    def _get_alias(self) -> str:
        return 'groupby_scope'

    def _structural_extra(self) -> tuple:
        scope = self.scope
        return (
            type(self).__name__, self.op, type(scope).__name__,
            str(getattr(scope, "gap", "")), getattr(scope, "count", None),
        )

    def _to_latex(self, subst: dict | None = None) -> str:
        sk = self._structural_key()
        if subst is not None and sk in subst:
            return f"{subst[sk]}_t"
        scope = _scope_latex(self.scope)
        start, end = self.trunc_start, self.trunc_end
        if start is not None or end is not None:
            left = start._to_latex(subst) if isinstance(start, FactorExpr) else str(start)
            right = end._to_latex(subst) if isinstance(end, FactorExpr) else str(end)
            return (r'\mathrm{R}^{' + scope
                    + r',\mathrm{trunc}(' + left + ',' + right + ')}')
        return r'\mathrm{R}^{' + scope + '}'

    def _allocate(self, *operands: FactorExpr) -> 'GroupByScopeOp':
        return type(self)(self.op, *operands)

    def _evaluate(self, ctx: EvaluateContext) -> pd.DataFrame:
        data_operand = self.operands[self._data_start]
        data = data_operand.evaluate(ctx=ctx)
        if not isinstance(data, pd.DataFrame):
            raise TypeError("groupby_scope data operand must evaluate to a DataFrame")
        quantile = None
        value = self.quantile_value
        if value is not None:
            resolved = value.evaluate(ctx=ctx)
            quantile = float(resolved.iloc[-1, 0]) if isinstance(resolved, pd.DataFrame) else float(resolved)
        return apply_grouped(
            self.op,
            self.scope,
            data,
            ctx=ctx,
            quantile=quantile,
            trunc_start=_bound_value(self.trunc_start, ctx),
            trunc_end=_bound_value(self.trunc_end, ctx),
        )
