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

_BINARY = {"add": "+", "sub": "-", "mul": "*", "div": "/"}
_ROLLING = {"rolling_sum", "rolling_mean", "rolling_var", "rolling_std", "rolling_skew"}


class _PlanBuilder:
    def __init__(self) -> None:
        from alpha import BatchPlan

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
            if expr.op not in _ROLLING or expr._n_data != 1:
                return None
            window_expr = expr.window
            if not isinstance(window_expr, ConstExpr) or not isinstance(window_expr.value, (int, np.integer)):
                return None
            child = self.build(expr.operands[expr._data_start])
            if child is None:
                return None
            window = int(window_expr.value)
            node = self.plan.rolling(
                child, window, expr.op.removeprefix("rolling_"),
                expr._min_periods_value(window),
                expr.nan_policy.value == "propagate",
            )
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


def try_evaluate_rust_plan(expression: FactorExpr, ctx: EvaluateContext) -> pd.DataFrame | None:
    """Return a DataFrame when the whole graph has a Rust batch plan."""
    if ctx.panel_timeline is not None:
        return None
    if isinstance(expression, (ColumnRef, ConstExpr)):
        return None
    builder = _PlanBuilder()
    output = builder.build(expression)
    if output is None:
        return None
    if not builder.columns:
        return None
    frames = [ref.evaluate(ctx=ctx) for ref in builder.columns]
    if not frames or not isinstance(frames[0], pd.DataFrame):
        return None
    index = frames[0].index
    products = [p for p in ctx.products if p in frames[0].columns]
    if not products:
        return None
    result = {}
    for product in products:
        arrays = []
        for frame in frames:
            if product not in frame.columns:
                return None
            arrays.append(np.ascontiguousarray(frame[product].to_numpy(dtype=float)))
        result[product] = builder.plan.execute(arrays, output)
    return pd.DataFrame(result, index=index)


def try_evaluate_rust_plan_many(
    expressions: list[FactorExpr], ctx: EvaluateContext,
) -> list[pd.DataFrame] | None:
    """Execute several factors through one shared Rust Plan DAG."""
    if ctx.panel_timeline is not None:
        return None
    if not expressions or any(isinstance(e, (ColumnRef, ConstExpr)) for e in expressions):
        return None
    builder = _PlanBuilder()
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
