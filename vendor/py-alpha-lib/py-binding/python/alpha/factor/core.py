"""Public factor-definition API for py-alpha-lib.

This package owns FactorExpr, parameters and plan compilation.  It deliberately
does not import FactorTester domain objects (Product, DataColumn, RunSpec).
Data is supplied through a small EvalContext / preloaded panel contract.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence
from .semantics import NanPolicy, WindowSemantics

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class EvalContext:
    products: tuple[str, ...]
    freq: Any = None
    preloaded: Mapping[Any, pd.DataFrame] = field(default_factory=dict)
    cache: dict[Any, Any] = field(default_factory=dict)


class FactorExpr:
    _operands: tuple["FactorExpr", ...] = ()

    def evaluate(self, ctx: EvalContext) -> pd.DataFrame:
        return self._evaluate(ctx)

    def _structural_key(self) -> tuple:
        raise NotImplementedError

    def semantic_fingerprint(self) -> str:
        return hashlib.sha256(repr(self._structural_key()).encode()).hexdigest()

    def rolling(self, window: int) -> "RollingExpr":
        return RollingExpr(self, window)

    def shift(self, periods: int) -> "FactorExpr":
        return ShiftOp(periods, self)

    def neg(self) -> "FactorExpr":
        return CompositeExpr("neg", self)

    def __add__(self, other: Any) -> "FactorExpr":
        return CompositeExpr("add", self, _to_expr(other))

    def __sub__(self, other: Any) -> "FactorExpr":
        return CompositeExpr("sub", self, _to_expr(other))

    def __mul__(self, other: Any) -> "FactorExpr":
        return CompositeExpr("mul", self, _to_expr(other))

    def __truediv__(self, other: Any) -> "FactorExpr":
        return CompositeExpr("div", self, _to_expr(other))

    def __gt__(self, other: Any) -> "FactorExpr":
        return CompositeExpr("gt", self, _to_expr(other))

    def __lt__(self, other: Any) -> "FactorExpr":
        return CompositeExpr("lt", self, _to_expr(other))

    def where(self, condition: Any, other: Any = np.nan) -> "FactorExpr":
        return WhereOp(_to_expr(condition), self, _to_expr(other))


class ColumnRef(FactorExpr):
    def __init__(self, column: Any):
        self.column = str(getattr(column, "name", column))

    def _evaluate(self, ctx: EvalContext):
        frames = []
        for product in ctx.products:
            frame = ctx.preloaded.get(product)
            if frame is None:
                frame = ctx.preloaded.get((product, getattr(ctx.freq, "name", ctx.freq)))
            if frame is None or self.column not in frame.columns:
                raise KeyError(f"no preloaded column {self.column!r} for {product!r}")
            frames.append(frame[self.column].rename(product))
        return pd.concat(frames, axis=1)

    def evaluate(self, ctx: EvalContext) -> pd.DataFrame:
        return self._evaluate(ctx)

    def _structural_key(self):
        return ("alpha.factor.ColumnRef", self.column)


class ConstExpr(FactorExpr):
    def __init__(self, value: float):
        self.value = float(value)

    def evaluate(self, ctx: EvalContext) -> pd.DataFrame:
        if not ctx.preloaded:
            raise ValueError("constant expression needs at least one column context")
        frame = next(iter(ctx.preloaded.values()))
        return pd.DataFrame(
            self.value, index=frame.index, columns=list(ctx.products),
        )

    def _structural_key(self):
        return ("alpha.factor.ConstExpr", self.value)


def _to_expr(value: Any) -> FactorExpr:
    if isinstance(value, FactorExpr):
        return value
    if hasattr(value, "alias") and hasattr(value, "default_value"):
        return ParamRef(value)
    return ConstExpr(value)


class ParamRef(FactorExpr):
    def __init__(self, parameter: Any):
        self.parameter = parameter

    def resolve(self, values: Mapping[str, Any] | None = None) -> FactorExpr:
        value = None if values is None else values.get(self.parameter.alias)
        if value is None:
            value = self.parameter.default_value
        return _to_expr(value)

    def evaluate(self, ctx: EvalContext) -> pd.DataFrame:
        return self.resolve().evaluate(ctx)

    def _structural_key(self):
        return ("alpha.factor.ParamRef", self.parameter.alias)


class RollingExpr(FactorExpr):
    def __init__(self, data: FactorExpr, window: int):
        self.data = data
        self.window = int(window)

    def semantics(self, *, min_periods: int | None = None,
                  nan_policy: NanPolicy = NanPolicy.PROPAGATE) -> "RollingExpr":
        result = RollingExpr(self.data, self.window)
        result._semantics = WindowSemantics(self.window, min_periods, nan_policy)
        return result

    def _op(self, name: str) -> "RollingOp":
        return RollingOp(
            name, self.data, self.window,
            getattr(self, "_semantics", WindowSemantics(self.window)),
        )

    def mean(self): return self._op("mean")
    def sum(self): return self._op("sum")
    def std(self): return self._op("std")
    def var(self): return self._op("var")
    def min(self): return self._op("min")
    def max(self): return self._op("max")
    def ema(self): return self._op("ema")
    def median(self): return self._op("median")
    def quantile(self, q): return self._op(f"quantile:{float(q)}")
    def mad(self): return self._op("mad")
    def shift(self, periods): return self.data.shift(periods)


class RollingOp(FactorExpr):
    def __init__(self, op: str, data: FactorExpr, window: int,
                 semantics: WindowSemantics | None = None):
        self.op = op
        self.data = data
        self.window = int(window)
        self.semantics = semantics or WindowSemantics(self.window)

    def _structural_key(self):
        return ("alpha.factor.RollingOp", self.op, self.window,
                self.semantics.min_periods, self.semantics.nan_policy.value,
                self.data._structural_key())

    def _evaluate(self, ctx: EvalContext) -> pd.DataFrame:
        frame = self.data.evaluate(ctx)
        from alpha import interval_rolling
        from numpy import arange, maximum, uint64
        op, _, q = self.op.partition(":")
        quantile = float(q) if q else None
        min_periods = self.semantics.min_periods_for(op)
        propagate = self.semantics.nan_policy is NanPolicy.PROPAGATE
        out = {}
        for product in frame.columns:
            values = frame[product].to_numpy(dtype=float)
            ordinals = arange(len(values), dtype=uint64)
            starts = maximum(0, ordinals.astype("int64") - self.window + 1).astype(uint64)
            if op == "ema":
                from alpha import interval_ema
                out[product] = interval_ema(values, self.window, min_periods, propagate)
            else:
                out[product] = interval_rolling(
                    values, starts, ordinals, op, quantile, self.window,
                    min_periods, propagate,
                )
        return pd.DataFrame(out, index=frame.index)


class CompositeExpr(FactorExpr):
    def __init__(self, op: str, *operands: FactorExpr):
        self.op = op
        self.operands = tuple(operands)

    def _structural_key(self):
        return ("alpha.factor.CompositeExpr", self.op,
                tuple(o._structural_key() for o in self.operands))

    def _evaluate(self, ctx: EvalContext) -> pd.DataFrame:
        values = [operand.evaluate(ctx) for operand in self.operands]
        left = values[0]
        if self.op == "neg":
            return -left
        right = values[1]
        return {
            "add": lambda: left + right, "sub": lambda: left - right,
            "mul": lambda: left * right, "div": lambda: left / right,
            "gt": lambda: left > right, "lt": lambda: left < right,
        }[self.op]()


class ShiftOp(FactorExpr):
    def __init__(self, periods: int, data: FactorExpr):
        self.periods = int(periods)
        self.data = data

    def _structural_key(self):
        return ("alpha.factor.ShiftOp", self.periods, self.data._structural_key())

    def _evaluate(self, ctx: EvalContext) -> pd.DataFrame:
        return self.data.evaluate(ctx).shift(self.periods)


class WhereOp(FactorExpr):
    def __init__(self, condition: FactorExpr, when_true: FactorExpr, when_false: FactorExpr):
        self.condition = condition
        self.when_true = when_true
        self.when_false = when_false

    def _structural_key(self):
        return ("alpha.factor.WhereOp", self.condition._structural_key(),
                self.when_true._structural_key(), self.when_false._structural_key())

    def _evaluate(self, ctx: EvalContext) -> pd.DataFrame:
        condition = self.condition.evaluate(ctx)
        return self.when_true.evaluate(ctx).where(condition != 0, self.when_false.evaluate(ctx))
