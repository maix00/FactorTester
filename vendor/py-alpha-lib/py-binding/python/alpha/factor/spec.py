"""Serialize an alpha.factor graph into the bridge's Rust plan JSON."""

from __future__ import annotations

from typing import Any

import numpy as np

from .core import ColumnRef, CompositeExpr, ConstExpr, RollingOp, ShiftOp, WhereOp
from .cross_sectional import CrossSectionalExpr
from .scope import GroupByScopeOp
from .bar_search import BarSinceExpr, BarSinceExpr as BarSince

_BINARY = {"add", "sub", "mul", "div", "gt", "lt", "ge", "le", "eq", "ne"}


def to_plan_spec(expressions: list[Any]) -> dict[str, Any] | None:
    columns: list[str] = []
    nodes: list[dict[str, Any]] = []
    memo: dict[tuple, int] = {}

    def build(expr) -> int | None:
        key = expr._structural_key()
        if key in memo:
            return memo[key]
        if isinstance(expr, ColumnRef):
            if expr.column not in columns:
                columns.append(expr.column)
            node = {"kind": "column", "index": columns.index(expr.column)}
        elif isinstance(expr, ConstExpr):
            node = {"kind": "const", "value": float(expr.value)}
        elif isinstance(expr, RollingOp):
            child = build(expr.data)
            if child is None:
                return None
            op, _, q = expr.op.partition(":")
            node = {
                "kind": "rolling", "child": child, "window": expr.window,
                "op": op, "min_periods": expr.semantics.min_periods_for(op),
                "propagate_nan": expr.semantics.nan_policy.value == "propagate",
            }
            if q:
                node["quantile"] = float(q)
        elif isinstance(expr, GroupByScopeOp):
            child = build(expr.owner.data)
            if child is None:
                return None
            node = {
                "kind": "scope", "child": child,
                "count": expr.owner.scope.count,
                "op": expr.op, "min_periods": expr.owner.semantics.effective_min_periods,
                "propagate_nan": expr.owner.semantics.nan_policy.value == "propagate",
            }
        elif isinstance(expr, CrossSectionalExpr):
            child = build(expr.operand)
            if child is None:
                return None
            node = {"kind": "cross", "child": child, "op": expr.op.removeprefix("cs_")}
        elif isinstance(expr, CompositeExpr):
            children = [build(item) for item in expr.operands]
            if any(child is None for child in children):
                return None
            if expr.op == "neg":
                node = {"kind": "neg", "child": children[0]}
            elif expr.op in _BINARY:
                node = {"kind": "binary", "op": expr.op, "left": children[0], "right": children[1]}
            else:
                return None
        elif isinstance(expr, ShiftOp):
            child = build(expr.data)
            if child is None:
                return None
            node = {"kind": "shift", "child": child, "periods": expr.periods}
        elif isinstance(expr, WhereOp):
            children = [build(expr.condition), build(expr.when_true), build(expr.when_false)]
            if any(child is None for child in children):
                return None
            node = {"kind": "where", "condition": children[0],
                    "when_true": children[1], "when_false": children[2]}
        elif isinstance(expr, BarSince):
            child = build(expr.condition)
            if child is None:
                return None
            node = {"kind": "since", "condition": child, "count": expr.scope.count,
                    "include_current": bool(expr.include_current),
                    "nearest": expr.select == "nearest",
                    "default_scope": expr.default is None,
                    "default": 0.0 if expr.default is None else float(expr.default)}
        else:
            return None
        memo[key] = len(nodes)
        nodes.append(node)
        return len(nodes) - 1

    outputs = [build(expression) for expression in expressions]
    if any(output is None for output in outputs):
        return None
    return {"columns": columns, "nodes": nodes, "outputs": outputs}
