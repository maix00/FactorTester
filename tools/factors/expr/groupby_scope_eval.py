"""Labelled adapter to alpha-algo's shared scope-partition kernel.

No Python per-Bar aggregation or second scope state machine lives here.
"""
from __future__ import annotations
from typing import Any
import numpy as np
import pandas as pd
from tools.data.types import finest_index
from .bar_search_eval import _observed_mask
from .lookback_scope import BarCountScope, LookbackScope, SessionScope, TradingDayScope

# Kept for legacy tests that toggle the former vectorized/per-bar
# branch; both now route through the same Rust scope kernel.
_ARG_EXTREME_VECTOR_FLOOR = 10**9

GROUPED_AGGREGATIONS = frozenset({
    "mean", "std", "var", "min", "max", "sum", "median", "quantile", "argmax", "argmin",
})


def apply_grouped(op: str, scope: LookbackScope, data: pd.DataFrame, *, ctx: Any,
                  quantile: float | None = None, trunc_start: int | None = None,
                  trunc_end: int | None = None, min_periods: int = 1,
                  propagate_nan: bool = True) -> pd.DataFrame:
    if op not in GROUPED_AGGREGATIONS:
        raise ValueError(f"Unknown groupby_scope aggregation: {op}")
    if isinstance(scope, BarCountScope):
        kind, count, gap = 1, scope.resolved_count(ctx=ctx), 0
    elif isinstance(scope, TradingDayScope):
        if ctx.panel_timeline is None:
            raise ValueError("trading_day scope requires panel_timeline")
        kind, count, gap = 2, 0, 0
    elif isinstance(scope, SessionScope):
        kind, count, gap = 3, 0, int(pd.Timedelta(scope.gap).value)
    else:
        raise TypeError(f"unsupported groupby_scope scope: {scope!r}")
    if data.empty:
        return data.astype(float)
    from alpha import BatchPlan
    source_index = finest_index(data.index) if isinstance(data.index, pd.MultiIndex) else data.index
    times = (source_index.as_unit('ns').asi8 if isinstance(source_index, pd.DatetimeIndex)
             else np.arange(len(data), dtype=np.int64))
    days = (pd.factorize(ctx.panel_timeline.trading_days, sort=False)[0].astype(np.int64)
            if kind == 2 else np.zeros(len(data), dtype=np.int64))
    if len(days) != len(data):
        days = pd.factorize(pd.Series(np.asarray(ctx.panel_timeline.trading_days),
                                     index=ctx.panel_timeline.index).reindex(data.index), sort=False)[0].astype(np.int64)
    observed = np.ascontiguousarray(_observed_mask(data, ctx).T, dtype=np.uint8)
    values = np.ascontiguousarray(data.to_numpy(dtype=float).T).reshape(-1)
    plan = BatchPlan()
    grid = plan.grid(np.ascontiguousarray(times), np.ascontiguousarray(days), observed.reshape(-1))
    column = plan.add('column', [], [0.0], [], grid)
    params = [float(kind), float(count), float(gap), float(max(1, min_periods)),
              float(propagate_nan), 0.5 if quantile is None else float(quantile),
              -1.0 if trunc_start is None else float(max(0, trunc_start)),
              -1.0 if trunc_end is None else float(max(0, trunc_end))]
    output = plan.add('scope:' + op, [column], params, [], grid)
    result = plan.execute_panel([values], [output], len(data.columns))[0]
    return pd.DataFrame(np.asarray(result).reshape(len(data.columns), len(data)).T,
                        index=data.index, columns=data.columns)
