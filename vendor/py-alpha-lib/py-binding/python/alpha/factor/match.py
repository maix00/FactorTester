"""CURRENT/CANDIDATE bar-search expressions for the public API."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .core import CompositeExpr, ConstExpr, FactorExpr, _to_expr
from .scope import BarCountScope

_BINARY = {"add", "sub", "mul", "div", "gt", "lt", "ge", "le", "eq", "ne"}
_UNARY = {"abs", "neg"}


class MatchValueRef(FactorExpr):
    def __init__(self, kind: str):
        self.kind = kind

    def _structural_key(self):
        return ("alpha.factor.MatchValueRef", self.kind)


CURRENT = MatchValueRef("current")
CANDIDATE = MatchValueRef("candidate")


def _predicate(expr) -> dict:
    if isinstance(expr, MatchValueRef):
        return {"op": expr.kind}
    if isinstance(expr, ConstExpr):
        return {"op": "const", "value": float(expr.value)}
    if isinstance(expr, CompositeExpr):
        if expr.op in _UNARY:
            return {"op": expr.op, "a": _predicate(expr.operands[0])}
        if expr.op in _BINARY:
            return {"op": expr.op, "a": _predicate(expr.operands[0]), "b": _predicate(expr.operands[1])}
    raise TypeError(f"unsupported match predicate node {type(expr).__name__}")


class MatchBarDistanceExpr(FactorExpr):
    def __init__(self, value, condition, scope: BarCountScope, *,
                 select: str = "nearest", default: float = 0.0,
                 include_current: bool = True):
        if select not in {"nearest", "farthest"}:
            raise ValueError("select must be nearest or farthest")
        self.value = _to_expr(value)
        self.condition = _to_expr(condition)
        self.scope = scope
        self.select = select
        self.default = float(default)
        self.include_current = include_current

    def _structural_key(self):
        return ("alpha.factor.MatchBarDistanceExpr", self.scope.count, self.select,
                self.default, self.include_current,
                self.value._structural_key(), self.condition._structural_key())

    def evaluate(self, ctx) -> pd.DataFrame:
        frame = self.value.evaluate(ctx)
        from .match import _truth
        out = {}
        for product in frame.columns:
            values = frame[product].to_numpy(dtype=float)
            result = np.full(len(values), self.default, dtype=float)
            for current in range(len(values)):
                if self.include_current and _truth(self.condition, values[current], values[current]):
                    result[current] = 0.0
                    continue
                candidates = range(max(0, current - self.scope.count), current)
                matches = [
                    current - position for position in candidates
                    if _truth(self.condition, values[current], values[position])
                ]
                if matches:
                    result[current] = min(matches) if self.select == "nearest" else max(matches)
            out[product] = result
        return pd.DataFrame(out, index=frame.index)


def _truth(expr, current: float, candidate: float) -> bool:
    if isinstance(expr, MatchValueRef):
        return (current if expr.kind == "current" else candidate) != 0.0
    if isinstance(expr, ConstExpr):
        return float(expr.value) != 0.0
    if isinstance(expr, CompositeExpr):
        if expr.op == "neg":
            return -_value(expr.operands[0], current, candidate) != 0.0
        if expr.op == "abs":
            return abs(_value(expr.operands[0], current, candidate)) != 0.0
        left = _value(expr.operands[0], current, candidate)
        right = _value(expr.operands[1], current, candidate)
        return {
            "add": left + right, "sub": left - right, "mul": left * right,
            "div": left / right, "gt": left > right, "lt": left < right,
            "ge": left >= right, "le": left <= right,
            "eq": left == right, "ne": left != right,
        }[expr.op] != 0.0
    raise TypeError(f"unsupported match predicate node {type(expr).__name__}")


def _value(expr, current: float, candidate: float) -> float:
    if isinstance(expr, MatchValueRef):
        return current if expr.kind == "current" else candidate
    if isinstance(expr, ConstExpr):
        return float(expr.value)
    if isinstance(expr, CompositeExpr):
        if expr.op == "neg":
            return -_value(expr.operands[0], current, candidate)
        if expr.op == "abs":
            return abs(_value(expr.operands[0], current, candidate))
        left = _value(expr.operands[0], current, candidate)
        right = _value(expr.operands[1], current, candidate)
        return {
            "add": left + right, "sub": left - right, "mul": left * right, "div": left / right,
            "gt": float(left > right), "lt": float(left < right),
            "ge": float(left >= right), "le": float(left <= right),
            "eq": float(left == right), "ne": float(left != right),
        }[expr.op]
    raise TypeError(f"unsupported match predicate node {type(expr).__name__}")


def bar_distance(value, condition, *, scope: BarCountScope, select: str = "nearest",
                 default: float = 0.0, include_current: bool = True) -> MatchBarDistanceExpr:
    return MatchBarDistanceExpr(value, condition, scope, select=select,
                                default=default, include_current=include_current)
