"""Compile the public alpha.factor graph to the Rust matrix BatchPlan."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class _Grid:
    id: int
    index: pd.Index
    positions: np.ndarray
    times: np.ndarray


@dataclass
class _Ref:
    id: int
    grid: _Grid
    columns: tuple
    scalar: bool = False


def _times(index):
    values = index
    if isinstance(values, pd.MultiIndex):
        values = values.get_level_values(-1)
    if isinstance(values, pd.DatetimeIndex):
        return np.ascontiguousarray(values.as_unit("ns").asi8)
    return np.arange(len(index), dtype=np.int64)


def _walk(expressions):
    seen = set()

    def visit(expr):
        key = expr._structural_key()
        if key in seen:
            return
        seen.add(key)
        yield expr
        children = list(getattr(expr, "operands", ()))
        for attribute in ("data", "operand", "owner", "condition", "when_true", "when_false"):
            child = getattr(expr, attribute, None)
            if child is not None and child not in children:
                children.append(child)
        for child in children:
            if hasattr(child, "_structural_key"):
                yield from visit(child)

    for expression in expressions:
        yield from visit(expression)


class _Builder:
    def __init__(self, expressions, ctx):
        from alpha import BatchPlan

        self.ctx = ctx
        self.plan = BatchPlan()
        self.inputs: list[np.ndarray] = []
        self.memo: dict[tuple, _Ref] = {}
        self.products = tuple(ctx.products)
        self.frames = {}
        for expr in _walk(expressions):
            if type(expr).__name__ == "ColumnRef":
                self.frames[expr._structural_key()] = expr._evaluate(ctx)
        if self.frames:
            self.index = next(iter(self.frames.values())).index
        elif ctx.preloaded:
            self.index = next(iter(ctx.preloaded.values())).index
        else:
            raise ValueError("alpha.factor plan requires a source timeline")
        self.observed = np.ones((len(self.products), len(self.index)), dtype=np.uint8)
        day_values = self.index
        if isinstance(day_values, pd.MultiIndex):
            day_values = day_values.get_level_values(0)
        if isinstance(day_values, pd.DatetimeIndex):
            day_values = day_values.normalize()
        self.days = pd.factorize(day_values, sort=False)[0].astype(np.int64)
        self.base = _Grid(
            self.plan.grid(
                _times(self.index), self.days,
                np.ascontiguousarray(self.observed).reshape(-1),
            ),
            self.index, np.arange(len(self.index), dtype=np.int64), _times(self.index),
        )

    def input(self, values):
        self.inputs.append(np.ascontiguousarray(values, dtype=float).reshape(-1))
        return len(self.inputs) - 1

    def add(self, op, children=(), params=(), indices=(), *, grid=None, scalar=False, columns=None):
        grid = self.base if grid is None else grid
        node = self.plan.add(
            op, [child.id for child in children], list(params), list(indices), grid.id,
        )
        return _Ref(node, grid, self.products if columns is None else tuple(columns), scalar)

    def build(self, expr) -> _Ref:
        key = expr._structural_key()
        if key in self.memo:
            return self.memo[key]
        from .core import ColumnRef, CompositeExpr, ConstExpr, RollingOp, ShiftOp, WhereOp
        from .cross_sectional import CrossSectionalExpr
        from .scope import GroupByScopeOp

        if isinstance(expr, ColumnRef):
            frame = self.frames.get(key)
            if frame is None:
                frame = expr._evaluate(self.ctx)
                self.frames[key] = frame
            frame = frame.reindex(index=self.index, columns=self.products)
            ref = self.add("column", params=[self.input(frame.to_numpy(dtype=float).T)])
        elif isinstance(expr, ConstExpr):
            ref = self.add("const", params=[expr.value], scalar=True, columns=())
        elif isinstance(expr, RollingOp):
            child = self.build(expr.data)
            op, _, q = expr.op.partition(":")
            ref = self.add(
                f"rolling:{op}", [child],
                [0, expr.window, 0, expr.semantics.min_periods_for(op),
                 float(expr.semantics.nan_policy.value == "propagate"),
                 float(q) if q else 0.5, -1.0, -1.0],
                columns=child.columns,
            )
        elif isinstance(expr, GroupByScopeOp):
            child = self.build(expr.owner.data)
            op, _, q = expr.op.partition(":")
            ref = self.add(
                f"scope:{op}", [child],
                [1, expr.owner.scope.count, 0,
                 expr.owner.semantics.effective_min_periods,
                 float(expr.owner.semantics.nan_policy.value == "propagate"),
                 float(q) if q else 0.5, -1.0, -1.0],
                columns=child.columns,
            )
        elif isinstance(expr, CrossSectionalExpr):
            child = self.build(expr.operand)
            priority = [i for i, _ in enumerate(self.products)]
            ref = self.add(
                "cross:" + expr.op.removeprefix("cs_"), [child], [], priority,
                columns=self.products,
            )
        elif isinstance(expr, CompositeExpr):
            children = [self.build(item) for item in expr.operands]
            ref = self.add(expr.op, children, columns=children[0].columns)
        elif isinstance(expr, WhereOp):
            ref = self.add(
                "where", [self.build(expr.condition), self.build(expr.when_true),
                          self.build(expr.when_false)],
            )
        elif isinstance(expr, ShiftOp):
            child = self.build(expr.data)
            ref = self.add("shift", [child], [expr.periods], columns=child.columns)
        else:
            return None
        self.memo[key] = ref
        return ref


def compile_plan(expressions, ctx):
    builder = _Builder(expressions, ctx)
    outputs = [builder.build(expr) for expr in expressions]
    if any(output is None for output in outputs):
        return None
    arrays = builder.plan.execute_panel(
        builder.inputs, [output.id for output in outputs], len(builder.products),
    )
    result = []
    for values, output in zip(arrays, outputs, strict=True):
        width = len(output.columns) or len(builder.products)
        frame = np.asarray(values, dtype=float).reshape(width, len(output.grid.index)).T
        result.append(pd.DataFrame(frame, index=output.grid.index, columns=output.columns))
    return result
