"""Emit the bridge plan JSON from the existing tools.factors expression API.

This is the compatibility path: factor-family code keeps using
``tools.factors`` while the same graph can be handed to the Rust bridge.
"""

from __future__ import annotations

import pandas as pd

from typing import Any

from tools.factors.expr.bar_search import BarDistanceOp, BarSinceOp
from tools.factors.expr.composite import CompositeExpr
from tools.factors.expr.conditional import WhereOp
from tools.factors.expr.cross_sectional import CrossSectionalOp
from tools.factors.expr.groupby_scope import GroupByScopeOp
from tools.factors.expr.leaf import CategoryBoolRef, ColumnRef, ConstExpr
from tools.factors.expr.lookback_scope import BarCountScope
from tools.factors.expr.rolling import RollingOp
from tools.factors.expr.shift import ShiftOp
from tools.factors.expr.signal_align import SignalAlign

_BINARY = {"add", "sub", "mul", "div", "gt", "lt", "ge", "le", "eq", "ne"}
_UNARY = {"abs", "sign", "sqrt", "log", "tanh"}


def alpha_plan_spec(expression: Any, *, source_freq=None, products=(), session_calendar=None) -> dict[str, Any] | None:
    columns: list[str] = []
    nodes: list[dict[str, Any]] = []
    keys: list[str] = []
    key_tuples: list[tuple] = []
    memo: dict[tuple, int] = {}

    def build(expr) -> int | None:
        key = expr._structural_key()
        if key in memo:
            return memo[key]
        if isinstance(expr, CategoryBoolRef) and products:
            node = {"kind": "product", "values": [
                1.0 if expr.category.is_in_category(expr.category_name, product) else 0.0
                for product in products
            ]}
        elif isinstance(expr, ColumnRef):
            name = expr.column.name
            if name not in columns:
                columns.append(name)
            node = {"kind": "column", "index": columns.index(name)}
        elif isinstance(expr, ConstExpr):
            node = {"kind": "const", "value": float(expr.value)}
        elif isinstance(expr, RollingOp):
            if expr._n_data != 1:
                return None
            if expr.trunc_start is not None or expr.trunc_end is not None:
                return None
            window = expr.window
            if isinstance(window, ConstExpr) and isinstance(window.value, int):
                window_count = int(window.value)
            elif type(window).__name__ == "WindowBarsExpr" and source_freq is not None and products:
                from tools.factors.expr.rolling import _resolve_windows
                value = window.window.value
                if session_calendar is not None and isinstance(value, str) and value.strip().lower().endswith("d"):
                    lookback = int(value.strip().lower().removesuffix("d"))
                    sessions = [
                        [int(item.start_ns), int(item.end_ns), int(item.bar_count)]
                        for item in session_calendar.sessions
                    ]
                    if not sessions or any(item[2] <= 0 for item in sessions):
                        return None
                    child = build(expr.operands[expr._data_start])
                    if child is None:
                        return None
                    op, _, q = expr.op.partition(":") if ":" in expr.op else (expr.op, "", "")
                    op = op.removeprefix("rolling_")
                    node = {
                        "kind": "session_rolling", "child": child,
                        "lookback_sessions": lookback, "sessions": sessions,
                        "op": op, "min_periods": expr._min_periods_value(1),
                        "propagate_nan": expr.nan_policy.value == "propagate",
                    }
                    memo[key] = len(nodes); keys.append(repr(key)); key_tuples.append(key); nodes.append(node)
                    return memo[key]
                common, window_count, _ = _resolve_windows(value, source_freq, products)
                if not common:
                    return None
            else:
                return None
            child = build(expr.operands[expr._data_start])
            if child is None:
                return None
            op, _, q = expr.op.partition(":") if ":" in expr.op else (expr.op, "", "")
            op = op.removeprefix("rolling_")
            node = {
                "kind": "rolling", "child": child, "window": window_count,
                "op": op, "min_periods": expr._min_periods_value(window_count),
                "propagate_nan": expr.nan_policy.value == "propagate",
            }
            if op == "quantile":
                node["quantile"] = float(expr.quantile)
        elif isinstance(expr, GroupByScopeOp):
            if not isinstance(expr.scope, BarCountScope):
                return None
            if expr.op.startswith("quantile"):
                return None
            child = build(expr.operands[0])
            if child is None:
                return None
            node = {
                "kind": "scope", "child": child, "count": int(expr.scope.resolved_count()),
                "op": expr.op, "min_periods": expr.min_periods or 1,
                "propagate_nan": expr.nan_policy.value == "propagate",
            }
        elif isinstance(expr, SignalAlign):
            if expr.daily_basepoint is not None or expr.end_session_skip:
                return None
            if str(expr.signal_freq).lower() in {"1d", "1day", "daily"}:
                return None
            if not isinstance(expr.basepoint, str) or expr.basepoint not in {"last", "first"}:
                return None
            child = build(expr.operands[0])
            if child is None:
                return None
            node = {
                "kind": "signal", "child": child,
                "signal_ns": int(pd.Timedelta(str(expr.signal_freq)).value),
                "basepoint": expr.basepoint, "include_current": True,
                "partial": "drop", "scope_anchor": "start", "sessions": [],
            }
        elif isinstance(expr, CrossSectionalOp):
            if len(expr.operands) != 1:
                return None
            child = build(expr.operands[0])
            if child is None:
                return None
            node = {"kind": "cross", "child": child, "op": expr.op.removeprefix("cs_")}
        elif isinstance(expr, CompositeExpr):
            children = [build(item) for item in expr.operands]
            if any(child is None for child in children):
                return None
            if expr.op == "neg":
                node = {"kind": "neg", "child": children[0]}
            elif expr.op in _UNARY:
                node = {"kind": "unary", "op": expr.op, "child": children[0]}
            elif expr.op in _BINARY:
                node = {"kind": "binary", "op": expr.op, "left": children[0], "right": children[1]}
            else:
                return None
        elif isinstance(expr, ShiftOp):
            periods = expr.periods
            if not isinstance(periods, ConstExpr):
                return None
            child = build(expr.operand)
            if child is None:
                return None
            node = {"kind": "shift", "child": child, "periods": int(periods.value)}
        elif isinstance(expr, WhereOp):
            children = [build(item) for item in expr.operands]
            if any(child is None for child in children):
                return None
            node = {"kind": "where", "condition": children[0],
                    "when_true": children[1], "when_false": children[2]}
        elif isinstance(expr, BarDistanceOp):
            return None
        elif isinstance(expr, BarSinceOp):
            if not isinstance(expr.scope, BarCountScope):
                return None
            child = build(expr.condition)
            if child is None:
                return None
            default = expr.operands[-1]
            from tools.factors.expr.bar_search import ScopeLengthDefault
            default_scope = isinstance(default, ScopeLengthDefault)
            node = {
                "kind": "distance" if isinstance(expr, BarDistanceOp) else "since",
                "condition": child,
                "count": int(expr.scope.resolved_count()),
                "include_current": bool(expr.include_current),
                "nearest": expr.select == "nearest",
                "default_scope": default_scope,
                "default": 0.0 if default_scope else float(default.value),
            }
        else:
            return None
        memo[key] = len(nodes)
        keys.append(repr(key))
        key_tuples.append(key)
        nodes.append(node)
        return len(nodes) - 1

    output = build(expression)
    if output is None:
        return None
    return {"columns": columns, "keys": keys, "key_tuples": key_tuples,
            "nodes": nodes, "outputs": [output]}


def factor_alpha_plan_spec(factor: Any) -> dict[str, Any] | None:
    expression = getattr(factor, "_func_expr", None) or getattr(factor, "_expr", None)
    if expression is None:
        return None
    return alpha_plan_spec(expression)
