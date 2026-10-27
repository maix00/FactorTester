"""Compile FactorExpr into a shared Rust time × product DAG.

Python supplies source arrays and labelled timeline metadata. Sampling, causal
as-of carry, arithmetic, temporal searches and matrix kernels execute in Rust.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from tools.data.types import DataFreq, finest_index
from .core import EvaluateContext, FactorExpr
from .leaf import ColumnRef, ConstExpr, CategoryBoolRef
from .composite import CompositeExpr
from .rolling import RollingOp, WindowBarsExpr, IntervalBarsExpr, _resolve_windows
from .conditional import WhereOp
from .shift import ShiftOp
from .groupby_scope import GroupByScopeOp
from .cross_sectional import CrossSectionalOp
from .bar_search import BarSinceOp, BarDistanceOp, ScopeLengthDefault
from .lookback_scope import BarCountScope, TradingDayScope, SessionScope
from .signal_align import SignalAlign, _index_level_freqs, _named_time_index
from .match_refs import MatchValueRef
from .term_structure import TermStructureOp
from .pointwise import POINTWISE_OPS


@dataclass(eq=False)
class _Grid:
    id: int
    index: pd.Index
    positions: np.ndarray
    times: np.ndarray


@dataclass
class _Ref:
    id: int
    grid: _Grid
    signal: DataFreq | None = None
    scalar: bool = False
    columns: tuple = ()


def _times(index: pd.Index) -> np.ndarray:
    values = finest_index(index) if isinstance(index, pd.MultiIndex) else index
    if isinstance(values, pd.DatetimeIndex):
        return np.ascontiguousarray(values.as_unit('ns').asi8)
    return np.arange(len(index), dtype=np.int64)


def _walk(expressions):
    seen = set()
    def visit(expr):
        key = expr._structural_key()
        if key in seen:
            return
        seen.add(key)
        yield expr
        if not isinstance(expr, TermStructureOp):
            for operand in getattr(expr, '_operands', ()):
                yield from visit(operand)
    for expression in expressions:
        yield from visit(expression)


class _PlanBuilder:
    def __init__(self, ctx: EvaluateContext, expressions: list[FactorExpr]):
        from alpha import BatchPlan
        self.ctx = ctx
        self.plan = BatchPlan()
        self.inputs: list[np.ndarray] = []
        self.memo: dict[tuple, _Ref] = {}
        self.aligned: dict[tuple, _Ref] = {}
        self.products = tuple(ctx.products)
        self.frames = {}
        for expr in _walk(expressions):
            if isinstance(expr, ColumnRef):
                self.frames[expr._structural_key()] = expr._evaluate(ctx)
            elif getattr(expr,'_rust_frame_input',False) and isinstance(getattr(expr,'frame',None),pd.DataFrame) and not getattr(expr,'_operands',()):
                self.frames[expr._structural_key()] = expr.frame
        if ctx.panel_timeline is not None:
            index = ctx.panel_timeline.index
        elif self.frames:
            index = next(iter(self.frames.values())).index
        elif ctx.preloaded:
            index = next(iter(ctx.preloaded.values())).index
            for product in self.products:
                frame = ctx.preloaded.get((product, ctx.freq.name))
                if frame is not None:
                    index = index.union(frame.index, sort=False)
        else:
            raise ValueError('a Rust panel plan requires a concrete source timeline')
        for frame in self.frames.values():
            if not index.equals(frame.index):
                index = index.union(frame.index, sort=False)
        if isinstance(index, pd.MultiIndex):
            order = np.argsort(_times(index), kind='stable')
            index = index.take(order)
        elif isinstance(index, pd.DatetimeIndex):
            index = index.sort_values()
        self.index = index
        if (ctx.panel_timeline is not None
                and hasattr(ctx.panel_timeline, 'observed')
                and ctx.panel_timeline.index.equals(index)
                and ctx.panel_timeline.products == self.products):
            self.observed = ctx.panel_timeline.observed
            self.days = ctx.panel_timeline.days
        elif ctx.panel_timeline is not None:
            self.observed = ctx.panel_timeline.observed_mask.reindex(
                index=index, columns=self.products, fill_value=False,
            ).to_numpy(dtype=np.uint8).T
            day_values = pd.Series(np.asarray(ctx.panel_timeline.trading_days),
                                   index=ctx.panel_timeline.index).reindex(index)
            self.days = pd.factorize(day_values, sort=False)[0].astype(np.int64)
        else:
            self.observed = np.ones((len(self.products), len(index)), dtype=np.uint8)
            if ctx.preloaded:
                for g, product in enumerate(self.products):
                    frame = ctx.preloaded.get((product, ctx.freq.name))
                    if frame is not None:
                        self.observed[g] = index.isin(frame.index)
            day_values = index.get_level_values(0) if isinstance(index, pd.MultiIndex) else index
            if isinstance(day_values, pd.DatetimeIndex):
                day_values = day_values.normalize()
            self.days = pd.factorize(day_values, sort=False)[0].astype(np.int64)
        self.base = self.grid(index, np.arange(len(index), dtype=np.int64))

    def input(self, values) -> int:
        self.inputs.append(np.ascontiguousarray(values, dtype=float).reshape(-1))
        return len(self.inputs) - 1

    def grid(self, index, positions) -> _Grid:
        times = _times(index)
        grid_id = self.plan.grid(times, np.ascontiguousarray(self.days[positions]),
                                 np.ascontiguousarray(self.observed[:, positions]).reshape(-1))
        return _Grid(grid_id, index, positions, times)

    def add(self, op, children=(), params=(), indices=(), *, grid=None,
            signal=None, scalar=False, columns=None):
        grid = self.base if grid is None else grid
        node = self.plan.add(op, [child.id for child in children], list(params),
                             list(indices), grid.id)
        return _Ref(node, grid, signal, scalar,
                    self.products if columns is None else tuple(columns))

    def align(self, ref: _Ref, grid: _Grid) -> _Ref:
        if ref.scalar or ref.grid is grid:
            return ref
        key = (ref.id, grid.id)
        if key not in self.aligned:
            if ref.signal is not None:
                mapping = self.plan.asof_indices(ref.grid.times, grid.times)
            else:
                mapping = ref.grid.index.get_indexer(grid.index)
            self.aligned[key] = self.add('reindex', [ref], indices=mapping,
                                        grid=grid, columns=ref.columns)
        return self.aligned[key]

    def common(self, refs):
        non_scalar = [ref for ref in refs if not ref.scalar]
        if not non_scalar:
            return self.base, None
        raw = [ref for ref in non_scalar if ref.signal is None]
        if raw:
            return raw[0].grid, None
        # Equal frequency follows the right operand, as in pointwise alignment.
        chosen = min(reversed(non_scalar), key=lambda ref: ref.signal.value)
        return chosen.grid, chosen.signal

    def point(self, op, refs):
        grid, signal = self.common(refs)
        columns = max(refs, key=lambda ref: len(ref.columns) if not ref.scalar else 0).columns
        return self.add(op, [self.align(ref, grid) for ref in refs], grid=grid,
                        signal=signal, scalar=all(ref.scalar for ref in refs), columns=columns)

    def scope(self, scope):
        if isinstance(scope, BarCountScope):
            return 1, scope.resolved_count(ctx=self.ctx), 0
        if isinstance(scope, TradingDayScope):
            if self.ctx.panel_timeline is None:
                raise ValueError('trading_day scope requires panel_timeline')
            return 2, 0, 0
        if isinstance(scope, SessionScope):
            return 3, 0, int(pd.Timedelta(scope.gap).value)
        raise TypeError(f'unsupported scope {scope!r}')

    def match_predicate(self,expr,grid,dependencies):
        if isinstance(expr,MatchValueRef):return {'op':expr.role}
        if isinstance(expr,ConstExpr):return {'op':'const','value':None if np.isnan(float(expr.value)) else float(expr.value)}
        if isinstance(expr,WhereOp):
            c,a,b=[self.match_predicate(x,grid,dependencies) for x in expr.operands]
            return dict(op='where',condition=c,when_true=a,when_false=b)
        if type(expr) is CompositeExpr and expr.op in POINTWISE_OPS:
            args=[self.match_predicate(x,grid,dependencies) for x in expr.operands]
            op={'bimax':'max','bimin':'min'}.get(expr.op,expr.op)
            if len(args)==1:return dict(op='unary',kind=op,a=args[0])
            result=args[0]
            for child in args[1:]:result=dict(op='binary',kind=op,a=result,b=child)
            return result
        child=self.align(self.build(expr),grid)
        if all(child.id!=old.id for old in dependencies):dependencies.append(child)
        return dict(op='input',index=next(i for i,x in enumerate(dependencies) if x.id==child.id))

    def search(self,expr):
        import json
        child=self.build(expr.value if isinstance(expr,BarDistanceOp) else expr.condition)
        if child.signal is not None:child=self.align(child,self.base)
        dependencies=[]
        predicate=self.match_predicate(expr.condition,child.grid,dependencies) if isinstance(expr,BarDistanceOp) else None
        refs=[child,*dependencies]
        nodes=[dict(kind='column',index=i) for i in range(len(refs))]
        partition=expr.scope.resolved_count(ctx=self.ctx) if isinstance(expr.scope,BarCountScope) else None
        lookback=BarCountScope(expr.lookback).resolved_count(ctx=self.ctx) if expr.lookback is not None else None
        day=isinstance(expr.scope,TradingDayScope)
        if day and self.ctx.panel_timeline is None:raise ValueError('trading_day search requires frozen panel_timeline')
        boundary=None
        if day:boundary=len(nodes);nodes.append(dict(kind='boundary',index=0))
        default=expr.operands[-1];dynamic=isinstance(default,ScopeLengthDefault)
        value=0.0 if dynamic else float(default.value)
        nodes.append(dict(kind='search',child=0,dependencies=list(range(1,len(refs))),boundary=boundary,
            predicate=predicate,partition=partition,lookback=lookback,
            gap_ns=int(pd.Timedelta(expr.scope.gap).value) if isinstance(expr.scope,SessionScope) else None,
            nearest=expr.select=='nearest',default_scope=dynamic,default=None if np.isnan(value) else value,
            include_current=getattr(expr,'include_current',False),propagate_nan=expr.nan_policy.value=='propagate'))
        index=self.plan.add_kernel(json.dumps(dict(nodes=nodes,outputs=[len(nodes)-1]),allow_nan=False),
            [r.id for r in refs],child.grid.id,len(self.products),day)
        return _Ref(index,child.grid,child.signal,False,child.columns)

    def signal(self, expr):
        child = self.build(expr.operands[0])
        if child.signal is not None:
            child = self.align(child, self.base)
        source = child.grid
        freq = DataFreq(expr.signal_freq)
        levels = _index_level_freqs(source.index, target_freq=freq)
        template, names = _named_time_index(pd.DataFrame(index=source.index), levels)
        level = next((item for item in levels if freq.value % item.freq.value == pd.Timedelta(0)), None)
        if level is None:
            raise ValueError(f'frequency {freq} is not an integer multiple of an input frequency')
        multiple = int(freq.value / level.freq.value)
        keys = pd.DatetimeIndex(template.index.get_level_values(level.pos)).as_unit('ns').asi8
        bp, mask = expr.basepoint, []
        if freq.is_day_multiple() and expr.daily_basepoint is not None:
            mask = list(pd.DatetimeIndex(finest_index(source.index)).time == pd.Timestamp(expr.daily_basepoint).time())
            bp = 'mask'
        elif callable(bp):
            selection = bp(template.groupby(names[level.pos]))
            if not isinstance(selection, pd.Series) or selection.dtype != bool:
                raise TypeError('basepoint function must return a boolean Series')
            mask, bp = selection.to_list(), 'mask'
        gap = int(pd.Timedelta(expr.end_session_gap).value) if expr.end_session_skip and not freq.is_day_multiple() else None
        positions = np.asarray(self.plan.signal_indices(np.ascontiguousarray(keys), source.times,
                                                       multiple, bp, mask, gap), dtype=np.int64)
        keep = [i for i, name in enumerate(names) if not str(name).startswith('_SIGNAL@')]
        arrays = [template.index.get_level_values(i).take(positions) for i in keep]
        new_names = [f'_SIGNAL@{freq.name}' if i == level.pos else str(names[i]).split('@')[-1] for i in keep]
        index = pd.MultiIndex.from_arrays(arrays, names=new_names)
        grid = self.grid(index, source.positions[positions])
        return self.add('reindex', [child], indices=positions, grid=grid,
                        signal=freq, columns=child.columns)

    def term(self, expr):
        from tools.products.AdjustableTermStructure import TERM_DAYS_TO_MATURITY_COL, TERM_RANK_COL
        near, far, depth, column = expr._term_param_values()
        if min(near, far, depth) < 0:
            raise ValueError('term ranks and depth must be nonnegative')
        slots = max(near, far, depth, 1) + 1
        mapping = np.full((len(self.products), len(self.index)), -1.0)
        raw_values, raw_days, lengths = [], [], []
        trading_days = expr._trading_days_for_index(self.index)
        needs_days = expr.op in {'term_carry_annualized', 'term_slope_segment', 'term_slope', 'term_curvature'}
        for g, product in enumerate(self.products):
            supports = getattr(product, 'supports_term_structure', None)
            if callable(supports) and not supports():
                continue
            if not hasattr(product, 'get_term_structure'):
                continue
            days = trading_days[self.observed[g].astype(bool)].unique()
            batch = getattr(product, 'get_term_structures', None)
            curves = batch(days, depth=slots) if callable(batch) else {day: product.get_term_structure(day, depth=slots) for day in days}
            by_day = {}
            for day in days:
                curve = curves.get(pd.Timestamp(day).normalize(), pd.DataFrame())
                if not isinstance(curve, pd.DataFrame):
                    curve = pd.DataFrame(curve)
                if not curve.empty and TERM_RANK_COL in curve:
                    curve = curve.sort_values(TERM_RANK_COL, kind='stable')
                if not curve.empty and column not in curve:
                    raise KeyError(f'{column!r} not in term curve')
                if not curve.empty and needs_days and TERM_DAYS_TO_MATURITY_COL not in curve:
                    raise KeyError(f'{TERM_DAYS_TO_MATURITY_COL!r} not in term curve')
                count = min(len(curve), slots)
                values, maturity = np.full(slots, np.nan), np.full(slots, np.nan)
                if count:
                    values[:count] = curve[column].to_numpy(dtype=float)[:count]
                    if TERM_DAYS_TO_MATURITY_COL in curve:
                        maturity[:count] = curve[TERM_DAYS_TO_MATURITY_COL].to_numpy(dtype=float)[:count]
                by_day[day] = len(lengths)
                lengths.append(count)
                raw_values.append(values)
                raw_days.append(maturity)
            mapping[g] = [by_day.get(day, -1) if self.observed[g, i] else -1 for i, day in enumerate(trading_days)]
        ops = ['term_spread', 'term_ratio', 'term_log_ratio', 'term_contango',
               'term_carry_annualized', 'term_slope_segment', 'term_rank_value',
               'term_slope', 'term_curvature']
        inputs = [self.input(raw_values), self.input(raw_days), self.input(lengths), self.input(mapping), slots]
        return self.add('term', params=[near, far, depth, ops.index(expr.op)], indices=inputs)

    def build(self, expr) -> _Ref:
        key = expr._structural_key()
        if key in self.memo:
            return self.memo[key]
        if isinstance(expr, ColumnRef):
            frame = self.frames[key].reindex(index=self.index, columns=self.products)
            result = self.add('column', params=[self.input(frame.to_numpy(dtype=float).T)])
        elif isinstance(expr, ConstExpr):
            result = self.add('const', params=[float(expr.value)], scalar=True, columns=())
        elif isinstance(expr, WindowBarsExpr):
            if not isinstance(expr.window, ConstExpr):
                raise ValueError('window_bars requires a resolved window')
            common, count, _ = _resolve_windows(expr.window.value, self.ctx.freq, self.products)
            if not common:
                raise ValueError('window_bars requires a common scalar count across products')
            result = self.add('product', params=[float(count)] * len(self.products))
        elif isinstance(expr, IntervalBarsExpr):
            source_index = finest_index(self.index) if isinstance(self.index, pd.MultiIndex) else self.index
            if not isinstance(source_index, pd.DatetimeIndex):
                raise ValueError('interval_bars requires source timestamps')
            result = self.add('bar_count', indices=[expr.start_ns, expr.end_ns])
        elif isinstance(expr, CategoryBoolRef):
            values = [float(expr.category.is_in_category(expr.category_name, p)) for p in self.products]
            result = self.add('product', params=values)
        elif isinstance(expr, SignalAlign):
            result = self.signal(expr)
        elif isinstance(expr, TermStructureOp):
            result = self.term(expr)
        elif isinstance(expr,(BarSinceOp,BarDistanceOp)):
            result=self.search(expr)
        elif isinstance(expr, (RollingOp, GroupByScopeOp)):
            children = [self.build(c) for c in expr.operands[expr._data_start:expr._data_start + expr._n_data]]
            grid, signal = self.common(children)
            children = [self.align(c, grid) for c in children]
            if isinstance(expr, RollingOp) and type(expr.window).__name__ == "WindowBarsExpr":
                timeline = getattr(self.ctx, "panel_timeline", None)
                value = expr.window.window.value
                if timeline is not None and isinstance(value, str) and value.strip().lower().endswith("d"):
                    lookback = int(value.strip().lower().removesuffix("d"))
                    days = pd.Index(timeline.trading_days)
                    groups: dict[object, list[int]] = {}
                    for row, day in enumerate(days):
                        groups.setdefault(day, []).append(row)
                    indices = [len(groups)]
                    for rows in groups.values():
                        indices.extend([
                            int(timeline.index[rows[0]].value),
                            int(timeline.index[rows[-1]].value),
                            len(rows),
                        ])
                    minimum = expr._min_periods_value(1)
                    params = [lookback, minimum,
                              float(expr.nan_policy.value == 'propagate'),
                              0.5 if expr.quantile is None else float(expr.quantile)]
                    return self.add(
                        'session_rolling:' + expr.op.removeprefix('rolling_'),
                        children, params, indices, grid=grid, signal=signal,
                        columns=children[0].columns,
                    )
                else:
                    raise TypeError('250d rolling requires panel timeline')
            elif isinstance(expr, RollingOp):
                if not isinstance(expr.window, ConstExpr):
                    raise TypeError('rolling window must resolve to a constant')
                common, count, _ = _resolve_windows(expr.window.value, self.ctx.freq, self.products)
                if not common:
                    raise ValueError('rolling duration differs across products; use explicit bar counts')
                scope = (0, count, 0)
                minimum = expr._min_periods_value(count)
                quantile = expr.quantile
            elif isinstance(expr, RollingOp):
                scope = (0, 0, 0); minimum = 1; quantile = None
            else:
                scope = self.scope(expr.scope)
                minimum = expr.min_periods if expr.min_periods is not None else 1
                quantile = expr.quantile_value
                if isinstance(quantile, ConstExpr):
                    quantile = quantile.value
            start = float(expr.trunc_start.value) if isinstance(expr.trunc_start, ConstExpr) else -1.0
            end = float(expr.trunc_end.value) if isinstance(expr.trunc_end, ConstExpr) else -1.0
            params = [*scope, minimum, float(expr.nan_policy.value == 'propagate'),
                      0.5 if quantile is None else float(quantile), start, end]
            if not (isinstance(expr, RollingOp) and type(expr.window).__name__ == "WindowBarsExpr"):
                result = self.add(('rolling:' if isinstance(expr, RollingOp) else 'scope:') + expr.op.removeprefix('rolling_'),
                                  children, params, grid=grid, signal=signal, columns=children[0].columns)
        elif isinstance(expr, CrossSectionalOp):
            children = [self.build(c) for c in expr.operands]
            grid, signal = self.common(children)
            categories = []
            if expr.category is not None:
                categories = [-1] * len(self.products)
                for label_id, label in enumerate(expr.category.categories):
                    for g, product in enumerate(self.products):
                        if expr.category.is_in_category(label, product):
                            categories[g] = label_id
            priority = {p: i for i, p in enumerate(sorted(self.products, key=str))}
            result = self.add('cross:' + expr.op.removeprefix('cs_'),
                              [self.align(c, grid) for c in children], categories,
                              [priority[p] for p in self.products], grid=grid, signal=signal,
                              columns=('IC',) if expr.op in {'cs_corr', 'cs_spearman'} else self.products)
        elif isinstance(expr, ShiftOp):
            child = self.build(expr.operand)
            periods = int(expr.periods.value)
            if periods < 0:
                raise ValueError('negative shift is not a causal factor')
            result = self.add('shift', [child], [periods], grid=child.grid,
                              signal=child.signal, columns=child.columns)
        elif isinstance(expr, WhereOp):
            result = self.point('where', [self.build(c) for c in expr.operands])
        elif type(expr) is CompositeExpr and expr.op in POINTWISE_OPS:
            children = [self.build(c) for c in expr.operands]
            op = {'bimax': 'max', 'bimin': 'min'}.get(expr.op, expr.op)
            if len(children) == 1:
                result = self.point(op, children)
            else:
                result = children[0]
                for child in children[1:]:
                    result = self.point(op, [result, child])
        elif getattr(expr,'_rust_frame_input',False) and isinstance(getattr(expr,'frame',None),pd.DataFrame) and not getattr(expr,'_operands',()):
            frame=expr.frame.reindex(index=self.index,columns=self.products)
            result=self.add('column',params=[self.input(frame.to_numpy(dtype=float).T)])
        else:
            raise TypeError(f'unsupported Rust plan node: {type(expr).__name__}')
        self.memo[key] = result
        return result


def evaluate_rust_plan(expressions: list[FactorExpr], ctx: EvaluateContext) -> list[pd.DataFrame] | None:
    """Execute once for all products and outputs, sharing repeated subgraphs."""
    if not expressions or any(isinstance(e, ConstExpr) for e in expressions) or (len(expressions)==1 and isinstance(expressions[0],ColumnRef)):
        return None
    if any(unsupported_plan_nodes(e) for e in expressions):
        return None
    builder = _PlanBuilder(ctx, expressions)
    outputs = [builder.build(expr) for expr in expressions]
    arrays = builder.plan.execute_panel(builder.inputs, [ref.id for ref in outputs], len(builder.products))
    return [pd.DataFrame(np.asarray(values).reshape(len(ref.columns), len(ref.grid.index)).T,
                         index=ref.grid.index, columns=ref.columns)
            for values, ref in zip(arrays, outputs, strict=True)]


def try_evaluate_rust_plan(expression: FactorExpr, ctx: EvaluateContext) -> pd.DataFrame | None:
    result = evaluate_rust_plan([expression], ctx)
    return None if result is None else result[0]


def plan_identity(expressions: list[FactorExpr]) -> tuple[tuple, ...]:
    return tuple(node._structural_key() for node in _walk(expressions))


_PLAN_SUPPORTED = (ColumnRef, ConstExpr, RollingOp, WindowBarsExpr, IntervalBarsExpr, CompositeExpr, WhereOp, ShiftOp,
                   GroupByScopeOp, BarSinceOp, BarDistanceOp, CrossSectionalOp,
                   SignalAlign, CategoryBoolRef, MatchValueRef, ScopeLengthDefault,
                   TermStructureOp)


def unsupported_plan_nodes(expression: FactorExpr) -> tuple[str, ...]:
    return tuple(dict.fromkeys(type(node).__name__ for node in _walk([expression])
                               if not isinstance(node, _PLAN_SUPPORTED) and not (isinstance(getattr(node,"frame",None),pd.DataFrame) and not getattr(node,"_operands",()))))
