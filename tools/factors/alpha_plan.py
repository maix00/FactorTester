"""Emit the bridge plan JSON from the existing tools.factors expression API.

This is the compatibility path: factor-family code keeps using
``tools.factors`` while the same graph can be handed to the Rust bridge.
"""

from __future__ import annotations

import pandas as pd

from typing import Any

from tools.factors.expr.bar_search import BarDistanceOp, BarSinceOp, ScopeLengthDefault
from tools.factors.expr.composite import CompositeExpr
from tools.factors.expr.conditional import WhereOp
from tools.factors.expr.cross_sectional import CrossSectionalOp
from tools.factors.expr.groupby_scope import GroupByScopeOp
from tools.factors.expr.leaf import CategoryBoolRef, ColumnRef, ConstExpr
from tools.factors.expr.lookback_scope import BarCountScope, SessionScope, TradingDayScope
from tools.factors.expr.rolling import IntervalBarsExpr, RollingOp, WindowBarsExpr, _resolve_windows
from tools.factors.expr.shift import ShiftOp
from tools.factors.expr.term_structure import TermStructureOp
from tools.factors.expr.match_refs import MatchValueRef
from tools.factors.expr.signal_align import SignalAlign

_BINARY = {"add", "sub", "mul", "div", "gt", "lt", "ge", "le", "eq", "ne"}
_UNARY = {"abs", "sign", "sqrt", "log", "tanh"}


def _match_predicate(expr, external=None) -> dict:
    if isinstance(expr, MatchValueRef):return {"op":expr.role}
    if isinstance(expr, ConstExpr):
        import math
        value=float(expr.value)
        return {"op":"const","value":None if math.isnan(value) else value}
    if isinstance(expr,WhereOp):
        c,a,b=[_match_predicate(x,external) for x in expr.operands]
        return dict(op='where',condition=c,when_true=a,when_false=b)
    from tools.factors.expr.pointwise import POINTWISE_OPS
    if type(expr) is CompositeExpr and expr.op in POINTWISE_OPS:
        args=[_match_predicate(x,external) for x in expr.operands]
        op={'bimax':'max','bimin':'min'}.get(expr.op,expr.op)
        if len(args)==1:return dict(op='unary',kind=op,a=args[0])
        result=args[0]
        for child in args[1:]:result=dict(op='binary',kind=op,a=result,b=child)
        return result
    if external is not None:return dict(op='input',index=external(expr))
    raise TypeError(f"unsupported match node {type(expr).__name__}")


def alpha_plan_spec(expression: Any, *, source_freq=None, products=(), session_calendar=None) -> dict[str, Any] | None:
    columns: list[str] = []
    boundaries: list[str] = []
    term_columns: list[str] = []
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
        elif isinstance(expr, TermStructureOp):
            near, far, depth, column = expr._term_param_values()
            if column not in term_columns:
                term_columns.append(column)
            node = {"kind": "term", "op": expr.op, "near_rank": near,
                    "far_rank": far, "depth": depth, "column": term_columns.index(column)}
        elif isinstance(expr, IntervalBarsExpr):
            node = {"kind": "bar_count", "start_ns": expr.start_ns, "end_ns": expr.end_ns}
        elif isinstance(expr, WindowBarsExpr):
            if source_freq is None or not isinstance(expr.window, ConstExpr):
                return None
            common, count, _ = _resolve_windows(expr.window.value, source_freq, products)
            if not common:
                return None
            node = {"kind": "const", "value": float(count)}
        elif isinstance(expr, RollingOp):
            if expr._n_data != 1:
                return None
            child = build(expr.operands[expr._data_start])
            if child is None:
                return None
            window = expr.window
            if isinstance(window, ConstExpr) and isinstance(window.value, int):
                window_count = int(window.value)
            elif source_freq is not None and products and (
                isinstance(window, WindowBarsExpr) or isinstance(window, ConstExpr) and isinstance(window.value,(str,pd.Timedelta))
            ):
                value = window.window.value if isinstance(window,WindowBarsExpr) else window.value
                if session_calendar is not None and isinstance(value,(str,pd.Timedelta)) and pd.Timedelta(value)>=pd.Timedelta(days=1):
                    duration=pd.Timedelta(value)
                    if duration % pd.Timedelta(days=1):raise ValueError("session window must contain whole trading days")
                    lookback=int(duration / pd.Timedelta(days=1))
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
                        "op": op, "quantile": expr.quantile, "min_periods": expr._min_periods_value(1),
                        "propagate_nan": expr.nan_policy.value == "propagate",
                    }
                    memo[key] = len(nodes); keys.append(repr(key)); key_tuples.append(key); nodes.append(node)
                    return memo[key]
                common, window_count, per_product = _resolve_windows(value, source_freq, products)
                if not common:
                    if not per_product:
                        return None
                    windows = [int(per_product[product]) for product in products]
                    op, _, q = expr.op.partition(":") if ":" in expr.op else (expr.op, "", "")
                    op = op.removeprefix("rolling_")
                    node = {
                        "kind": "rolling_dynamic", "child": child, "windows": windows,
                        "op": op, "quantile": expr.quantile, "min_periods": 1,
                        "propagate_nan": expr.nan_policy.value == "propagate",
                    }
                    memo[key] = len(nodes); keys.append(repr(key)); key_tuples.append(key); nodes.append(node)
                    return memo[key]
            else:
                return None
            child = build(expr.operands[expr._data_start])
            if child is None:
                return None
            op, _, q = expr.op.partition(":") if ":" in expr.op else (expr.op, "", "")
            op = op.removeprefix("rolling_")
            trunc = []
            trunc_children = []
            for value in (expr.trunc_start, expr.trunc_end):
                if value is None:
                    trunc.append(-1); trunc_children.append(None)
                elif isinstance(value, ConstExpr) and isinstance(value.value, int):
                    trunc.append(int(value.value)); trunc_children.append(None)
                else:
                    child_index = build(value)
                    if child_index is None:
                        return None
                    trunc.append(-1); trunc_children.append(child_index)
            node = {
                "kind": "rolling", "child": child, "window": window_count,
                "op": op, "min_periods": expr._min_periods_value(window_count),
                "propagate_nan": expr.nan_policy.value == "propagate",
                "trunc_start": trunc[0], "trunc_end": trunc[1],
                "trunc_start_child": trunc_children[0], "trunc_end_child": trunc_children[1],
            }
            if op == "quantile":
                node["quantile"] = float(expr.quantile)
        elif isinstance(expr, GroupByScopeOp):
            if isinstance(expr.scope, (SessionScope, TradingDayScope)) and (
                session_calendar is None or isinstance(expr.scope, SessionScope)
            ):
                if expr.trunc_start is not None or expr.trunc_end is not None :
                    return None
                child = build(expr.operands[0])
                if child is None:
                    return None
                event = "trading_day_start" if isinstance(expr.scope, TradingDayScope) else "trading_session_start"
                boundary_key = ("event_boundary", event)
                if boundary_key not in memo:
                    if event not in boundaries:
                        boundaries.append(event)
                    memo[boundary_key] = len(nodes)
                    nodes.append({"kind": "boundary", "index": boundaries.index(event)})
                    keys.append(repr(boundary_key)); key_tuples.append(boundary_key)
                node = {
                    "kind": "session_reset", "child": child, "boundary": memo[boundary_key],
                    "op": expr.op, "min_periods": expr.min_periods or 1,
                    "propagate_nan": expr.nan_policy.value == "propagate",
                }
            elif isinstance(expr.scope, TradingDayScope) and session_calendar is not None:
                sessions = [[int(item.start_ns), int(item.end_ns), int(item.bar_count)]
                            for item in session_calendar.sessions]
                if not sessions or any(item[2] <= 0 for item in sessions):
                    return None
                child = build(expr.operands[0])
                if child is None :
                    return None
                node = {
                    "kind": "session_rolling", "child": child, "lookback_sessions": 1,
                    "sessions": sessions, "op": expr.op,
                    "min_periods": expr.min_periods or 1,
                    "propagate_nan": expr.nan_policy.value == "propagate",
                }
            elif not isinstance(expr.scope, BarCountScope):
                return None
            else:
                child = build(expr.operands[0])
                if child is None:
                    return None
                node = {
                    "kind": "scope", "child": child, "count": int(expr.scope.resolved_count()),
                    "op": expr.op, "min_periods": expr.min_periods or 1,
                    "propagate_nan": expr.nan_policy.value == "propagate",
                }
            if expr.op=='quantile':
                q=expr.quantile_value
                if not isinstance(q,ConstExpr):raise TypeError('scope quantile must resolve to a scalar')
                node['quantile']=float(q.value)
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
        elif isinstance(expr,(BarSinceOp,BarDistanceOp)):
            is_match=isinstance(expr,BarDistanceOp)
            child=build(expr.value if is_match else expr.condition)
            if child is None:return None
            dependencies=[]
            def external(value):
                index=build(value)
                if index is None:raise TypeError('match dependency cannot compile to Rust')
                if index not in dependencies:dependencies.append(index)
                return dependencies.index(index)
            predicate=_match_predicate(expr.condition,external) if is_match else None
            partition=expr.scope.resolved_count(source_freq=source_freq,products=products) if isinstance(expr.scope,BarCountScope) else None
            lookback=BarCountScope(expr.lookback).resolved_count(source_freq=source_freq,products=products) if expr.lookback is not None else None
            boundary=None
            if isinstance(expr.scope,TradingDayScope):
                event='trading_day_start';boundary_key=('event_boundary',event)
                if boundary_key not in memo:
                    if event not in boundaries:boundaries.append(event)
                    memo[boundary_key]=len(nodes);nodes.append(dict(kind='boundary',index=boundaries.index(event)))
                    keys.append(repr(boundary_key));key_tuples.append(boundary_key)
                boundary=memo[boundary_key]
            default=expr.operands[-1];dynamic=isinstance(default,ScopeLengthDefault)
            import math
            value=0.0 if dynamic else float(default.value)
            node=dict(kind='search',child=child,dependencies=dependencies,boundary=boundary,predicate=predicate,
                partition=partition,lookback=lookback,gap_ns=int(pd.Timedelta(expr.scope.gap).value) if isinstance(expr.scope,SessionScope) else None,
                nearest=expr.select=='nearest',default_scope=dynamic,default=None if math.isnan(value) else value,
                include_current=getattr(expr,'include_current',False),propagate_nan=expr.nan_policy.value=='propagate')
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
    return {"columns": columns, "boundaries": boundaries, "term_columns": term_columns, "keys": keys, "key_tuples": key_tuples,
            "nodes": nodes, "outputs": [output]}


def factor_alpha_plan_spec(factor: Any) -> dict[str, Any] | None:
    expression = getattr(factor, "_func_expr", None) or getattr(factor, "_expr", None)
    if expression is None:
        return None
    return alpha_plan_spec(expression)
