"""Compile a FactorExpr subgraph into the Rust BatchPlan executor.

Only operations with a Rust batch implementation are compiled.  Anything else
returns ``None`` so the regular Python evaluator remains the explicit fallback.
Intermediate values stay in Rust; only the input columns and final result cross
the Python boundary.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .core import EvaluateContext, FactorExpr
from .leaf import ColumnRef, ConstExpr
from .composite import CompositeExpr
from .rolling import RollingOp
from .conditional import WhereOp
from .shift import ShiftOp
from .groupby_scope import GroupByScopeOp
from .lookback_scope import BarCountScope

_BINARY = {"add": "+", "sub": "-", "mul": "*", "div": "/",
           "gt": "gt", "lt": "lt", "ge": "ge", "le": "le", "eq": "eq", "ne": "ne",
           "and": "and", "or": "or"}
_UNARY = {"neg", "abs", "sign", "sqrt", "log", "tanh", "not"}



class _PlanBuilder:
    def __init__(self, ctx=None) -> None:
        from alpha import BatchPlan

        self.ctx = ctx
        self.plan = BatchPlan()
        self.columns: list[ColumnRef] = []
        self.memo: dict[Any, int] = {}

    def build(self, expr: FactorExpr) -> int | None:
        key = expr._structural_key()
        if key in self.memo:
            return self.memo[key]
        if isinstance(expr, ColumnRef):
            for index, ref in enumerate(self.columns):
                if ref.column.name == expr.column.name:
                    return self.plan.column(index)
            self.columns.append(expr)
            node = self.plan.column(len(self.columns) - 1)
            self.memo[key] = node
            return node
        if isinstance(expr, ConstExpr):
            if not np.isscalar(expr.value):
                return None
            node = self.plan.constant(float(expr.value))
            self.memo[key] = node
            return node
        if isinstance(expr, RollingOp):
            if expr._n_data != 1:
                return None
            window_expr = expr.window
            if not isinstance(window_expr, ConstExpr) or not isinstance(window_expr.value, (int, np.integer)):
                return None
            child = self.build(expr.operands[expr._data_start])
            if child is None:
                return None
            window = int(window_expr.value)
            quantile = expr.quantile if expr.op == "rolling_quantile" else None
            node = self.plan.rolling(
                child, window, expr.op.removeprefix("rolling_"),
                expr._min_periods_value(window),
                expr.nan_policy.value == "propagate",
                quantile,
            )
            self.memo[key] = node
            return node
        if isinstance(expr, WhereOp):
            if len(expr.operands) != 3:
                return None
            condition = self.build(expr.operands[0])
            when_true = self.build(expr.operands[1])
            when_false = self.build(expr.operands[2])
            if condition is None or when_true is None or when_false is None:
                return None
            node = self.plan.where_node(condition, when_true, when_false)
            self.memo[key] = node
            return node
        if isinstance(expr, CompositeExpr) and expr.op in _UNARY and len(expr.operands) == 1:
            child = self.build(expr.operands[0])
            if child is None:
                return None
            node = self.plan.unary(expr.op, child)
            self.memo[key] = node
            return node
        if isinstance(expr, GroupByScopeOp):
            if not isinstance(expr.scope, BarCountScope) or expr._n_data != 1:
                return None
            child = self.build(expr.operands[0])
            if child is None:
                return None
            count = expr.scope.resolved_count(
                source_freq=getattr(self.ctx, "freq", None),
                products=getattr(self.ctx, "products", ()),
            )
            quantile = expr.quantile_value if expr.op == "quantile" else None
            if isinstance(quantile, ConstExpr):
                quantile = quantile.value
            node = self.plan.bar_scope(
                child, int(count), expr.op.removeprefix("rolling_"),
                expr.min_periods if expr.min_periods is not None else 1,
                expr.nan_policy.value == "propagate",
                None if quantile is None else float(quantile),
            )
            self.memo[key] = node
            return node
        if isinstance(expr, ShiftOp):
            periods = expr.periods
            if not isinstance(periods, ConstExpr) or not isinstance(periods.value, (int, np.integer)):
                return None
            child = self.build(expr.operand)
            if child is None or int(periods.value) < 0:
                return None
            node = self.plan.shift(child, int(periods.value))
            self.memo[key] = node
            return node
        if isinstance(expr, CompositeExpr):
            binary = _BINARY.get(expr.op)
            if binary is None or len(expr.operands) != 2:
                return None
            left = self.build(expr.operands[0])
            right = self.build(expr.operands[1])
            if left is None or right is None:
                return None
            node = self.plan.binary(binary, left, right)
            self.memo[key] = node
            return node
        return None


def evaluate_rust_plan(
    expressions: list[FactorExpr], ctx: EvaluateContext,
) -> list[pd.DataFrame] | None:
    """Execute several factors through one shared Rust Plan DAG."""
    if ctx.panel_timeline is not None and not ctx.panel_timeline.same_session:
        return None
    if not expressions or any(isinstance(e, (ColumnRef, ConstExpr)) for e in expressions):
        return None
    builder = _PlanBuilder(ctx)
    outputs = [builder.build(expression) for expression in expressions]
    if any(output is None for output in outputs):
        return None
    if not builder.columns:
        return None
    frames = [ref.evaluate(ctx=ctx) for ref in builder.columns]
    if not frames or not isinstance(frames[0], pd.DataFrame):
        return None
    products = [p for p in ctx.products if p in frames[0].columns]
    if not products:
        return None
    result: list[dict[Any, np.ndarray]] = [{} for _ in expressions]
    for product in products:
        arrays = [
            np.ascontiguousarray(frame[product].to_numpy(dtype=float))
            for frame in frames
        ]
        values = builder.plan.execute_many(arrays, [int(o) for o in outputs])
        for index, array in enumerate(values):
            result[index][product] = array
    return [pd.DataFrame(item, index=frames[0].index) for item in result]


def try_evaluate_rust_plan(expression: FactorExpr, ctx: EvaluateContext) -> pd.DataFrame | None:
    result = evaluate_rust_plan([expression], ctx)
    return None if result is None else result[0]




def plan_identity(expressions: list[FactorExpr]) -> tuple[tuple, ...]:
    """Stable node identity of the Rust batch plan for a factor collection."""
    builder = _PlanBuilder()
    for expression in expressions:
        builder.build(expression)
    return tuple(builder.memo.keys())


_PLAN_SUPPORTED = (
    ColumnRef, ConstExpr, RollingOp, CompositeExpr, WhereOp, ShiftOp,
    GroupByScopeOp,
)


def unsupported_plan_nodes(expression: FactorExpr) -> tuple[str, ...]:
    """Explicitly list node types that still require Python execution."""
    blockers: list[str] = []

    def visit(node: FactorExpr) -> None:
        if not isinstance(node, _PLAN_SUPPORTED):
            blockers.append(type(node).__name__)
            return
        if isinstance(node, GroupByScopeOp) and not isinstance(node.scope, BarCountScope):
            blockers.append(f"GroupByScopeOp({type(node.scope).__name__})")
            return
        for child in getattr(node, "_operands", ()):
            visit(child)

    visit(expression)
    return tuple(dict.fromkeys(blockers))
